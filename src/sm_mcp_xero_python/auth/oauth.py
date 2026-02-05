"""OAuth client credentials flow handler for Xero authentication."""

import os
import subprocess
import sys
from datetime import datetime
from typing import Any

import aiohttp

from .token_store import DEFAULT_SHORT_CODES, Tenant, TokenSet, TokenStore

# Credential profiles for different Xero organizations
# Maps profile name to keychain service prefix
CREDENTIAL_PROFILES = {
    "SP": "SP",        # SimpleMotion.Projects
    "SM": "SM",        # SimpleMotion
}

# Current active profile (module-level state)
_active_profile: str = "SP"


def get_active_profile() -> str:
    """Get the current active credential profile."""
    return _active_profile


def set_active_profile(profile: str) -> bool:
    """Set the active credential profile.

    Args:
        profile: Profile name (e.g., 'SP', 'SM')

    Returns:
        True if successful, False if profile not found
    """
    global _active_profile
    profile_upper = profile.upper()
    if profile_upper not in CREDENTIAL_PROFILES:
        return False
    _active_profile = profile_upper
    return True


def list_profiles() -> list[dict[str, Any]]:
    """List all available credential profiles.

    Returns:
        List of profile info dictionaries
    """
    return [
        {
            "name": name,
            "active": name == _active_profile,
            "configured": _check_profile_configured(name),
        }
        for name in CREDENTIAL_PROFILES
    ]


def _check_profile_configured(profile: str) -> bool:
    """Check if a profile has credentials configured."""
    prefix = CREDENTIAL_PROFILES.get(profile.upper(), profile.upper())
    client_id = _get_secure_credential(f"{prefix}-Xero-Client-ID")
    client_secret = _get_secure_credential(f"{prefix}-Xero-Client-Secret")
    return bool(client_id and client_secret)


KEYCHAIN_ACCOUNT = "xero-mcp"


def _get_keychain_password_macos(service: str, account: str = KEYCHAIN_ACCOUNT) -> str | None:
    """Retrieve password from macOS Keychain.

    Args:
        service: Keychain service name (e.g., 'SM-Xero-ClientId')
        account: Keychain account name (default: 'xero-mcp')

    Returns:
        Password if found, None otherwise
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _get_credential_password_windows(target: str) -> str | None:
    """Retrieve password from Windows Credential Manager.

    Args:
        target: Credential target name

    Returns:
        Password if found, None otherwise
    """
    # PowerShell script to retrieve credential
    ps_script = f'''
    $cred = Get-StoredCredential -Target "{target}" -ErrorAction SilentlyContinue
    if ($cred) {{
        $cred.GetNetworkCredential().Password
    }}
    '''

    # Try using cmdkey first (built-in, doesn't require CredentialManager module)
    # Format: cmdkey /list shows credentials, but can't retrieve passwords directly
    # Use PowerShell with .NET instead
    ps_script_dotnet = f'''
    Add-Type -AssemblyName System.Security
    $target = "{target}"
    try {{
        [Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime] | Out-Null
        $vault = New-Object Windows.Security.Credentials.PasswordVault
        $cred = $vault.Retrieve("xero-mcp", $target)
        $cred.RetrievePassword()
        Write-Output $cred.Password
    }} catch {{
        # Fallback: try generic credential
        $sig = @"
[DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern bool CredRead(string target, int type, int flags, out IntPtr credential);
[DllImport("advapi32.dll")]
public static extern void CredFree(IntPtr credential);
"@
        try {{
            Add-Type -MemberDefinition $sig -Namespace Win32 -Name Cred
            $ptr = [IntPtr]::Zero
            if ([Win32.Cred]::CredRead($target, 1, 0, [ref]$ptr)) {{
                $cred = [Runtime.InteropServices.Marshal]::PtrToStructure($ptr, [Type][Win32.Cred+CREDENTIAL])
                $secret = [Runtime.InteropServices.Marshal]::PtrToStringUni($cred.CredentialBlob, $cred.CredentialBlobSize / 2)
                [Win32.Cred]::CredFree($ptr)
                Write-Output $secret
            }}
        }} catch {{}}
    }}
    '''

    try:
        # Simple approach: use cmdkey-style generic credentials via PowerShell
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f'''
                $ErrorActionPreference = "SilentlyContinue"
                $cred = cmdkey /list:"{target}" 2>$null
                if ($LASTEXITCODE -eq 0) {{
                    # Can't get password from cmdkey, try .NET CredentialManager
                    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class CredManager {{
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool CredRead(string target, int type, int flags, out IntPtr credential);

    [DllImport("advapi32.dll")]
    public static extern void CredFree(IntPtr credential);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {{
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public long LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }}

    public static string GetPassword(string target) {{
        IntPtr ptr;
        if (CredRead(target, 1, 0, out ptr)) {{
            CREDENTIAL cred = (CREDENTIAL)Marshal.PtrToStructure(ptr, typeof(CREDENTIAL));
            string password = Marshal.PtrToStringUni(cred.CredentialBlob, cred.CredentialBlobSize / 2);
            CredFree(ptr);
            return password;
        }}
        return null;
    }}
}}
"@
                    $password = [CredManager]::GetPassword("{target}")
                    if ($password) {{ Write-Output $password }}
                }}
                ''',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _get_secret_tool_password_linux(name: str) -> str | None:
    """Retrieve password from Linux secret storage using secret-tool (libsecret).

    Args:
        name: Secret name (e.g., 'xero-client-id')

    Returns:
        Password if found, None otherwise

    Requires:
        - libsecret-tools package (provides secret-tool command)
        - A running secret service (GNOME Keyring, KDE Wallet, etc.)
    """
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", "xero-mcp", "name", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def _get_secure_credential(name: str) -> str | None:
    """Retrieve credential from platform-specific secure storage.

    Args:
        name: Credential name (e.g., 'xero-client-id')

    Returns:
        Credential value if found, None otherwise

    Platform support:
        - macOS: Keychain (security command)
        - Windows: Credential Manager (PowerShell)
        - Linux: libsecret via secret-tool (GNOME Keyring, KDE Wallet)
    """
    if sys.platform == "darwin":
        return _get_keychain_password_macos(name)
    elif sys.platform == "win32":
        return _get_credential_password_windows(name)
    elif sys.platform.startswith("linux"):
        return _get_secret_tool_password_linux(name)
    return None

# Xero OAuth endpoints
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"


class XeroOAuth:
    """Handle Xero OAuth 2.0 client credentials authentication for Custom Connections."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_store: TokenStore | None = None,
        profile: str | None = None,
    ):
        """Initialize OAuth handler.

        Args:
            client_id: Xero app client ID (defaults to keychain or XERO_CLIENT_ID env var)
            client_secret: Xero app client secret (defaults to keychain or XERO_CLIENT_SECRET env var)
            token_store: Token storage handler
            profile: Credential profile to use (e.g., 'SP', 'SM'). Defaults to active profile.

        Credential lookup order:
            1. Explicit parameter
            2. Platform secure storage (profile-specific):
               - macOS: Keychain ({Profile}-Xero-ClientId, {Profile}-Xero-ClientSecret)
               - Windows: Credential Manager
            3. Environment variable (XERO_CLIENT_ID, XERO_CLIENT_SECRET)
        """
        # Use specified profile or active profile
        self.profile = (profile or _active_profile).upper()
        prefix = CREDENTIAL_PROFILES.get(self.profile, self.profile)

        self.client_id = (
            client_id
            or _get_secure_credential(f"{prefix}-Xero-Client-ID")
            or os.environ.get("XERO_CLIENT_ID", "")
        )
        self.client_secret = (
            client_secret
            or _get_secure_credential(f"{prefix}-Xero-Client-Secret")
            or os.environ.get("XERO_CLIENT_SECRET", "")
        )

        # Use profile-specific token store (keychain-based)
        self.token_store = token_store or TokenStore(profile=self.profile)

    @property
    def is_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.client_secret)

    async def authenticate_client_credentials(self) -> TokenSet:
        """Authenticate using client credentials grant (for Custom Connections).

        This is used for Xero Custom Connection apps which are pre-authorized
        to a specific organization and don't require user interaction.

        Returns:
            Token set with access token

        Raises:
            ValueError: If credentials not configured or auth fails
        """
        if not self.is_configured:
            raise ValueError("XERO_CLIENT_ID and XERO_CLIENT_SECRET must be set")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    raise ValueError(f"Client credentials auth failed: {error}")

                data = await response.json()

        # Get all tenants from connections
        tenant_id, tenants = await self._get_tenant_id(data["access_token"])

        tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),  # May not have refresh token
            expires_at=datetime.now().timestamp() + data["expires_in"],
            token_type=data["token_type"],
            scope=data.get("scope", "").split(),
            tenant_id=tenant_id,
            tenants=tenants,
        )

        self.token_store.save(tokens)
        return tokens

    async def get_valid_tokens(self) -> TokenSet | None:
        """Get valid tokens, re-authenticating if expired.

        Returns:
            Valid token set or None if not authenticated
        """
        tokens = self.token_store.load()
        if not tokens:
            return None

        if tokens.is_expired:
            try:
                # Re-authenticate using client credentials
                tokens = await self.authenticate_client_credentials()
            except ValueError:
                return None

        return tokens

    async def _get_all_tenants(self, access_token: str) -> list[Tenant]:
        """Get all connected tenants from Xero.

        Args:
            access_token: Valid access token

        Returns:
            List of all connected tenants (organizations)
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                XERO_CONNECTIONS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response:
                if response.status != 200:
                    return []

                connections = await response.json()
                tenants = []
                for conn in connections:
                    tenant_name = conn.get("tenantName", "Unknown")
                    tenants.append(Tenant(
                        tenant_id=conn["tenantId"],
                        tenant_name=tenant_name,
                        tenant_type=conn.get("tenantType", "ORGANISATION"),
                        short_code=DEFAULT_SHORT_CODES.get(tenant_name),
                    ))
                return tenants

    async def _get_tenant_id(self, access_token: str) -> tuple[str | None, list[Tenant]]:
        """Get tenant ID and all tenants from Xero connections.

        Args:
            access_token: Valid access token

        Returns:
            Tuple of (first tenant ID, list of all tenants)
        """
        tenants = await self._get_all_tenants(access_token)
        if tenants:
            return tenants[0].tenant_id, tenants
        return None, []

    def disconnect(self) -> None:
        """Disconnect from Xero by removing stored tokens."""
        self.token_store.delete()

    def get_status(self) -> dict[str, Any]:
        """Get current authentication status.

        Returns:
            Status dictionary with connection info
        """
        if not self.is_configured:
            return {
                "connected": False,
                "configured": False,
                "message": "Xero credentials not configured. Store {Profile}-Xero-ClientId and {Profile}-Xero-ClientSecret in keychain.",
            }

        tokens = self.token_store.load()
        if not tokens:
            return {
                "connected": False,
                "configured": True,
                "message": "Not connected to Xero. Use xero_connect to authenticate.",
            }

        # Build tenant info
        active_tenant = tokens.active_tenant
        tenant_count = len(tokens.tenants) if tokens.tenants else 1

        status = {
            "connected": True,
            "configured": True,
            "expired": tokens.is_expired,
            "tenant_id": tokens.tenant_id,
            "tenant_name": active_tenant.tenant_name if active_tenant else "Unknown",
            "tenant_count": tenant_count,
            "scopes": tokens.scope,
            "message": f"Connected to Xero ({active_tenant.tenant_name if active_tenant else 'Unknown'})"
                + (" (token expired, will refresh)" if tokens.is_expired else ""),
        }

        # Include all tenants if multiple
        if tokens.tenants and len(tokens.tenants) > 1:
            status["tenants"] = [
                {"id": t.tenant_id, "name": t.tenant_name, "type": t.tenant_type}
                for t in tokens.tenants
            ]

        return status

    def list_tenants(self) -> list[dict[str, Any]]:
        """List all available tenants.

        Returns:
            List of tenant info dictionaries
        """
        tokens = self.token_store.load()
        if not tokens or not tokens.tenants:
            return []

        return [
            {
                "id": t.tenant_id,
                "name": t.tenant_name,
                "type": t.tenant_type,
                "short_code": t.short_code,
                "active": t.tenant_id == tokens.tenant_id,
            }
            for t in tokens.tenants
        ]

    def set_active_tenant(self, tenant_id: str) -> bool:
        """Set the active tenant.

        Args:
            tenant_id: Tenant ID to set as active

        Returns:
            True if successful, False if tenant not found
        """
        return self.token_store.set_active_tenant(tenant_id)
