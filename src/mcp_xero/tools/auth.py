"""Authentication tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..auth import XeroOAuth

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

    return {"error": f"Unknown auth tool: {name}"}
