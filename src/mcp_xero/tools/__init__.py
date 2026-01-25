"""MCP tools for Xero integration."""

from .auth import AUTH_TOOLS, handle_auth_tool
from .contacts import CONTACT_TOOLS, handle_contact_tool
from .invoices import INVOICE_TOOLS, handle_invoice_tool
from .quotes import QUOTE_TOOLS, handle_quote_tool

ALL_TOOLS = AUTH_TOOLS + CONTACT_TOOLS + QUOTE_TOOLS + INVOICE_TOOLS

__all__ = [
    "ALL_TOOLS",
    "AUTH_TOOLS",
    "CONTACT_TOOLS",
    "QUOTE_TOOLS",
    "INVOICE_TOOLS",
    "handle_auth_tool",
    "handle_contact_tool",
    "handle_quote_tool",
    "handle_invoice_tool",
]
