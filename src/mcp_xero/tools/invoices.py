"""Invoice tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..xero import XeroClient

INVOICE_TOOLS = [
    Tool(
        name="xero_list_invoices",
        description="List invoices from Xero with optional filtering by status, contact, type, or date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by invoice status",
                    "enum": ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED"],
                },
                "contact_id": {
                    "type": "string",
                    "description": "Filter by contact ID",
                },
                "invoice_type": {
                    "type": "string",
                    "description": "Invoice type: ACCREC (sales/receivable) or ACCPAY (purchases/payable). Default: ACCREC",
                    "enum": ["ACCREC", "ACCPAY"],
                    "default": "ACCREC",
                },
                "date_from": {
                    "type": "string",
                    "description": "Filter invoices from this date (YYYY-MM-DD format)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter invoices to this date (YYYY-MM-DD format)",
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
        name="xero_get_invoice",
        description="Get detailed information about a specific invoice by its ID or invoice number.",
        inputSchema={
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "The Xero invoice ID (UUID format) or invoice number",
                },
            },
            "required": ["invoice_id"],
        },
    ),
    Tool(
        name="xero_create_invoice",
        description="Create a new invoice in Xero for a contact with line items.",
        inputSchema={
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Contact ID to create the invoice for",
                },
                "line_items": {
                    "type": "array",
                    "description": "List of line items for the invoice",
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
                "invoice_type": {
                    "type": "string",
                    "description": "Invoice type: ACCREC (sales) or ACCPAY (purchases). Default: ACCREC",
                    "enum": ["ACCREC", "ACCPAY"],
                    "default": "ACCREC",
                },
                "date": {
                    "type": "string",
                    "description": "Invoice date (YYYY-MM-DD). Defaults to today.",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date (YYYY-MM-DD)",
                },
                "invoice_number": {
                    "type": "string",
                    "description": "Invoice number (auto-generated if not provided)",
                },
                "reference": {
                    "type": "string",
                    "description": "Reference text",
                },
                "currency_code": {
                    "type": "string",
                    "description": "Currency code (default: AUD)",
                    "default": "AUD",
                },
                "status": {
                    "type": "string",
                    "description": "Initial status. Default: DRAFT",
                    "enum": ["DRAFT", "SUBMITTED"],
                    "default": "DRAFT",
                },
            },
            "required": ["contact_id", "line_items"],
        },
    ),
    Tool(
        name="xero_update_invoice",
        description="Update an existing invoice. Only provide fields you want to change. Note: invoices can only be updated when in DRAFT or SUBMITTED status.",
        inputSchema={
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "Invoice ID to update",
                },
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["DRAFT", "SUBMITTED", "AUTHORISED", "VOIDED"],
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
                "due_date": {
                    "type": "string",
                    "description": "New due date (YYYY-MM-DD)",
                },
                "reference": {
                    "type": "string",
                    "description": "New reference",
                },
            },
            "required": ["invoice_id"],
        },
    ),
    Tool(
        name="xero_send_invoice",
        description="Send an invoice via email to the contact. The invoice must be in AUTHORISED status.",
        inputSchema={
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "Invoice ID to send",
                },
            },
            "required": ["invoice_id"],
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


async def handle_invoice_tool(name: str, arguments: dict[str, Any], client: XeroClient) -> dict[str, Any]:
    """Handle invoice tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        client: Xero API client

    Returns:
        Tool result
    """
    try:
        if name == "xero_list_invoices":
            invoices = await client.list_invoices(
                status=arguments.get("status"),
                contact_id=arguments.get("contact_id"),
                invoice_type=arguments.get("invoice_type", "ACCREC"),
                page=arguments.get("page", 1),
                date_from=arguments.get("date_from"),
                date_to=arguments.get("date_to"),
            )
            return {
                "invoices": [
                    {
                        "id": inv.get("InvoiceID"),
                        "number": inv.get("InvoiceNumber"),
                        "type": inv.get("Type"),
                        "contact_name": inv.get("Contact", {}).get("Name"),
                        "status": inv.get("Status"),
                        "date": inv.get("Date"),
                        "due_date": inv.get("DueDate"),
                        "total": inv.get("Total"),
                        "amount_due": inv.get("AmountDue"),
                        "amount_paid": inv.get("AmountPaid"),
                        "currency": inv.get("CurrencyCode"),
                    }
                    for inv in invoices
                ],
                "count": len(invoices),
            }

        elif name == "xero_get_invoice":
            invoice = await client.get_invoice(arguments["invoice_id"])
            return {
                "invoice": {
                    "id": invoice.get("InvoiceID"),
                    "number": invoice.get("InvoiceNumber"),
                    "type": invoice.get("Type"),
                    "contact": {
                        "id": invoice.get("Contact", {}).get("ContactID"),
                        "name": invoice.get("Contact", {}).get("Name"),
                    },
                    "status": invoice.get("Status"),
                    "date": invoice.get("Date"),
                    "due_date": invoice.get("DueDate"),
                    "reference": invoice.get("Reference"),
                    "sub_total": invoice.get("SubTotal"),
                    "total_tax": invoice.get("TotalTax"),
                    "total": invoice.get("Total"),
                    "amount_due": invoice.get("AmountDue"),
                    "amount_paid": invoice.get("AmountPaid"),
                    "currency": invoice.get("CurrencyCode"),
                    "line_items": [
                        {
                            "description": li.get("Description"),
                            "quantity": li.get("Quantity"),
                            "unit_amount": li.get("UnitAmount"),
                            "line_amount": li.get("LineAmount"),
                            "tax_type": li.get("TaxType"),
                            "account_code": li.get("AccountCode"),
                        }
                        for li in invoice.get("LineItems", [])
                    ],
                    "payments": [
                        {
                            "payment_id": p.get("PaymentID"),
                            "date": p.get("Date"),
                            "amount": p.get("Amount"),
                        }
                        for p in invoice.get("Payments", [])
                    ],
                }
            }

        elif name == "xero_create_invoice":
            line_items = _format_line_items(arguments.get("line_items", []))
            invoice = await client.create_invoice(
                contact_id=arguments["contact_id"],
                line_items=line_items,
                invoice_type=arguments.get("invoice_type", "ACCREC"),
                date=arguments.get("date"),
                due_date=arguments.get("due_date"),
                invoice_number=arguments.get("invoice_number"),
                reference=arguments.get("reference"),
                currency_code=arguments.get("currency_code", "AUD"),
                status=arguments.get("status", "DRAFT"),
            )
            return {
                "success": True,
                "invoice": {
                    "id": invoice.get("InvoiceID"),
                    "number": invoice.get("InvoiceNumber"),
                    "status": invoice.get("Status"),
                    "total": invoice.get("Total"),
                },
                "message": f"Invoice {invoice.get('InvoiceNumber')} created successfully",
            }

        elif name == "xero_update_invoice":
            line_items = None
            if "line_items" in arguments:
                line_items = _format_line_items(arguments["line_items"])

            invoice = await client.update_invoice(
                invoice_id=arguments["invoice_id"],
                status=arguments.get("status"),
                line_items=line_items,
                due_date=arguments.get("due_date"),
                reference=arguments.get("reference"),
            )
            return {
                "success": True,
                "invoice": {
                    "id": invoice.get("InvoiceID"),
                    "number": invoice.get("InvoiceNumber"),
                    "status": invoice.get("Status"),
                    "total": invoice.get("Total"),
                },
                "message": f"Invoice {invoice.get('InvoiceNumber')} updated successfully",
            }

        elif name == "xero_send_invoice":
            result = await client.send_invoice(arguments["invoice_id"])
            return {
                "success": True,
                "message": "Invoice sent to contact via email",
            }

    except Exception as e:
        return {"error": str(e)}

    return {"error": f"Unknown invoice tool: {name}"}
