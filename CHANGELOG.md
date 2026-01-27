# Changelog

All notable changes to this project will be documented in this file.

## [0.0.1.14] - 2026-01-27

### Added
- Multi-profile support: both SP and SM can be connected simultaneously
- `xero_connect_all` tool to authenticate all configured profiles at once
- Optional `profile` parameter on most tools to specify which profile to use
- Quarterly wages report supports `profile='ALL'` to run across all connected profiles
- Combined report shows breakdown by profile with grand totals

### Changed
- Server now maintains separate OAuth/Client instances per profile
- `xero_list_profiles` shows connection status for each profile
- `xero_set_profile` now only changes the default profile (both remain connected)

## [0.0.1.12] - 2026-01-27

### Changed
- SP profile keychain suffix changed from empty to `-sp`
- Credentials now use `xero-client-id-sp` and `xero-client-secret-sp`
- Token storage changed from `tokens.enc` to `tokens-sp.enc`

## [0.0.1.10] - 2026-01-27

### Added
- OTE (Ordinary Time Earnings) calculation in quarterly wages report
- Allowance detection and exclusion from super calculations
- Per diem allowances identified and separated from OTE

### Changed
- Super percentage now calculated on OTE, not gross wages
- Date format changed to DD-MM-YYYY (Australian format)
- Numeric columns right-aligned in markdown table output

## [0.0.1.8] - 2026-01-27

### Added
- Xero Payroll AU API support with new tools:
  - `xero_list_payruns` - List pay runs with status filtering
  - `xero_get_payrun` - Get pay run details with payslips
  - `xero_list_payroll_employees` - List payroll employees
  - `xero_quarterly_wages_report` - Generate quarterly wages report with gross wages, superannuation, and super percentage
- Quarterly report filters by payment date (for BAS/cash basis reporting)
- Rate limiting improvements: 1.2s minimum interval between requests to avoid bursts

### Changed
- Simplified OAuth to client credentials only (Custom Connection apps)
- Reduced rate limit threshold from 60 to 50 requests per minute (more conservative)

## [0.0.1.6] - 2026-01-25

### Added
- Multi-profile credential support for multiple Xero Custom Connection apps
- CREDENTIAL_PROFILES mapping (SP = SimpleMotion.Projects, SM = SimpleMotion)
- `xero_list_profiles` and `xero_set_profile` tools to switch between profiles
- Each profile uses separate token storage (tokens.enc, tokens-sm.enc)
- SimpleMotion short code (SM) added to DEFAULT_SHORT_CODES

## [0.0.1.5] - 2026-01-25

### Fixed
- Add missing `__main__.py` to enable `python -m mcp_xero` execution

## [0.0.1.4] - 2026-01-25

### Added
- Initial MCP server implementation
- OAuth 2.0 authentication with encrypted token storage
- Contact tools: list, get, create
- Quote tools: list, get, create, update, send, convert to invoice
- Invoice tools: list, get, create, update, send
- Rate limiting with automatic backoff
- Local callback server for OAuth flow

## [0.0.1.3] - 2026-01-25

### Added
- Add .claude, .github, .github-private submodules
- Align with 999998-ST-Default-SimpleMotion-Orgs structure

## [0.0.1.1] - 2026-01-07

### Added
- Initial project setup
