"""Secure token storage for Xero OAuth tokens."""

import json
import os
from base64 import b64decode, b64encode
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Self

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# Default short codes for known tenants
DEFAULT_SHORT_CODES = {
    "SimpleMotion.Projects": "SP",
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


class TokenStore:
    """Secure storage for OAuth tokens using encryption."""

    def __init__(self, storage_path: Path | None = None):
        """Initialize token store.

        Args:
            storage_path: Path to token storage file. Defaults to ~/.xero/tokens.enc
        """
        if storage_path is None:
            storage_path = Path.home() / ".xero" / "tokens.enc"
        self.storage_path = storage_path
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        """Get or create Fernet cipher using machine-specific key."""
        if self._fernet is None:
            # Use machine-specific salt derived from hostname and username
            machine_id = f"{os.uname().nodename}:{os.getlogin()}".encode()
            salt = machine_id[:16].ljust(16, b"\x00")

            # Derive key from salt using PBKDF2
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=480000,
            )
            key = b64encode(kdf.derive(b"xero-mcp-token-encryption"))
            self._fernet = Fernet(key)

        return self._fernet

    def save(self, tokens: TokenSet) -> None:
        """Save tokens to encrypted storage.

        Args:
            tokens: Token set to save
        """
        # Ensure directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Encrypt and save
        data = json.dumps(tokens.to_dict()).encode()
        encrypted = self._get_fernet().encrypt(data)
        self.storage_path.write_bytes(encrypted)

        # Set restrictive permissions (owner read/write only)
        self.storage_path.chmod(0o600)

    def load(self) -> TokenSet | None:
        """Load tokens from encrypted storage.

        Returns:
            Token set if exists and valid, None otherwise
        """
        if not self.storage_path.exists():
            return None

        try:
            encrypted = self.storage_path.read_bytes()
            data = self._get_fernet().decrypt(encrypted)
            return TokenSet.from_dict(json.loads(data))
        except Exception:
            return None

    def delete(self) -> None:
        """Delete stored tokens."""
        if self.storage_path.exists():
            self.storage_path.unlink()

    def exists(self) -> bool:
        """Check if tokens exist in storage."""
        return self.storage_path.exists()

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
