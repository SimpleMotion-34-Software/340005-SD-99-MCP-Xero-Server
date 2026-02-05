"""Secure token storage for Xero OAuth tokens using macOS Keychain."""

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Self


# Default short codes for known tenants
DEFAULT_SHORT_CODES = {
    "SimpleMotion.Projects": "SP",
    "SimpleMotion": "SM",
}


@dataclass
class Tenant:
    """Xero tenant (organization) information."""

    tenant_id: str
    tenant_name: str
    tenant_type: str  # "ORGANISATION" or "PRACTICE"
    short_code: str | None = None  # Optional short code (e.g., "SP")

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        """Create from dictionary."""
        tenant_name = data.get("tenant_name", "Unknown")
        return cls(
            tenant_id=data["tenant_id"],
            tenant_name=tenant_name,
            tenant_type=data.get("tenant_type", "ORGANISATION"),
            short_code=data.get("short_code") or DEFAULT_SHORT_CODES.get(tenant_name),
        )


@dataclass
class TokenSet:
    """OAuth token set."""

    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str
    scope: list[str]
    tenant_id: str | None = None  # Active tenant ID
    tenants: list[Tenant] | None = None  # All available tenants

    @property
    def is_expired(self) -> bool:
        """Check if the access token is expired."""
        return datetime.now().timestamp() >= self.expires_at - 60  # 60s buffer

    @property
    def active_tenant(self) -> Tenant | None:
        """Get the active tenant info."""
        if not self.tenants or not self.tenant_id:
            return None
        for tenant in self.tenants:
            if tenant.tenant_id == self.tenant_id:
                return tenant
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "scope": self.scope,
            "tenant_id": self.tenant_id,
        }
        if self.tenants:
            data["tenants"] = [t.to_dict() for t in self.tenants]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        """Create from dictionary."""
        tenants = None
        if "tenants" in data:
            tenants = [Tenant.from_dict(t) for t in data["tenants"]]
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            token_type=data["token_type"],
            scope=data.get("scope", []),
            tenant_id=data.get("tenant_id"),
            tenants=tenants,
        )


# Keychain account name for all Xero tokens
KEYCHAIN_ACCOUNT = "xero-mcp"


class TokenStore:
    """Secure storage for OAuth tokens using macOS Keychain."""

    def __init__(self, profile: str = "SP"):
        """Initialize token store.

        Args:
            profile: Credential profile (e.g., 'SP', 'SM')
        """
        self.profile = profile.upper()
        # Keychain service name: {Profile}-Xero (e.g., SP-Xero, SM-Xero)
        self.keychain_service = f"{self.profile}-Xero"
        # Keychain account name: consistent 'xero-mcp' across all profiles
        self.keychain_account = KEYCHAIN_ACCOUNT

    def _keychain_save(self, data: str) -> bool:
        """Save data to macOS Keychain.

        Args:
            data: JSON string to save

        Returns:
            True if successful
        """
        if sys.platform != "darwin":
            raise RuntimeError("Keychain storage only supported on macOS")

        # Delete existing entry first (ignore errors if doesn't exist)
        subprocess.run(
            [
                "security", "delete-generic-password",
                "-s", self.keychain_service,
                "-a", self.keychain_account,
            ],
            capture_output=True,
        )

        # Add new entry
        result = subprocess.run(
            [
                "security", "add-generic-password",
                "-s", self.keychain_service,
                "-a", self.keychain_account,
                "-w", data,
                "-U",  # Update if exists
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def _keychain_load(self) -> str | None:
        """Load data from macOS Keychain.

        Returns:
            JSON string if found, None otherwise
        """
        if sys.platform != "darwin":
            return None

        try:
            result = subprocess.run(
                [
                    "security", "find-generic-password",
                    "-s", self.keychain_service,
                    "-a", self.keychain_account,
                    "-w",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _keychain_delete(self) -> bool:
        """Delete entry from macOS Keychain.

        Returns:
            True if successful
        """
        if sys.platform != "darwin":
            return False

        result = subprocess.run(
            [
                "security", "delete-generic-password",
                "-s", self.keychain_service,
                "-a", self.keychain_account,
            ],
            capture_output=True,
        )
        return result.returncode == 0

    def save(self, tokens: TokenSet) -> None:
        """Save tokens to Keychain.

        Args:
            tokens: Token set to save
        """
        data = json.dumps(tokens.to_dict())
        if not self._keychain_save(data):
            raise RuntimeError("Failed to save tokens to Keychain")

    def load(self) -> TokenSet | None:
        """Load tokens from Keychain.

        Returns:
            Token set if exists and valid, None otherwise
        """
        data = self._keychain_load()
        if not data:
            return None

        try:
            return TokenSet.from_dict(json.loads(data))
        except (json.JSONDecodeError, KeyError):
            return None

    def delete(self) -> None:
        """Delete stored tokens."""
        self._keychain_delete()

    def exists(self) -> bool:
        """Check if tokens exist in storage."""
        return self._keychain_load() is not None

    def set_active_tenant(self, tenant_id_or_code: str) -> bool:
        """Set the active tenant by ID or short code.

        Args:
            tenant_id_or_code: Tenant ID (UUID) or short code (e.g., "SP")

        Returns:
            True if successful, False if tenant not found
        """
        tokens = self.load()
        if not tokens:
            return False

        # Find tenant by ID or short code
        resolved_id = None
        if tokens.tenants:
            for t in tokens.tenants:
                if t.tenant_id == tenant_id_or_code:
                    resolved_id = t.tenant_id
                    break
                if t.short_code and t.short_code.upper() == tenant_id_or_code.upper():
                    resolved_id = t.tenant_id
                    break

        if not resolved_id:
            return False

        tokens.tenant_id = resolved_id
        self.save(tokens)
        return True
