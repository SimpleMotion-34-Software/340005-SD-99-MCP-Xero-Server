<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/SimpleMotion-99-Templates/.github/main/profile/sm-assets/sm-white-banner.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/SimpleMotion-99-Templates/.github/main/profile/sm-assets/sm-black-banner.svg">
    <img alt="SimpleMotion" src="https://raw.githubusercontent.com/SimpleMotion-99-Templates/.github/main/profile/sm-assets/sm-black-banner.svg" width="800">
  </picture>
</p>

<p align="center">
  <em>Engineered for Architecture, Entertainment and Industry.</em>
</p>

# MCP Xero Server

A Model Context Protocol (MCP) server that integrates Claude Code with Xero for managing contacts, quotes, and invoices.

## Features

- **Authentication**: Secure OAuth 2.0 flow with encrypted token storage
- **Contacts**: List, search, create, and view contact details
- **Quotes**: Create, update, send quotes, and convert to invoices
- **Invoices**: Create, update, send, and track invoices

## Installation

### Prerequisites

- Python 3.10 or later
- A Xero developer account and app credentials

### Install from source

```bash
git clone --recurse-submodules https://github.com/SimpleMotion-34-Software/340005-SD-99-MCP-Xero-Server.git
cd 340005-SD-99-MCP-Xero-Server
pip install -e .
```

### Create a Xero App

1. Go to [Xero Developer Portal](https://developer.xero.com/app/manage)
2. Create a new app with:
   - App name: Your choice (e.g., "Claude Code Integration")
   - Company URL: Your company website
   - OAuth 2.0 redirect URI: `http://localhost:8742/callback`
3. Note your Client ID and Client Secret

## Configuration

Add the MCP server to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "xero": {
      "command": "python",
      "args": ["-m", "mcp_xero"],
      "env": {
        "XERO_CLIENT_ID": "your-client-id",
        "XERO_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Or if installed as a package:

```json
{
  "mcpServers": {
    "xero": {
      "command": "mcp-xero",
      "env": {
        "XERO_CLIENT_ID": "your-client-id",
        "XERO_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

## Usage

### Authentication

1. Check connection status:
   ```
   Use the xero_auth_status tool
   ```

2. Connect to Xero:
   ```
   Use the xero_auth_url tool, then open the provided URL in your browser
   ```

3. After authorizing in the browser, the connection completes automatically.

### Working with Contacts

```
# List all contacts
xero_list_contacts

# Search for a contact
xero_list_contacts with search="Company Name"

# Create a new contact
xero_create_contact with name="New Company", email="contact@example.com"
```

### Working with Quotes

```
# Create a quote
xero_create_quote with:
  - contact_id: "contact-uuid"
  - line_items: [{"description": "Consulting", "quantity": 10, "unit_amount": 150}]
  - title: "Project Quote"

# Send a quote
xero_send_quote with quote_id="quote-uuid"

# Convert accepted quote to invoice
xero_convert_quote_to_invoice with quote_id="quote-uuid"
```

### Working with Invoices

```
# Create an invoice
xero_create_invoice with:
  - contact_id: "contact-uuid"
  - line_items: [{"description": "Service", "quantity": 1, "unit_amount": 500}]
  - due_date: "2026-02-28"

# Authorize and send
xero_update_invoice with invoice_id="invoice-uuid", status="AUTHORISED"
xero_send_invoice with invoice_id="invoice-uuid"
```

## Available Tools

### Authentication
| Tool | Description |
|------|-------------|
| `xero_auth_status` | Check authentication status |
| `xero_auth_url` | Get OAuth authorization URL |
| `xero_auth_callback` | Complete OAuth with manual code entry |
| `xero_disconnect` | Disconnect from Xero |

### Contacts
| Tool | Description |
|------|-------------|
| `xero_list_contacts` | List contacts with optional search |
| `xero_get_contact` | Get contact details |
| `xero_create_contact` | Create a new contact |

### Quotes
| Tool | Description |
|------|-------------|
| `xero_list_quotes` | List quotes with filters |
| `xero_get_quote` | Get quote details |
| `xero_create_quote` | Create a new quote |
| `xero_update_quote` | Update a quote |
| `xero_send_quote` | Send quote via email |
| `xero_convert_quote_to_invoice` | Convert accepted quote to invoice |

### Invoices
| Tool | Description |
|------|-------------|
| `xero_list_invoices` | List invoices with filters |
| `xero_get_invoice` | Get invoice details |
| `xero_create_invoice` | Create a new invoice |
| `xero_update_invoice` | Update an invoice |
| `xero_send_invoice` | Send invoice via email |

## Security

- Client credentials are stored in environment variables only
- OAuth tokens are encrypted at rest using machine-specific keys
- Token storage: `~/.xero/tokens.enc` (600 permissions)
- Refresh tokens are single-use per Xero requirements

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run linting
ruff check src/

# Run tests
pytest
```

## License

MIT License - see [LICENSE.md](LICENSE.md)
