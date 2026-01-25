"""Authentication tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..auth import XeroOAuth
from ..auth.oauth import get_active_profile, set_active_profile, list_profiles

AUTH_TOOLS = [
    Tool(
        name="xero_auth_status",
        description="Check the current Xero authentication status. Returns whether you're connected, if credentials are configured, and connection details.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_connect",
        description="Connect to Xero using client credentials (for Custom Connection apps). This authenticates directly without requiring browser interaction. Use this for Xero apps configured as 'Custom Connection' type.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_auth_url",
        description="Get the OAuth authorization URL to connect to Xero. Open this URL in a browser to authorize the connection. After authorizing, Xero will redirect to a local callback URL where the authorization code will be captured automatically.",
        inputSchema={
            "type": "object",
            "properties": {
                "start_callback_server": {
                    "type": "boolean",
                    "description": "Whether to start a local server to capture the callback automatically. Default: true",
                    "default": True,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_auth_callback",
        description="Complete the OAuth flow with an authorization code. Use this if you manually copied the code from the callback URL instead of using the automatic callback server.",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The authorization code from the OAuth callback URL",
                },
                "state": {
                    "type": "string",
                    "description": "The state parameter from the callback (optional, for CSRF verification)",
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="xero_disconnect",
        description="Disconnect from Xero by removing stored authentication tokens.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_list_tenants",
        description="List all Xero organizations (tenants) you have access to. Shows which one is currently active.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_set_tenant",
        description="Switch to a different Xero organization (tenant). Use xero_list_tenants first to see available options. Accepts tenant_id (UUID) or short_code (e.g., 'SP').",
        inputSchema={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The tenant ID (UUID) or short code (e.g., 'SP') to switch to",
                },
            },
            "required": ["tenant_id"],
        },
    ),
    Tool(
        name="xero_list_profiles",
        description="List available Xero credential profiles. Each profile connects to a different Xero Custom Connection app.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_set_profile",
        description="Switch to a different Xero credential profile (e.g., 'SP' for SimpleMotion.Projects, 'SM' for SimpleMotion). This changes which Xero app credentials are used.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "The profile name to switch to (e.g., 'SP', 'SM')",
                },
            },
            "required": ["profile"],
        },
    ),
]


async def handle_auth_tool(name: str, arguments: dict[str, Any], oauth: XeroOAuth) -> dict[str, Any]:
    """Handle authentication tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        oauth: OAuth handler

    Returns:
        Tool result
    """
    if name == "xero_auth_status":
        return oauth.get_status()

    elif name == "xero_connect":
        if not oauth.is_configured:
            return {
                "error": "Xero credentials not configured",
                "message": "Set XERO_CLIENT_ID and XERO_CLIENT_SECRET environment variables",
            }

        try:
            tokens = await oauth.authenticate_client_credentials()
            return {
                "success": True,
                "message": "Successfully connected to Xero using client credentials",
                "tenant_id": tokens.tenant_id,
                "scopes": tokens.scope,
            }
        except ValueError as e:
            return {"error": str(e)}

    elif name == "xero_auth_url":
        if not oauth.is_configured:
            return {
                "error": "Xero credentials not configured",
                "message": "Set XERO_CLIENT_ID and XERO_CLIENT_SECRET environment variables",
            }

        url, state = oauth.get_authorization_url()
        start_server = arguments.get("start_callback_server", True)

        result = {
            "authorization_url": url,
            "state": state,
            "instructions": f"Open this URL in your browser to authorize: {url}",
        }

        if start_server:
            result["callback_info"] = (
                "A local server is listening for the OAuth callback. "
                "After authorizing in the browser, the connection will complete automatically."
            )
            # Note: The actual callback server is started in the server.py
            # when this tool is called. This is just for the response.

        return result

    elif name == "xero_auth_callback":
        code = arguments.get("code")
        state = arguments.get("state")

        if not code:
            return {"error": "Authorization code is required"}

        try:
            tokens = await oauth.exchange_code(code, state)
            return {
                "success": True,
                "message": "Successfully connected to Xero",
                "tenant_id": tokens.tenant_id,
                "scopes": tokens.scope,
            }
        except ValueError as e:
            return {"error": str(e)}

    elif name == "xero_disconnect":
        oauth.disconnect()
        return {
            "success": True,
            "message": "Disconnected from Xero. Stored tokens have been removed.",
        }

    elif name == "xero_list_tenants":
        tenants = oauth.list_tenants()
        if not tenants:
            return {
                "tenants": [],
                "message": "No tenants available. Connect to Xero first.",
            }
        return {
            "tenants": tenants,
            "count": len(tenants),
            "message": f"Found {len(tenants)} organization(s)",
        }

    elif name == "xero_set_tenant":
        tenant_id_or_code = arguments.get("tenant_id")
        if not tenant_id_or_code:
            return {"error": "tenant_id is required"}

        success = oauth.set_active_tenant(tenant_id_or_code)
        if success:
            # Get the tenant info for confirmation
            tenants = oauth.list_tenants()
            active = next((t for t in tenants if t["active"]), None)
            short_code = f" ({active['short_code']})" if active and active.get("short_code") else ""
            return {
                "success": True,
                "tenant_id": active["id"] if active else tenant_id_or_code,
                "tenant_name": active["name"] if active else "Unknown",
                "short_code": active.get("short_code") if active else None,
                "message": f"Switched to {active['name'] if active else tenant_id_or_code}{short_code}",
            }
        else:
            return {
                "error": "Tenant not found",
                "message": "Use xero_list_tenants to see available organizations",
            }

    elif name == "xero_list_profiles":
        profiles = list_profiles()
        return {
            "profiles": profiles,
            "active": get_active_profile(),
            "message": f"Active profile: {get_active_profile()}",
        }

    elif name == "xero_set_profile":
        profile = arguments.get("profile")
        if not profile:
            return {"error": "profile is required"}

        success = set_active_profile(profile)
        if success:
            return {
                "success": True,
                "profile": get_active_profile(),
                "message": f"Switched to profile: {get_active_profile()}. Use xero_connect to authenticate.",
            }
        else:
            profiles = list_profiles()
            available = [p["name"] for p in profiles]
            return {
                "error": f"Profile '{profile}' not found",
                "available": available,
                "message": f"Available profiles: {', '.join(available)}",
            }

    return {"error": f"Unknown auth tool: {name}"}
