# CLAUDE.md

## Project Overview

MCP Server for Xero integration, enabling Claude Code to manage contacts, quotes, and invoices through Xero's API.

**Repository:** `SimpleMotion-34-Software/340005-SD-99-MCP-Xero-Server`

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Claude Code   │────▶│  Xero MCP Server │────▶│  Xero API   │
└─────────────────┘     └──────────────────┘     └─────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │ Token Store  │
                        │ (~/.xero/)   │
                        └──────────────┘
```

## Project Structure

```
src/sm_mcp_xero_python/
├── __init__.py           # Package entry point
├── server.py             # MCP server main
├── auth/
│   ├── __init__.py
│   ├── oauth.py          # OAuth flow handling
│   └── token_store.py    # Encrypted token storage
├── tools/
│   ├── __init__.py       # Tool exports
│   ├── auth.py           # Authentication tools
│   ├── contacts.py       # Contact tools
│   ├── quotes.py         # Quote tools
│   └── invoices.py       # Invoice tools
└── xero/
    ├── __init__.py
    └── client.py         # Xero API client wrapper
```

## Key Implementation Details

### OAuth Flow
- Authorization URL generation with PKCE
- Local callback server on port 8742
- Automatic token refresh
- Encrypted token storage using Fernet

### Rate Limiting
- Tracks requests per minute (60/min limit)
- Automatic backoff on 429 responses
- Exponential retry (up to 3 attempts)

### Tool Categories
1. **Auth tools** (`xero_auth_*`): Handle authentication flow
2. **Contact tools** (`xero_*_contact*`): CRUD for contacts
3. **Quote tools** (`xero_*_quote*`): Quote management
4. **Invoice tools** (`xero_*_invoice*`): Invoice management

## Development Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run the server directly
python -m sm_mcp_xero_python

# Lint code
ruff check src/

# Format code
ruff format src/
```

## Configuration

Required environment variables:
- `XERO_CLIENT_ID`: Xero app client ID
- `XERO_CLIENT_SECRET`: Xero app client secret

Optional:
- OAuth redirect URI defaults to `http://localhost:8742/callback`

## Testing

Test authentication:
1. Run `xero_auth_status` - should show "not connected"
2. Run `xero_auth_url` - open returned URL in browser
3. Authorize in Xero
4. Run `xero_auth_status` - should show "connected"

Test operations:
1. `xero_list_contacts` - verify contacts returned
2. `xero_create_contact` with test data
3. `xero_create_quote` for a contact
4. `xero_create_invoice` for a contact
