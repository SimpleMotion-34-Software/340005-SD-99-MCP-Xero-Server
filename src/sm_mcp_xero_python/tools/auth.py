"""Authentication tools for Xero MCP server."""

import subprocess
import sys
from typing import Any, TYPE_CHECKING

from mcp.types import Tool

from ..auth import XeroOAuth
from ..auth.oauth import CREDENTIAL_PROFILES, get_active_profile, set_active_profile, list_profiles

if TYPE_CHECKING:
    from ..server import XeroMCPServer


def _keychain_set_credential(service: str, password: str) -> bool:
    """Set a credential in macOS Keychain (service-only pattern for credentials)."""
    if sys.platform != "darwin":
        return False

    # Delete existing entry first
    subprocess.run(
        ["security", "delete-generic-password", "-s", service],
        capture_output=True,
    )

    # Add new entry
    result = subprocess.run(
        ["security", "add-generic-password", "-s", service, "-w", password],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _keychain_delete_credential(service: str) -> bool:
    """Delete a credential from macOS Keychain (service-only pattern)."""
    if sys.platform != "darwin":
        return False

    result = subprocess.run(
        ["security", "delete-generic-password", "-s", service],
        capture_output=True,
    )
    return result.returncode == 0


def _keychain_exists_credential(service: str) -> bool:
    """Check if a credential exists in macOS Keychain (service-only pattern)."""
    if sys.platform != "darwin":
        return False

    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
    )
    return result.returncode == 0


def _keychain_exists_token(service: str, account: str) -> bool:
    """Check if tokens exist in macOS Keychain (service+account pattern)."""
    if sys.platform != "darwin":
        return False

    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
    )
    return result.returncode == 0


def _keychain_delete_token(service: str, account: str) -> bool:
    """Delete tokens from macOS Keychain (service+account pattern)."""
    if sys.platform != "darwin":
        return False

    result = subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True,
    )
    return result.returncode == 0

AUTH_TOOLS = [
    Tool(
        name="xero_auth_status",
        description="Check the current Xero authentication status. Returns whether you're connected, if credentials are configured, and connection details. Optionally specify a profile to check.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Profile to check (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_connect",
        description="Connect to Xero using client credentials (for Custom Connection apps). Optionally specify a profile to connect.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Profile to connect (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_connect_all",
        description="Connect to all configured Xero profiles at once. Returns status for each profile.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_disconnect",
        description="Disconnect from Xero by removing stored authentication tokens. Optionally specify a profile.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Profile to disconnect (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_list_tenants",
        description="List all Xero organizations (tenants) you have access to. Shows which one is currently active.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Profile to list tenants for (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_set_tenant",
        description="Switch to a different Xero organization (tenant). Use xero_list_tenants first to see available options. Accepts tenant_id (UUID) or short_code (e.g., 'SP').",
        inputSchema={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The tenant ID (UUID) or short code (e.g., 'SP') to switch to",
                },
                "profile": {
                    "type": "string",
                    "description": "Profile to set tenant for (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": ["tenant_id"],
        },
    ),
    Tool(
        name="xero_list_profiles",
        description="List available Xero credential profiles with connection status. Each profile connects to a different Xero Custom Connection app.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="xero_set_profile",
        description="Switch the default active profile (e.g., 'SP' for SimpleMotion.Projects, 'SM' for SimpleMotion). Note: Both profiles can be connected simultaneously - this just changes the default.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "The profile name to set as default (e.g., 'SP', 'SM')",
                },
            },
            "required": ["profile"],
        },
    ),
    Tool(
        name="xero_set_credential",
        description="Set a Xero credential in macOS Keychain. Use this to configure client_id and client_secret for a profile.",
        inputSchema={
            "type": "object",
            "properties": {
                "credential": {
                    "type": "string",
                    "description": "Credential type: 'client_id' or 'client_secret'",
                    "enum": ["client_id", "client_secret"],
                },
                "value": {
                    "type": "string",
                    "description": "The credential value to store",
                },
                "profile": {
                    "type": "string",
                    "description": "Profile to set credential for (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": ["credential", "value"],
        },
    ),
    Tool(
        name="xero_delete_credential",
        description="Delete a Xero credential from macOS Keychain.",
        inputSchema={
            "type": "object",
            "properties": {
                "credential": {
                    "type": "string",
                    "description": "Credential type: 'client_id' or 'client_secret'",
                    "enum": ["client_id", "client_secret"],
                },
                "profile": {
                    "type": "string",
                    "description": "Profile to delete credential for (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": ["credential"],
        },
    ),
    Tool(
        name="xero_list_credentials",
        description="List which Xero credentials are configured in Keychain (does not show values).",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Profile to check (e.g., 'SP', 'SM'). If not specified, checks all profiles.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_delete_tokens",
        description="Delete stored OAuth tokens from Keychain for a profile. Use this to force re-authentication.",
        inputSchema={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Profile to delete tokens for (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
]


async def handle_auth_tool(
    name: str,
    arguments: dict[str, Any],
    oauth: XeroOAuth,
    server: "XeroMCPServer | None" = None,
) -> dict[str, Any]:
    """Handle authentication tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        oauth: OAuth handler for the current/specified profile
        server: Server instance for multi-profile operations

    Returns:
        Tool result
    """
    profile = arguments.get("profile") or oauth.profile

    if name == "xero_auth_status":
        status = oauth.get_status()
        status["profile"] = profile
        return status

    elif name == "xero_connect":
        if not oauth.is_configured:
            return {
                "error": "Xero credentials not configured",
                "profile": profile,
                "message": f"Store xero-client-id-{profile.lower()} and xero-client-secret-{profile.lower()} in keychain",
            }

        try:
            tokens = await oauth.authenticate_client_credentials()
            return {
                "success": True,
                "profile": profile,
                "message": f"Successfully connected to Xero ({profile})",
                "tenant_id": tokens.tenant_id,
                "scopes": tokens.scope,
            }
        except ValueError as e:
            return {"error": str(e), "profile": profile}

    elif name == "xero_connect_all":
        if not server:
            return {"error": "Server instance not available"}

        results = {}
        for prof in CREDENTIAL_PROFILES:
            prof_oauth = server.get_oauth(prof)
            if not prof_oauth.is_configured:
                results[prof] = {"connected": False, "error": "Credentials not configured"}
                continue

            try:
                tokens = await prof_oauth.authenticate_client_credentials()
                results[prof] = {
                    "connected": True,
                    "tenant_id": tokens.tenant_id,
                    "tenant_name": tokens.active_tenant.tenant_name if tokens.active_tenant else "Unknown",
                }
            except ValueError as e:
                results[prof] = {"connected": False, "error": str(e)}

        connected = [p for p, r in results.items() if r.get("connected")]
        return {
            "success": len(connected) > 0,
            "profiles": results,
            "connected_count": len(connected),
            "message": f"Connected {len(connected)}/{len(CREDENTIAL_PROFILES)} profiles: {', '.join(connected) or 'none'}",
        }

    elif name == "xero_disconnect":
        oauth.disconnect()
        return {
            "success": True,
            "profile": profile,
            "message": f"Disconnected from Xero ({profile}). Stored tokens have been removed.",
        }

    elif name == "xero_list_tenants":
        tenants = oauth.list_tenants()
        if not tenants:
            return {
                "tenants": [],
                "profile": profile,
                "message": f"No tenants available for {profile}. Connect to Xero first.",
            }
        return {
            "tenants": tenants,
            "count": len(tenants),
            "profile": profile,
            "message": f"Found {len(tenants)} organization(s) for {profile}",
        }

    elif name == "xero_set_tenant":
        tenant_id_or_code = arguments.get("tenant_id")
        if not tenant_id_or_code:
            return {"error": "tenant_id is required"}

        success = oauth.set_active_tenant(tenant_id_or_code)
        if success:
            # Get the tenant info for confirmation
            tenants = oauth.list_tenants()
            active = next((t for t in tenants if t["active"]), None)
            short_code = f" ({active['short_code']})" if active and active.get("short_code") else ""
            return {
                "success": True,
                "profile": profile,
                "tenant_id": active["id"] if active else tenant_id_or_code,
                "tenant_name": active["name"] if active else "Unknown",
                "short_code": active.get("short_code") if active else None,
                "message": f"Switched to {active['name'] if active else tenant_id_or_code}{short_code}",
            }
        else:
            return {
                "error": "Tenant not found",
                "profile": profile,
                "message": "Use xero_list_tenants to see available organizations",
            }

    elif name == "xero_list_profiles":
        profiles_info = []
        for prof in CREDENTIAL_PROFILES:
            prof_oauth = server.get_oauth(prof) if server else None
            if prof_oauth:
                status = prof_oauth.get_status()
                profiles_info.append({
                    "name": prof,
                    "active": prof == get_active_profile(),
                    "configured": prof_oauth.is_configured,
                    "connected": status.get("connected", False),
                    "tenant_name": status.get("tenant_name") if status.get("connected") else None,
                })
            else:
                profiles_info.append({
                    "name": prof,
                    "active": prof == get_active_profile(),
                    "configured": False,
                    "connected": False,
                })

        return {
            "profiles": profiles_info,
            "active": get_active_profile(),
            "message": f"Active profile: {get_active_profile()}",
        }

    elif name == "xero_set_profile":
        profile_arg = arguments.get("profile")
        if not profile_arg:
            return {"error": "profile is required"}

        success = set_active_profile(profile_arg)
        if success:
            return {
                "success": True,
                "profile": get_active_profile(),
                "message": f"Default profile set to: {get_active_profile()}. Note: Both profiles can be connected simultaneously.",
            }
        else:
            available = list(CREDENTIAL_PROFILES.keys())
            return {
                "error": f"Profile '{profile_arg}' not found",
                "available": available,
                "message": f"Available profiles: {', '.join(available)}",
            }

    elif name == "xero_set_credential":
        credential = arguments.get("credential")
        value = arguments.get("value")
        profile_arg = arguments.get("profile") or get_active_profile()

        if not credential or not value:
            return {"error": "credential and value are required"}

        if credential not in ["client_id", "client_secret"]:
            return {"error": "credential must be 'client_id' or 'client_secret'"}

        suffix = CREDENTIAL_PROFILES.get(profile_arg.upper(), "")
        service_name = f"xero-{credential.replace('_', '-')}{suffix}"

        success = _keychain_set_credential(service_name, value)
        if success:
            return {
                "success": True,
                "profile": profile_arg.upper(),
                "credential": credential,
                "message": f"Credential '{credential}' set for profile {profile_arg.upper()}",
            }
        else:
            return {"error": "Failed to set credential in Keychain"}

    elif name == "xero_delete_credential":
        credential = arguments.get("credential")
        profile_arg = arguments.get("profile") or get_active_profile()

        if not credential:
            return {"error": "credential is required"}

        suffix = CREDENTIAL_PROFILES.get(profile_arg.upper(), "")
        service_name = f"xero-{credential.replace('_', '-')}{suffix}"

        success = _keychain_delete_credential(service_name)
        if success:
            return {
                "success": True,
                "profile": profile_arg.upper(),
                "credential": credential,
                "message": f"Credential '{credential}' deleted for profile {profile_arg.upper()}",
            }
        else:
            return {"error": "Failed to delete credential (may not exist)"}

    elif name == "xero_list_credentials":
        profile_arg = arguments.get("profile")
        profiles_to_check = [profile_arg.upper()] if profile_arg else list(CREDENTIAL_PROFILES.keys())

        results = {}
        for prof in profiles_to_check:
            suffix = CREDENTIAL_PROFILES.get(prof, "")
            results[prof] = {
                "client_id": _keychain_exists_credential(f"xero-client-id{suffix}"),
                "client_secret": _keychain_exists_credential(f"xero-client-secret{suffix}"),
                "tokens": _keychain_exists_token("xero-mcp-tokens", prof),
            }

        return {
            "profiles": results,
            "message": "Credential status (does not show values)",
        }

    elif name == "xero_delete_tokens":
        profile_arg = arguments.get("profile") or get_active_profile()
        success = _keychain_delete_token("xero-mcp-tokens", profile_arg.upper())

        if success:
            return {
                "success": True,
                "profile": profile_arg.upper(),
                "message": f"Tokens deleted for profile {profile_arg.upper()}. Re-authentication required.",
            }
        else:
            return {"error": "Failed to delete tokens (may not exist)"}

    return {"error": f"Unknown auth tool: {name}"}
