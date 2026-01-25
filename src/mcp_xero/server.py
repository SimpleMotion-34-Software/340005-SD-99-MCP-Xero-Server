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
        self._callback_task: asyncio.Task | None = None

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
        if name.startswith("xero_auth"):
            result = await handle_auth_tool(name, arguments, self.oauth)

            # Special handling for auth_url with callback server
            if name == "xero_auth_url" and arguments.get("start_callback_server", True):
                if "authorization_url" in result:
                    # Start callback server in background
                    self._start_callback_server()

            return result

        # Check authentication for other tools
        tokens = await self.oauth.get_valid_tokens()
        if not tokens:
            return {
                "error": "Not authenticated with Xero",
                "message": "Use xero_auth_url to connect to Xero first",
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

        return {"error": f"Unknown tool: {name}"}

    def _start_callback_server(self) -> None:
        """Start OAuth callback server in background."""
        if self._callback_task and not self._callback_task.done():
            return  # Already running

        async def run_callback_server():
            try:
                code = await self.oauth.start_callback_server()
                await self.oauth.exchange_code(code)
                logger.info("OAuth callback completed successfully")
            except asyncio.TimeoutError:
                logger.warning("OAuth callback timed out")
            except Exception as e:
                logger.error(f"OAuth callback error: {e}")

        self._callback_task = asyncio.create_task(run_callback_server())

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
