"""Contact tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..xero import XeroClient

CONTACT_TOOLS = [
    Tool(
        name="xero_list_contacts",
        description="List contacts from Xero with optional search filtering. Returns contact names, IDs, and basic info.",
        inputSchema={
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Search term to filter contacts by name",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (100 results per page). Default: 1",
                    "default": 1,
                    "minimum": 1,
                },
                "include_archived": {
                    "type": "boolean",
                    "description": "Include archived contacts. Default: false",
                    "default": False,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_get_contact",
        description="Get detailed information about a specific contact by their ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "The Xero contact ID (UUID format)",
                },
            },
            "required": ["contact_id"],
        },
    ),
    Tool(
        name="xero_find_contact",
        description="Find a contact by name. Returns the best matching contact, preferring exact matches. Useful for getting a contact ID when you only know the name.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Contact name to search for (partial match supported)",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="xero_create_contact",
        description="Create a new contact in Xero. At minimum, a name is required.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Contact or company name (required)",
                },
                "email": {
                    "type": "string",
                    "description": "Email address",
                },
                "first_name": {
                    "type": "string",
                    "description": "First name",
                },
                "last_name": {
                    "type": "string",
                    "description": "Last name",
                },
                "phone": {
                    "type": "string",
                    "description": "Phone number",
                },
                "account_number": {
                    "type": "string",
                    "description": "Account number for reference",
                },
            },
            "required": ["name"],
        },
    ),
]


async def handle_contact_tool(name: str, arguments: dict[str, Any], client: XeroClient) -> dict[str, Any]:
    """Handle contact tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        client: Xero API client

    Returns:
        Tool result
    """
    try:
        if name == "xero_list_contacts":
            contacts = await client.list_contacts(
                search=arguments.get("search"),
                page=arguments.get("page", 1),
                include_archived=arguments.get("include_archived", False),
            )
            return {
                "contacts": [
                    {
                        "id": c.get("ContactID"),
                        "name": c.get("Name"),
                        "email": c.get("EmailAddress"),
                        "status": c.get("ContactStatus"),
                        "first_name": c.get("FirstName"),
                        "last_name": c.get("LastName"),
                    }
                    for c in contacts
                ],
                "count": len(contacts),
            }

        elif name == "xero_find_contact":
            contact = await client.find_contact_by_name(arguments["name"])
            if not contact:
                return {
                    "found": False,
                    "message": f"No contact found matching '{arguments['name']}'",
                }
            return {
                "found": True,
                "contact": {
                    "id": contact.get("ContactID"),
                    "name": contact.get("Name"),
                    "email": contact.get("EmailAddress"),
                    "status": contact.get("ContactStatus"),
                },
            }

        elif name == "xero_get_contact":
            contact = await client.get_contact(arguments["contact_id"])
            return {
                "contact": {
                    "id": contact.get("ContactID"),
                    "name": contact.get("Name"),
                    "email": contact.get("EmailAddress"),
                    "status": contact.get("ContactStatus"),
                    "first_name": contact.get("FirstName"),
                    "last_name": contact.get("LastName"),
                    "account_number": contact.get("AccountNumber"),
                    "phones": contact.get("Phones", []),
                    "addresses": contact.get("Addresses", []),
                    "is_customer": contact.get("IsCustomer"),
                    "is_supplier": contact.get("IsSupplier"),
                }
            }

        elif name == "xero_create_contact":
            contact = await client.create_contact(
                name=arguments["name"],
                email=arguments.get("email"),
                first_name=arguments.get("first_name"),
                last_name=arguments.get("last_name"),
                phone=arguments.get("phone"),
                account_number=arguments.get("account_number"),
            )
            return {
                "success": True,
                "contact": {
                    "id": contact.get("ContactID"),
                    "name": contact.get("Name"),
                    "email": contact.get("EmailAddress"),
                },
                "message": f"Contact '{contact.get('Name')}' created successfully",
            }

    except Exception as e:
        return {"error": str(e)}

    return {"error": f"Unknown contact tool: {name}"}
