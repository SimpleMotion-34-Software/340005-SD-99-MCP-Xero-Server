"""OAuth flow handler for Xero authentication."""

import asyncio
import os
import secrets
import subprocess
import sys
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from .token_store import TokenSet, TokenStore


def _get_keychain_password_macos(service: str) -> str | None:
    """Retrieve password from macOS Keychain.

    Args:
        service: Keychain service name

    Returns:
        Password if found, None otherwise
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _get_credential_password_windows(target: str) -> str | None:
    """Retrieve password from Windows Credential Manager.

    Args:
        target: Credential target name

    Returns:
        Password if found, None otherwise
    """
    # PowerShell script to retrieve credential
    ps_script = f'''
    $cred = Get-StoredCredential -Target "{target}" -ErrorAction SilentlyContinue
    if ($cred) {{
        $cred.GetNetworkCredential().Password
    }}
    '''

    # Try using cmdkey first (built-in, doesn't require CredentialManager module)
    # Format: cmdkey /list shows credentials, but can't retrieve passwords directly
    # Use PowerShell with .NET instead
    ps_script_dotnet = f'''
    Add-Type -AssemblyName System.Security
    $target = "{target}"
    try {{
        [Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime] | Out-Null
        $vault = New-Object Windows.Security.Credentials.PasswordVault
        $cred = $vault.Retrieve("xero-mcp", $target)
        $cred.RetrievePassword()
        Write-Output $cred.Password
    }} catch {{
        # Fallback: try generic credential
        $sig = @"
[DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern bool CredRead(string target, int type, int flags, out IntPtr credential);
[DllImport("advapi32.dll")]
public static extern void CredFree(IntPtr credential);
"@
        try {{
            Add-Type -MemberDefinition $sig -Namespace Win32 -Name Cred
            $ptr = [IntPtr]::Zero
            if ([Win32.Cred]::CredRead($target, 1, 0, [ref]$ptr)) {{
                $cred = [Runtime.InteropServices.Marshal]::PtrToStructure($ptr, [Type][Win32.Cred+CREDENTIAL])
                $secret = [Runtime.InteropServices.Marshal]::PtrToStringUni($cred.CredentialBlob, $cred.CredentialBlobSize / 2)
                [Win32.Cred]::CredFree($ptr)
                Write-Output $secret
            }}
        }} catch {{}}
    }}
    '''

    try:
        # Simple approach: use cmdkey-style generic credentials via PowerShell
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f'''
                $ErrorActionPreference = "SilentlyContinue"
                $cred = cmdkey /list:"{target}" 2>$null
                if ($LASTEXITCODE -eq 0) {{
                    # Can't get password from cmdkey, try .NET CredentialManager
                    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class CredManager {{
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool CredRead(string target, int type, int flags, out IntPtr credential);

    [DllImport("advapi32.dll")]
    public static extern void CredFree(IntPtr credential);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {{
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public long LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }}

    public static string GetPassword(string target) {{
        IntPtr ptr;
        if (CredRead(target, 1, 0, out ptr)) {{
            CREDENTIAL cred = (CREDENTIAL)Marshal.PtrToStructure(ptr, typeof(CREDENTIAL));
            string password = Marshal.PtrToStringUni(cred.CredentialBlob, cred.CredentialBlobSize / 2);
            CredFree(ptr);
            return password;
        }}
        return null;
    }}
}}
"@
                    $password = [CredManager]::GetPassword("{target}")
                    if ($password) {{ Write-Output $password }}
                }}
                ''',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _get_secret_tool_password_linux(name: str) -> str | None:
    """Retrieve password from Linux secret storage using secret-tool (libsecret).

    Args:
        name: Secret name (e.g., 'xero-client-id')

    Returns:
        Password if found, None otherwise

    Requires:
        - libsecret-tools package (provides secret-tool command)
        - A running secret service (GNOME Keyring, KDE Wallet, etc.)
    """
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", "xero-mcp", "name", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _get_secure_credential(name: str) -> str | None:
    """Retrieve credential from platform-specific secure storage.

    Args:
        name: Credential name (e.g., 'xero-client-id')

    Returns:
        Credential value if found, None otherwise

    Platform support:
        - macOS: Keychain (security command)
        - Windows: Credential Manager (PowerShell)
        - Linux: libsecret via secret-tool (GNOME Keyring, KDE Wallet)
    """
    if sys.platform == "darwin":
        return _get_keychain_password_macos(name)
    elif sys.platform == "win32":
        return _get_credential_password_windows(name)
    elif sys.platform.startswith("linux"):
        return _get_secret_tool_password_linux(name)
    return None

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
        redirect_uri: str = "https://localhost:8742/callback",
        token_store: TokenStore | None = None,
    ):
        """Initialize OAuth handler.

        Args:
            client_id: Xero app client ID (defaults to keychain or XERO_CLIENT_ID env var)
            client_secret: Xero app client secret (defaults to keychain or XERO_CLIENT_SECRET env var)
            redirect_uri: OAuth redirect URI
            token_store: Token storage handler

        Credential lookup order:
            1. Explicit parameter
            2. Platform secure storage:
               - macOS: Keychain (xero-client-id, xero-client-secret)
               - Windows: Credential Manager (xero-client-id, xero-client-secret)
            3. Environment variable (XERO_CLIENT_ID, XERO_CLIENT_SECRET)
        """
        self.client_id = (
            client_id
            or _get_secure_credential("xero-client-id")
            or os.environ.get("XERO_CLIENT_ID", "")
        )
        self.client_secret = (
            client_secret
            or _get_secure_credential("xero-client-secret")
            or os.environ.get("XERO_CLIENT_SECRET", "")
        )
        self.redirect_uri = redirect_uri
        self.token_store = token_store or TokenStore()
        self._state: str | None = None
        self._callback_server: web.AppRunner | None = None

    @property
    def is_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.client_secret)

    async def authenticate_client_credentials(self) -> TokenSet:
        """Authenticate using client credentials grant (for Custom Connections).

        This is used for Xero Custom Connection apps which are pre-authorized
        to a specific organization and don't require user interaction.

        Returns:
            Token set with access token

        Raises:
            ValueError: If credentials not configured or auth fails
        """
        if not self.is_configured:
            raise ValueError("XERO_CLIENT_ID and XERO_CLIENT_SECRET must be set")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    raise ValueError(f"Client credentials auth failed: {error}")

                data = await response.json()

        # Get tenant ID from connections
        tenant_id = await self._get_tenant_id(data["access_token"])

        tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),  # May not have refresh token
            expires_at=datetime.now().timestamp() + data["expires_in"],
            token_type=data["token_type"],
            scope=data.get("scope", "").split(),
            tenant_id=tenant_id,
        )

        self.token_store.save(tokens)
        return tokens

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
                # If no refresh token (Custom Connection), re-authenticate
                if not tokens.refresh_token:
                    tokens = await self.authenticate_client_credentials()
                else:
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
