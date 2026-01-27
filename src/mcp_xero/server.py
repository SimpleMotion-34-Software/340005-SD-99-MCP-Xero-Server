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
        self.oauth = XeroOAuth()
        self.client = XeroClient(self.oauth)

        # Register handlers
        self._register_handlers()

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
        # Authentication tools
        if name.startswith("xero_auth") or name in ("xero_connect", "xero_disconnect",
                                                     "xero_list_tenants", "xero_set_tenant",
                                                     "xero_list_profiles", "xero_set_profile"):
            return await handle_auth_tool(name, arguments, self.oauth)

        # Check authentication for other tools
        tokens = await self.oauth.get_valid_tokens()
        if not tokens:
            return {
                "error": "Not authenticated with Xero",
                "message": "Use xero_connect to connect to Xero first",
            }

        # Contact tools
        if name.startswith("xero_") and "contact" in name:
            return await handle_contact_tool(name, arguments, self.client)

        # Quote tools
        if name.startswith("xero_") and "quote" in name:
            return await handle_quote_tool(name, arguments, self.client)

        # Invoice tools
        if name.startswith("xero_") and "invoice" in name:
            return await handle_invoice_tool(name, arguments, self.client)

        # Payroll tools
        if name.startswith("xero_") and ("payroll" in name or "payrun" in name or "wages" in name):
            return await handle_payroll_tool(name, arguments, self.client)

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
