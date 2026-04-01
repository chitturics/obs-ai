"""Tenant Isolation — scoping layer for collections, credentials, and configuration.

Provides logical tenant isolation without separate database instances:
- **Collection scoping**: Tenant-prefixed collection names in ChromaDB
- **Credential scoping**: Per-tenant credential sets
- **Config scoping**: Tenant-specific config overlays
- **Context propagation**: Tenant ID flows through the request pipeline
- **Export/Import**: Tenant data portability

Usage:
    from chat_app.tenant_isolation import get_tenant_manager, TenantContext

    mgr = get_tenant_manager()
    mgr.create_tenant("acme_corp", display_name="Acme Corporation")

    # Scope a collection name
    scoped = mgr.scope_collection("acme_corp", "spl_docs")  # "acme_corp__spl_docs"

    # Get tenant context for request pipeline
    ctx = mgr.get_context("acme_corp")
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


_TENANT_SEPARATOR = "__"  # Collection prefix separator
_TENANTS_FILE = Path(os.getenv("TENANTS_FILE", "/app/data/tenants.json"))


# ---------------------------------------------------------------------------
# Tenant definition
# ---------------------------------------------------------------------------

@dataclass
class Tenant:
    """A logical tenant with its configuration."""
    tenant_id: str
    display_name: str = ""
    enabled: bool = True
    created_at: str = ""
    config_overrides: Dict[str, Any] = field(default_factory=dict)
    allowed_collections: Set[str] = field(default_factory=set)  # Empty = all
    credential_set: str = "default"  # Which credential set to use
    max_users: int = 100
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "config_overrides": self.config_overrides,
            "allowed_collections": sorted(self.allowed_collections) if self.allowed_collections else ["*"],
            "credential_set": self.credential_set,
            "max_users": self.max_users,
            "tags": self.tags,
        }


# ---------------------------------------------------------------------------
# Tenant context (propagated through request pipeline)
# ---------------------------------------------------------------------------

@dataclass
class TenantContext:
    """Request-scoped tenant context."""
    tenant_id: str
    display_name: str = ""
    enabled: bool = True
    collection_prefix: str = ""
    config_overrides: Dict[str, Any] = field(default_factory=dict)
    credential_set: str = "default"

    def scope_collection(self, collection: str) -> str:
        """Prefix a collection name with the tenant ID."""
        if self.collection_prefix and not collection.startswith(self.collection_prefix):
            return f"{self.collection_prefix}{_TENANT_SEPARATOR}{collection}"
        return collection

    def unscope_collection(self, scoped_name: str) -> str:
        """Remove tenant prefix from a collection name."""
        prefix = f"{self.collection_prefix}{_TENANT_SEPARATOR}"
        if scoped_name.startswith(prefix):
            return scoped_name[len(prefix):]
        return scoped_name


# ---------------------------------------------------------------------------
# Export manifest
# ---------------------------------------------------------------------------

@dataclass
class TenantExport:
    """Manifest for a tenant data export."""
    tenant_id: str
    exported_at: str
    collections: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    user_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "exported_at": self.exported_at,
            "collections": self.collections,
            "config": self.config,
            "user_count": self.user_count,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Tenant Manager
# ---------------------------------------------------------------------------

class TenantManager:
    """Manages tenant lifecycle, isolation, and context."""

    def __init__(self):
        self._tenants: Dict[str, Tenant] = {}
        self._lock = threading.Lock()
        self._load_tenants()

    def _load_tenants(self) -> None:
        """Load tenants from persistent storage."""
        if not _TENANTS_FILE.exists():
            # Create default tenant
            self._tenants["default"] = Tenant(
                tenant_id="default",
                display_name="Default Tenant",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            return

        try:
            with open(_TENANTS_FILE, "r") as fh:
                data = json.load(fh)
            for tid, tdata in data.items():
                self._tenants[tid] = Tenant(
                    tenant_id=tid,
                    display_name=tdata.get("display_name", tid),
                    enabled=tdata.get("enabled", True),
                    created_at=tdata.get("created_at", ""),
                    config_overrides=tdata.get("config_overrides", {}),
                    allowed_collections=set(tdata.get("allowed_collections", [])),
                    credential_set=tdata.get("credential_set", "default"),
                    max_users=tdata.get("max_users", 100),
                    tags=tdata.get("tags", []),
                )
            logger.info("[TENANT] Loaded %d tenants", len(self._tenants))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("[TENANT] Failed to load tenants: %s", exc)
            self._tenants["default"] = Tenant(
                tenant_id="default",
                display_name="Default Tenant",
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    def _save_tenants(self) -> None:
        """Persist tenants to file."""
        try:
            _TENANTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {tid: t.to_dict() for tid, t in self._tenants.items()}
            with open(_TENANTS_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("[TENANT] Failed to save tenants: %s", exc)

    # ----- CRUD -----

    def create_tenant(
        self,
        tenant_id: str,
        display_name: str = "",
        config_overrides: Optional[Dict[str, Any]] = None,
        max_users: int = 100,
    ) -> Tenant:
        """Create a new tenant."""
        if tenant_id in self._tenants:
            raise ValueError(f"Tenant already exists: {tenant_id}")
        tenant = Tenant(
            tenant_id=tenant_id,
            display_name=display_name or tenant_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            config_overrides=config_overrides or {},
            max_users=max_users,
        )
        with self._lock:
            self._tenants[tenant_id] = tenant
            self._save_tenants()
        logger.info("[TENANT] Created: %s", tenant_id)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get a tenant by ID."""
        return self._tenants.get(tenant_id)

    def list_tenants(self) -> List[Tenant]:
        """List all tenants."""
        return list(self._tenants.values())

    def update_tenant(self, tenant_id: str, **kwargs) -> Optional[Tenant]:
        """Update tenant properties."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return None
        for key, value in kwargs.items():
            if hasattr(tenant, key):
                setattr(tenant, key, value)
        with self._lock:
            self._save_tenants()
        return tenant

    def disable_tenant(self, tenant_id: str) -> bool:
        """Disable a tenant (soft delete)."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.enabled = False
        with self._lock:
            self._save_tenants()
        return True

    def delete_tenant(self, tenant_id: str) -> bool:
        """Permanently delete a tenant."""
        with self._lock:
            if tenant_id in self._tenants and tenant_id != "default":
                del self._tenants[tenant_id]
                self._save_tenants()
                return True
        return False

    # ----- Context -----

    def get_context(self, tenant_id: str) -> Optional[TenantContext]:
        """Get the tenant context for request-scoped isolation."""
        tenant = self._tenants.get(tenant_id)
        if not tenant or not tenant.enabled:
            return None
        return TenantContext(
            tenant_id=tenant.tenant_id,
            display_name=tenant.display_name,
            enabled=tenant.enabled,
            collection_prefix=tenant.tenant_id if tenant.tenant_id != "default" else "",
            config_overrides=tenant.config_overrides,
            credential_set=tenant.credential_set,
        )

    # ----- Collection scoping -----

    def scope_collection(self, tenant_id: str, collection: str) -> str:
        """Prefix a collection name with the tenant ID."""
        if tenant_id == "default" or not tenant_id:
            return collection
        return f"{tenant_id}{_TENANT_SEPARATOR}{collection}"

    def unscope_collection(self, scoped_name: str) -> tuple:
        """Extract tenant ID and base collection from a scoped name.

        Returns (tenant_id, base_collection).
        """
        if _TENANT_SEPARATOR in scoped_name:
            parts = scoped_name.split(_TENANT_SEPARATOR, 1)
            return parts[0], parts[1]
        return "default", scoped_name

    def get_tenant_collections(self, tenant_id: str) -> List[str]:
        """Get the collection names a tenant is allowed to access."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return []
        if not tenant.allowed_collections:
            return ["*"]  # All collections
        return sorted(tenant.allowed_collections)

    # ----- Export/Import -----

    def export_tenant(self, tenant_id: str) -> Optional[TenantExport]:
        """Generate an export manifest for a tenant."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return None
        return TenantExport(
            tenant_id=tenant_id,
            exported_at=datetime.now(timezone.utc).isoformat(),
            collections=self.get_tenant_collections(tenant_id),
            config=tenant.config_overrides,
            metadata={"display_name": tenant.display_name, "tags": tenant.tags},
        )

    def import_tenant(self, export_data: Dict[str, Any]) -> Tenant:
        """Import a tenant from export data."""
        tenant_id = export_data["tenant_id"]
        return self.create_tenant(
            tenant_id=tenant_id,
            display_name=export_data.get("metadata", {}).get("display_name", tenant_id),
            config_overrides=export_data.get("config", {}),
        )

    # ----- Stats -----

    def get_stats(self) -> Dict[str, Any]:
        """Get tenant management statistics."""
        enabled = sum(1 for t in self._tenants.values() if t.enabled)
        return {
            "total_tenants": len(self._tenants),
            "enabled": enabled,
            "disabled": len(self._tenants) - enabled,
            "tenants": [t.to_dict() for t in self._tenants.values()],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[TenantManager] = None
_instance_lock = threading.Lock()


def get_tenant_manager() -> TenantManager:
    """Get the global TenantManager singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TenantManager()
    return _instance
