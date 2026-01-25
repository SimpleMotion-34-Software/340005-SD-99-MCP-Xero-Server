"""OAuth flow handler for Xero authentication."""

import asyncio
import os
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from .token_store import TokenSet, TokenStore

# Xero OAuth endpoints
XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

# Default scopes for quotes and invoices
DEFAULT_SCOPES = [
    "openid",
    "profile",
    "email",
    "accounting.transactions",
    "accounting.contacts",
    "accounting.settings.read",
    "offline_access",
]


class XeroOAuth:
    """Handle Xero OAuth 2.0 authentication flow."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = "http://localhost:8742/callback",
        token_store: TokenStore | None = None,
    ):
        """Initialize OAuth handler.

        Args:
            client_id: Xero app client ID (defaults to XERO_CLIENT_ID env var)
            client_secret: Xero app client secret (defaults to XERO_CLIENT_SECRET env var)
            redirect_uri: OAuth redirect URI
            token_store: Token storage handler
        """
        self.client_id = client_id or os.environ.get("XERO_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("XERO_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri
        self.token_store = token_store or TokenStore()
        self._state: str | None = None
        self._callback_server: web.AppRunner | None = None

    @property
    def is_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, scopes: list[str] | None = None) -> tuple[str, str]:
        """Generate authorization URL for user to visit.

        Args:
            scopes: OAuth scopes to request (defaults to DEFAULT_SCOPES)

        Returns:
            Tuple of (authorization_url, state)
        """
        if not self.is_configured:
            raise ValueError("XERO_CLIENT_ID and XERO_CLIENT_SECRET must be set")

        self._state = secrets.token_urlsafe(32)
        scopes = scopes or DEFAULT_SCOPES

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": self._state,
        }

        return f"{XERO_AUTH_URL}?{urlencode(params)}", self._state

    async def exchange_code(self, code: str, state: str | None = None) -> TokenSet:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback
            state: State parameter to verify (optional)

        Returns:
            Token set with access and refresh tokens

        Raises:
            ValueError: If state doesn't match or exchange fails
        """
        if state and self._state and state != self._state:
            raise ValueError("State mismatch - possible CSRF attack")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    raise ValueError(f"Token exchange failed: {error}")

                data = await response.json()

        # Get tenant ID from connections
        tenant_id = await self._get_tenant_id(data["access_token"])

        tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now().timestamp() + data["expires_in"],
            token_type=data["token_type"],
            scope=data.get("scope", "").split(),
            tenant_id=tenant_id,
        )

        self.token_store.save(tokens)
        return tokens

    async def refresh_tokens(self) -> TokenSet:
        """Refresh expired access token using refresh token.

        Returns:
            New token set

        Raises:
            ValueError: If no tokens exist or refresh fails
        """
        current = self.token_store.load()
        if not current:
            raise ValueError("No tokens to refresh - authentication required")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": current.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    # Clear invalid tokens
                    self.token_store.delete()
                    raise ValueError(f"Token refresh failed: {error}")

                data = await response.json()

        tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now().timestamp() + data["expires_in"],
            token_type=data["token_type"],
            scope=data.get("scope", "").split(),
            tenant_id=current.tenant_id,
        )

        self.token_store.save(tokens)
        return tokens

    async def get_valid_tokens(self) -> TokenSet | None:
        """Get valid tokens, refreshing if necessary.

        Returns:
            Valid token set or None if not authenticated
        """
        tokens = self.token_store.load()
        if not tokens:
            return None

        if tokens.is_expired:
            try:
                tokens = await self.refresh_tokens()
            except ValueError:
                return None

        return tokens

    async def _get_tenant_id(self, access_token: str) -> str | None:
        """Get tenant ID from Xero connections.

        Args:
            access_token: Valid access token

        Returns:
            Tenant ID of first connected organization
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                XERO_CONNECTIONS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response:
                if response.status != 200:
                    return None

                connections = await response.json()
                if connections:
                    return connections[0]["tenantId"]

        return None

    async def start_callback_server(self) -> str:
        """Start local HTTP server to capture OAuth callback.

        Returns:
            Authorization code from callback

        Raises:
            TimeoutError: If callback not received within timeout
        """
        code_future: asyncio.Future[str] = asyncio.Future()

        async def handle_callback(request: web.Request) -> web.Response:
            code = request.query.get("code")
            state = request.query.get("state")
            error = request.query.get("error")

            if error:
                code_future.set_exception(ValueError(f"OAuth error: {error}"))
                return web.Response(
                    text="<html><body><h1>Authentication Failed</h1>"
                    f"<p>Error: {error}</p></body></html>",
                    content_type="text/html",
                )

            if not code:
                code_future.set_exception(ValueError("No authorization code received"))
                return web.Response(
                    text="<html><body><h1>Error</h1>"
                    "<p>No authorization code received</p></body></html>",
                    content_type="text/html",
                )

            # Verify state
            if state != self._state:
                code_future.set_exception(ValueError("State mismatch"))
                return web.Response(
                    text="<html><body><h1>Error</h1>"
                    "<p>Security check failed</p></body></html>",
                    content_type="text/html",
                )

            code_future.set_result(code)
            return web.Response(
                text="<html><body><h1>Success!</h1>"
                "<p>You can close this window and return to Claude Code.</p></body></html>",
                content_type="text/html",
            )

        app = web.Application()
        app.router.add_get("/callback", handle_callback)

        runner = web.AppRunner(app)
        await runner.setup()

        # Extract port from redirect URI
        port = 8742
        if ":" in self.redirect_uri.split("//")[1]:
            port = int(self.redirect_uri.split(":")[-1].split("/")[0])

        site = web.TCPSite(runner, "localhost", port)
        await site.start()

        self._callback_server = runner

        try:
            # Wait for callback with timeout
            code = await asyncio.wait_for(code_future, timeout=300)  # 5 minute timeout
            return code
        finally:
            await runner.cleanup()
            self._callback_server = None

    def disconnect(self) -> None:
        """Disconnect from Xero by removing stored tokens."""
        self.token_store.delete()

    def get_status(self) -> dict[str, Any]:
        """Get current authentication status.

        Returns:
            Status dictionary with connection info
        """
        if not self.is_configured:
            return {
                "connected": False,
                "configured": False,
                "message": "Xero credentials not configured. Set XERO_CLIENT_ID and XERO_CLIENT_SECRET.",
            }

        tokens = self.token_store.load()
        if not tokens:
            return {
                "connected": False,
                "configured": True,
                "message": "Not connected to Xero. Use xero_auth_url to begin authentication.",
            }

        return {
            "connected": True,
            "configured": True,
            "expired": tokens.is_expired,
            "tenant_id": tokens.tenant_id,
            "scopes": tokens.scope,
            "message": "Connected to Xero" + (" (token expired, will refresh)" if tokens.is_expired else ""),
        }
