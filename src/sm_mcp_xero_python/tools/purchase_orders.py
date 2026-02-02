"""Purchase order tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..xero import XeroClient

PURCHASE_ORDER_TOOLS = [
    Tool(
        name="xero_list_purchase_orders",
        description="List purchase orders from Xero with optional filtering by status, contact, or date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by purchase order status",
                    "enum": ["DRAFT", "SUBMITTED", "AUTHORISED", "BILLED", "DELETED"],
                },
                "contact_id": {
                    "type": "string",
                    "description": "Filter by contact (supplier) ID",
                },
                "date_from": {
                    "type": "string",
                    "description": "Filter POs from this date (YYYY-MM-DD format)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter POs to this date (YYYY-MM-DD format)",
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
        name="xero_get_purchase_order",
        description="Get detailed information about a specific purchase order by its ID or PO number.",
        inputSchema={
            "type": "object",
            "properties": {
                "purchase_order_id": {
                    "type": "string",
                    "description": "The Xero purchase order ID (UUID format) or PO number",
                },
            },
            "required": ["purchase_order_id"],
        },
    ),
    Tool(
        name="xero_create_purchase_order",
        description="Create a new purchase order in Xero for a supplier contact with line items. You can specify either contact_id or contact_name (contact_name will search for the contact).",
        inputSchema={
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Contact ID (supplier) to create the PO for (use this OR contact_name)",
                },
                "contact_name": {
                    "type": "string",
                    "description": "Contact name to search for (use this OR contact_id)",
                },
                "line_items": {
                    "type": "array",
                    "description": "List of line items for the purchase order",
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
                                "description": "Price per unit (ex GST)",
                            },
                            "account_code": {
                                "type": "string",
                                "description": "Account code (e.g., '300' for Purchases)",
                            },
                            "tax_type": {
                                "type": "string",
                                "description": "Tax type (e.g., 'INPUT' for GST on expenses)",
                            },
                        },
                        "required": ["description", "unit_amount"],
                    },
                },
                "date": {
                    "type": "string",
                    "description": "PO date (YYYY-MM-DD). Defaults to today.",
                },
                "delivery_date": {
                    "type": "string",
                    "description": "Expected delivery date (YYYY-MM-DD)",
                },
                "purchase_order_number": {
                    "type": "string",
                    "description": "PO number (auto-generated if not provided)",
                },
                "reference": {
                    "type": "string",
                    "description": "Reference text (e.g., supplier quote number)",
                },
                "delivery_address": {
                    "type": "string",
                    "description": "Delivery address",
                },
                "attention_to": {
                    "type": "string",
                    "description": "Attention to name",
                },
                "telephone": {
                    "type": "string",
                    "description": "Contact telephone number",
                },
                "delivery_instructions": {
                    "type": "string",
                    "description": "Special delivery instructions",
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
            "required": ["line_items"],
        },
    ),
    Tool(
        name="xero_update_purchase_order",
        description="Update an existing purchase order. Only provide fields you want to change. Note: POs can only be updated when in DRAFT or SUBMITTED status.",
        inputSchema={
            "type": "object",
            "properties": {
                "purchase_order_id": {
                    "type": "string",
                    "description": "Purchase order ID to update",
                },
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["DRAFT", "SUBMITTED", "AUTHORISED", "DELETED"],
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
                "delivery_date": {
                    "type": "string",
                    "description": "New delivery date (YYYY-MM-DD)",
                },
                "reference": {
                    "type": "string",
                    "description": "New reference",
                },
                "delivery_address": {
                    "type": "string",
                    "description": "New delivery address",
                },
                "attention_to": {
                    "type": "string",
                    "description": "New attention to name",
                },
            },
            "required": ["purchase_order_id"],
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


async def handle_purchase_order_tool(name: str, arguments: dict[str, Any], client: XeroClient) -> dict[str, Any]:
    """Handle purchase order tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        client: Xero API client

    Returns:
        Tool result
    """
    try:
        if name == "xero_list_purchase_orders":
            purchase_orders = await client.list_purchase_orders(
                status=arguments.get("status"),
                contact_id=arguments.get("contact_id"),
                page=arguments.get("page", 1),
                date_from=arguments.get("date_from"),
                date_to=arguments.get("date_to"),
            )
            return {
                "purchase_orders": [
                    {
                        "id": po.get("PurchaseOrderID"),
                        "number": po.get("PurchaseOrderNumber"),
                        "contact_name": po.get("Contact", {}).get("Name"),
                        "status": po.get("Status"),
                        "date": po.get("Date"),
                        "delivery_date": po.get("DeliveryDate"),
                        "total": po.get("Total"),
                        "currency": po.get("CurrencyCode"),
                    }
                    for po in purchase_orders
                ],
                "count": len(purchase_orders),
            }

        elif name == "xero_get_purchase_order":
            po = await client.get_purchase_order(arguments["purchase_order_id"])
            return {
                "purchase_order": {
                    "id": po.get("PurchaseOrderID"),
                    "number": po.get("PurchaseOrderNumber"),
                    "contact": {
                        "id": po.get("Contact", {}).get("ContactID"),
                        "name": po.get("Contact", {}).get("Name"),
                    },
                    "status": po.get("Status"),
                    "date": po.get("Date"),
                    "delivery_date": po.get("DeliveryDate"),
                    "delivery_address": po.get("DeliveryAddress"),
                    "attention_to": po.get("AttentionTo"),
                    "telephone": po.get("Telephone"),
                    "delivery_instructions": po.get("DeliveryInstructions"),
                    "reference": po.get("Reference"),
                    "sub_total": po.get("SubTotal"),
                    "total_tax": po.get("TotalTax"),
                    "total": po.get("Total"),
                    "currency": po.get("CurrencyCode"),
                    "line_items": [
                        {
                            "description": li.get("Description"),
                            "quantity": li.get("Quantity"),
                            "unit_amount": li.get("UnitAmount"),
                            "line_amount": li.get("LineAmount"),
                            "tax_type": li.get("TaxType"),
                            "account_code": li.get("AccountCode"),
                        }
                        for li in po.get("LineItems", [])
                    ],
                }
            }

        elif name == "xero_create_purchase_order":
            # Resolve contact_id from contact_name if provided
            contact_id = arguments.get("contact_id")
            if not contact_id and arguments.get("contact_name"):
                contact = await client.find_contact_by_name(arguments["contact_name"])
                if not contact:
                    return {"error": f"No contact found matching '{arguments['contact_name']}'"}
                contact_id = contact["ContactID"]
            if not contact_id:
                return {"error": "Either contact_id or contact_name is required"}

            line_items = _format_line_items(arguments.get("line_items", []))
            po = await client.create_purchase_order(
                contact_id=contact_id,
                line_items=line_items,
                date=arguments.get("date"),
                delivery_date=arguments.get("delivery_date"),
                purchase_order_number=arguments.get("purchase_order_number"),
                reference=arguments.get("reference"),
                delivery_address=arguments.get("delivery_address"),
                attention_to=arguments.get("attention_to"),
                telephone=arguments.get("telephone"),
                delivery_instructions=arguments.get("delivery_instructions"),
                currency_code=arguments.get("currency_code", "AUD"),
                status=arguments.get("status", "DRAFT"),
            )
            return {
                "success": True,
                "purchase_order": {
                    "id": po.get("PurchaseOrderID"),
                    "number": po.get("PurchaseOrderNumber"),
                    "status": po.get("Status"),
                    "total": po.get("Total"),
                },
                "message": f"Purchase order {po.get('PurchaseOrderNumber')} created successfully",
            }

        elif name == "xero_update_purchase_order":
            line_items = None
            if "line_items" in arguments:
                line_items = _format_line_items(arguments["line_items"])

            po = await client.update_purchase_order(
                purchase_order_id=arguments["purchase_order_id"],
                status=arguments.get("status"),
                line_items=line_items,
                delivery_date=arguments.get("delivery_date"),
                reference=arguments.get("reference"),
                delivery_address=arguments.get("delivery_address"),
                attention_to=arguments.get("attention_to"),
            )
            return {
                "success": True,
                "purchase_order": {
                    "id": po.get("PurchaseOrderID"),
                    "number": po.get("PurchaseOrderNumber"),
                    "status": po.get("Status"),
                    "total": po.get("Total"),
                },
                "message": f"Purchase order {po.get('PurchaseOrderNumber')} updated successfully",
            }

    except Exception as e:
        return {"error": str(e)}

    return {"error": f"Unknown purchase order tool: {name}"}
