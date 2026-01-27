"""MCP Server for Xero integration."""

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from .auth import XeroOAuth
from .auth.oauth import CREDENTIAL_PROFILES, get_active_profile
from .tools import (
    ALL_TOOLS,
    handle_auth_tool,
    handle_contact_tool,
    handle_invoice_tool,
    handle_payroll_tool,
    handle_quote_tool,
)
from .xero import XeroClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class XeroMCPServer:
    """MCP Server for Xero integration."""

    def __init__(self):
        """Initialize the Xero MCP server."""
        self.server = Server("xero-mcp")

        # Multi-profile support: maintain OAuth/Client instances per profile
        self._oauth_instances: dict[str, XeroOAuth] = {}
        self._client_instances: dict[str, XeroClient] = {}

        # Register handlers
        self._register_handlers()

    def get_oauth(self, profile: str | None = None) -> XeroOAuth:
        """Get OAuth instance for a profile, creating if needed.

        Args:
            profile: Profile name (e.g., 'SP', 'SM'). Defaults to active profile.

        Returns:
            XeroOAuth instance for the profile
        """
        profile = (profile or get_active_profile()).upper()
        if profile not in self._oauth_instances:
            self._oauth_instances[profile] = XeroOAuth(profile=profile)
        return self._oauth_instances[profile]

    def get_client(self, profile: str | None = None) -> XeroClient:
        """Get Xero client for a profile, creating if needed.

        Args:
            profile: Profile name (e.g., 'SP', 'SM'). Defaults to active profile.

        Returns:
            XeroClient instance for the profile
        """
        profile = (profile or get_active_profile()).upper()
        if profile not in self._client_instances:
            oauth = self.get_oauth(profile)
            self._client_instances[profile] = XeroClient(oauth)
        return self._client_instances[profile]

    def get_all_clients(self) -> dict[str, XeroClient]:
        """Get clients for all configured profiles.

        Returns:
            Dictionary mapping profile name to XeroClient
        """
        clients = {}
        for profile in CREDENTIAL_PROFILES:
            oauth = self.get_oauth(profile)
            if oauth.is_configured:
                clients[profile] = self.get_client(profile)
        return clients

    def _register_handlers(self) -> None:
        """Register MCP server handlers."""

        @self.server.list_tools()
        async def list_tools():
            """List all available Xero tools."""
            return ALL_TOOLS

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Handle tool calls."""
            logger.info(f"Tool call: {name} with arguments: {arguments}")

            try:
                result = await self._handle_tool(name, arguments)
            except Exception as e:
                logger.exception(f"Error handling tool {name}")
                result = {"error": str(e)}

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _handle_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route tool calls to appropriate handlers.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        # Get profile from arguments (optional, defaults to active profile)
        profile = arguments.get("profile")

        # Authentication tools
        if name.startswith("xero_auth") or name in ("xero_connect", "xero_disconnect",
                                                     "xero_list_tenants", "xero_set_tenant",
                                                     "xero_list_profiles", "xero_set_profile",
                                                     "xero_connect_all"):
            return await handle_auth_tool(name, arguments, self.get_oauth(profile), self)

        # Get client for the specified profile
        oauth = self.get_oauth(profile)
        client = self.get_client(profile)

        # Check authentication for other tools
        tokens = await oauth.get_valid_tokens()
        if not tokens:
            return {
                "error": f"Not authenticated with Xero (profile: {profile or get_active_profile()})",
                "message": "Use xero_connect to connect to Xero first",
            }

        # Contact tools
        if name.startswith("xero_") and "contact" in name:
            return await handle_contact_tool(name, arguments, client)

        # Quote tools
        if name.startswith("xero_") and "quote" in name:
            return await handle_quote_tool(name, arguments, client)

        # Invoice tools
        if name.startswith("xero_") and "invoice" in name:
            return await handle_invoice_tool(name, arguments, client)

        # Payroll tools
        if name.startswith("xero_") and ("payroll" in name or "payrun" in name or "wages" in name):
            return await handle_payroll_tool(name, arguments, client, self)

        return {"error": f"Unknown tool: {name}"}

    async def run(self) -> None:
        """Run the MCP server."""
        logger.info("Starting Xero MCP server")

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


def main() -> None:
    """Main entry point."""
    server = XeroMCPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
