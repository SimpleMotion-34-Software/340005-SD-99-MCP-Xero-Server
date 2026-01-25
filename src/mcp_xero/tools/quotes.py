"""Quote tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..xero import XeroClient

QUOTE_TOOLS = [
    Tool(
        name="xero_list_quotes",
        description="List quotes from Xero with optional filtering by status, contact, or date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by quote status",
                    "enum": ["DRAFT", "SENT", "ACCEPTED", "DECLINED", "INVOICED"],
                },
                "contact_id": {
                    "type": "string",
                    "description": "Filter by contact ID",
                },
                "date_from": {
                    "type": "string",
                    "description": "Filter quotes from this date (YYYY-MM-DD format)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter quotes to this date (YYYY-MM-DD format)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination. Default: 1",
                    "default": 1,
                    "minimum": 1,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_get_quote",
        description="Get detailed information about a specific quote by its ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "quote_id": {
                    "type": "string",
                    "description": "The Xero quote ID (UUID format)",
                },
            },
            "required": ["quote_id"],
        },
    ),
    Tool(
        name="xero_create_quote",
        description="Create a new quote in Xero for a contact with line items.",
        inputSchema={
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Contact ID to create the quote for",
                },
                "line_items": {
                    "type": "array",
                    "description": "List of line items for the quote",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "Line item description",
                            },
                            "quantity": {
                                "type": "number",
                                "description": "Quantity (default: 1)",
                                "default": 1,
                            },
                            "unit_amount": {
                                "type": "number",
                                "description": "Price per unit",
                            },
                            "account_code": {
                                "type": "string",
                                "description": "Account code (e.g., '200' for sales)",
                            },
                            "tax_type": {
                                "type": "string",
                                "description": "Tax type (e.g., 'OUTPUT' for GST on sales)",
                            },
                        },
                        "required": ["description", "unit_amount"],
                    },
                },
                "title": {
                    "type": "string",
                    "description": "Quote title",
                },
                "summary": {
                    "type": "string",
                    "description": "Quote summary",
                },
                "date": {
                    "type": "string",
                    "description": "Quote date (YYYY-MM-DD). Defaults to today.",
                },
                "expiry_date": {
                    "type": "string",
                    "description": "Quote expiry date (YYYY-MM-DD)",
                },
                "reference": {
                    "type": "string",
                    "description": "Reference text",
                },
                "terms": {
                    "type": "string",
                    "description": "Terms and conditions",
                },
                "currency_code": {
                    "type": "string",
                    "description": "Currency code (default: AUD)",
                    "default": "AUD",
                },
            },
            "required": ["contact_id", "line_items"],
        },
    ),
    Tool(
        name="xero_update_quote",
        description="Update an existing quote. Only provide fields you want to change.",
        inputSchema={
            "type": "object",
            "properties": {
                "quote_id": {
                    "type": "string",
                    "description": "Quote ID to update",
                },
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["DRAFT", "SENT", "ACCEPTED", "DECLINED"],
                },
                "line_items": {
                    "type": "array",
                    "description": "Updated line items (replaces all existing items)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_amount": {"type": "number"},
                            "account_code": {"type": "string"},
                            "tax_type": {"type": "string"},
                        },
                        "required": ["description", "unit_amount"],
                    },
                },
                "title": {
                    "type": "string",
                    "description": "New title",
                },
                "summary": {
                    "type": "string",
                    "description": "New summary",
                },
                "expiry_date": {
                    "type": "string",
                    "description": "New expiry date (YYYY-MM-DD)",
                },
                "reference": {
                    "type": "string",
                    "description": "New reference",
                },
                "terms": {
                    "type": "string",
                    "description": "New terms",
                },
            },
            "required": ["quote_id"],
        },
    ),
    Tool(
        name="xero_send_quote",
        description="Send a quote via email to the contact. This marks the quote as SENT.",
        inputSchema={
            "type": "object",
            "properties": {
                "quote_id": {
                    "type": "string",
                    "description": "Quote ID to send",
                },
            },
            "required": ["quote_id"],
        },
    ),
    Tool(
        name="xero_convert_quote_to_invoice",
        description="Convert an accepted quote to an invoice. The quote must be in ACCEPTED status.",
        inputSchema={
            "type": "object",
            "properties": {
                "quote_id": {
                    "type": "string",
                    "description": "Quote ID to convert (must be ACCEPTED)",
                },
            },
            "required": ["quote_id"],
        },
    ),
]


def _format_line_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format line items from tool input to Xero API format."""
    formatted = []
    for item in items:
        formatted_item = {
            "Description": item.get("description", ""),
            "Quantity": item.get("quantity", 1),
            "UnitAmount": item.get("unit_amount", 0),
        }
        if "account_code" in item:
            formatted_item["AccountCode"] = item["account_code"]
        if "tax_type" in item:
            formatted_item["TaxType"] = item["tax_type"]
        formatted.append(formatted_item)
    return formatted


async def handle_quote_tool(name: str, arguments: dict[str, Any], client: XeroClient) -> dict[str, Any]:
    """Handle quote tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        client: Xero API client

    Returns:
        Tool result
    """
    try:
        if name == "xero_list_quotes":
            quotes = await client.list_quotes(
                status=arguments.get("status"),
                contact_id=arguments.get("contact_id"),
                page=arguments.get("page", 1),
                date_from=arguments.get("date_from"),
                date_to=arguments.get("date_to"),
            )
            return {
                "quotes": [
                    {
                        "id": q.get("QuoteID"),
                        "number": q.get("QuoteNumber"),
                        "contact_name": q.get("Contact", {}).get("Name"),
                        "status": q.get("Status"),
                        "title": q.get("Title"),
                        "date": q.get("Date"),
                        "expiry_date": q.get("ExpiryDate"),
                        "total": q.get("Total"),
                        "currency": q.get("CurrencyCode"),
                    }
                    for q in quotes
                ],
                "count": len(quotes),
            }

        elif name == "xero_get_quote":
            quote = await client.get_quote(arguments["quote_id"])
            return {
                "quote": {
                    "id": quote.get("QuoteID"),
                    "number": quote.get("QuoteNumber"),
                    "contact": {
                        "id": quote.get("Contact", {}).get("ContactID"),
                        "name": quote.get("Contact", {}).get("Name"),
                    },
                    "status": quote.get("Status"),
                    "title": quote.get("Title"),
                    "summary": quote.get("Summary"),
                    "date": quote.get("Date"),
                    "expiry_date": quote.get("ExpiryDate"),
                    "reference": quote.get("Reference"),
                    "terms": quote.get("Terms"),
                    "sub_total": quote.get("SubTotal"),
                    "total_tax": quote.get("TotalTax"),
                    "total": quote.get("Total"),
                    "currency": quote.get("CurrencyCode"),
                    "line_items": [
                        {
                            "description": li.get("Description"),
                            "quantity": li.get("Quantity"),
                            "unit_amount": li.get("UnitAmount"),
                            "line_amount": li.get("LineAmount"),
                            "tax_type": li.get("TaxType"),
                            "account_code": li.get("AccountCode"),
                        }
                        for li in quote.get("LineItems", [])
                    ],
                }
            }

        elif name == "xero_create_quote":
            line_items = _format_line_items(arguments.get("line_items", []))
            quote = await client.create_quote(
                contact_id=arguments["contact_id"],
                line_items=line_items,
                date=arguments.get("date"),
                expiry_date=arguments.get("expiry_date"),
                reference=arguments.get("reference"),
                terms=arguments.get("terms"),
                title=arguments.get("title"),
                summary=arguments.get("summary"),
                currency_code=arguments.get("currency_code", "AUD"),
            )
            return {
                "success": True,
                "quote": {
                    "id": quote.get("QuoteID"),
                    "number": quote.get("QuoteNumber"),
                    "status": quote.get("Status"),
                    "total": quote.get("Total"),
                },
                "message": f"Quote {quote.get('QuoteNumber')} created successfully",
            }

        elif name == "xero_update_quote":
            line_items = None
            if "line_items" in arguments:
                line_items = _format_line_items(arguments["line_items"])

            quote = await client.update_quote(
                quote_id=arguments["quote_id"],
                status=arguments.get("status"),
                line_items=line_items,
                expiry_date=arguments.get("expiry_date"),
                reference=arguments.get("reference"),
                terms=arguments.get("terms"),
                title=arguments.get("title"),
                summary=arguments.get("summary"),
            )
            return {
                "success": True,
                "quote": {
                    "id": quote.get("QuoteID"),
                    "number": quote.get("QuoteNumber"),
                    "status": quote.get("Status"),
                    "total": quote.get("Total"),
                },
                "message": f"Quote {quote.get('QuoteNumber')} updated successfully",
            }

        elif name == "xero_send_quote":
            quote = await client.send_quote(arguments["quote_id"])
            return {
                "success": True,
                "quote": {
                    "id": quote.get("QuoteID"),
                    "number": quote.get("QuoteNumber"),
                    "status": quote.get("Status"),
                },
                "message": f"Quote {quote.get('QuoteNumber')} sent to contact",
            }

        elif name == "xero_convert_quote_to_invoice":
            invoice = await client.convert_quote_to_invoice(arguments["quote_id"])
            return {
                "success": True,
                "invoice": {
                    "id": invoice.get("InvoiceID"),
                    "number": invoice.get("InvoiceNumber"),
                    "status": invoice.get("Status"),
                    "total": invoice.get("Total"),
                },
                "message": f"Quote converted to invoice {invoice.get('InvoiceNumber')}",
            }

    except Exception as e:
        return {"error": str(e)}

    return {"error": f"Unknown quote tool: {name}"}
