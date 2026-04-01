"""Least-Privilege Connectors — scoped credentials per action for Splunk/Cribl.

Maps each tool action to the minimum required credential scope, ensuring:
- Read-only tools use read-only credentials (when available)
- Write tools use write-scoped credentials
- Admin tools use admin credentials only when necessary
- Credential selection is automatic based on tool safety level

Also tracks credential usage for audit and provides a connector health view.

Usage:
    from chat_app.credential_scoping import get_credential_manager

    mgr = get_credential_manager()
    cred = mgr.get_credential("splunk", "search")  # Returns read-only cred
    cred = mgr.get_credential("splunk", "update_saved_search")  # Returns write cred
"""

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credential scope levels
# ---------------------------------------------------------------------------

class CredentialScope(str, Enum):
    READ = "read"        # Search, list, get operations
    WRITE = "write"      # Create, update operations
    ADMIN = "admin"      # Delete, manage, configure operations
    SUPERADMIN = "superadmin"  # Full access (avoid when possible)


# ---------------------------------------------------------------------------
# Credential definition
# ---------------------------------------------------------------------------

@dataclass
class ConnectorCredential:
    """A scoped credential for an external service connector."""
    name: str
    service: str  # splunk, cribl, etc.
    scope: CredentialScope
    env_var: str  # Environment variable holding the credential
    description: str = ""
    is_set: bool = False
    last_used: Optional[str] = None
    use_count: int = 0
    actions: Set[str] = field(default_factory=set)  # Actions this credential supports

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "service": self.service,
            "scope": self.scope.value,
            "env_var": self.env_var,
            "description": self.description,
            "is_set": self.is_set,
            "last_used": self.last_used,
            "use_count": self.use_count,
            "actions": sorted(self.actions),
        }


# ---------------------------------------------------------------------------
# Tool-to-scope mapping
# ---------------------------------------------------------------------------

_TOOL_SCOPES: Dict[str, Dict[str, CredentialScope]] = {
    "splunk": {
        # Read operations
        "splunk_search": CredentialScope.READ,
        "list_saved_searches": CredentialScope.READ,
        "list_indexes": CredentialScope.READ,
        "list_inputs": CredentialScope.READ,
        "list_apps": CredentialScope.READ,
        "list_users": CredentialScope.READ,
        "get_splunk_health": CredentialScope.READ,
        "get_license_info": CredentialScope.READ,
        "get_cluster_health": CredentialScope.READ,
        "list_deployment_apps": CredentialScope.READ,
        "validate_spl": CredentialScope.READ,
        # Write operations
        "update_saved_search": CredentialScope.WRITE,
        "create_saved_search": CredentialScope.WRITE,
        "create_input": CredentialScope.WRITE,
        "update_input": CredentialScope.WRITE,
        "send_hec_event": CredentialScope.WRITE,
        # Admin operations
        "delete_saved_search": CredentialScope.ADMIN,
        "delete_index": CredentialScope.ADMIN,
        "manage_users": CredentialScope.ADMIN,
    },
    "cribl": {
        # Read operations
        "get_pipeline_status": CredentialScope.READ,
        "list_pipelines": CredentialScope.READ,
        "list_routes": CredentialScope.READ,
        "list_packs": CredentialScope.READ,
        "list_worker_groups": CredentialScope.READ,
        # Write operations
        "update_pipeline": CredentialScope.WRITE,
        "deploy_pipeline": CredentialScope.WRITE,
        "create_route": CredentialScope.WRITE,
        # Admin operations
        "delete_pipeline": CredentialScope.ADMIN,
        "rollback_pipeline": CredentialScope.ADMIN,
    },
}


# ---------------------------------------------------------------------------
# Default credentials per service and scope
# ---------------------------------------------------------------------------

_DEFAULT_CREDENTIALS: List[ConnectorCredential] = [
    # Splunk
    ConnectorCredential(
        name="splunk_read",
        service="splunk",
        scope=CredentialScope.READ,
        env_var="SPLUNK_READ_TOKEN",
        description="Splunk read-only token (search, list operations)",
        actions={"splunk_search", "list_saved_searches", "list_indexes", "list_inputs",
                 "list_apps", "list_users", "get_splunk_health", "get_license_info",
                 "get_cluster_health", "list_deployment_apps", "validate_spl"},
    ),
    ConnectorCredential(
        name="splunk_write",
        service="splunk",
        scope=CredentialScope.WRITE,
        env_var="SPLUNK_WRITE_TOKEN",
        description="Splunk write token (create, update operations)",
        actions={"update_saved_search", "create_saved_search", "create_input",
                 "update_input", "send_hec_event"},
    ),
    ConnectorCredential(
        name="splunk_admin",
        service="splunk",
        scope=CredentialScope.ADMIN,
        env_var="SPLUNK_ADMIN_TOKEN",
        description="Splunk admin token (delete, manage operations)",
        actions={"delete_saved_search", "delete_index", "manage_users"},
    ),
    ConnectorCredential(
        name="splunk_fallback",
        service="splunk",
        scope=CredentialScope.SUPERADMIN,
        env_var="SPLUNK_PASSWORD",
        description="Splunk admin password (fallback — full access)",
    ),
    # Cribl
    ConnectorCredential(
        name="cribl_read",
        service="cribl",
        scope=CredentialScope.READ,
        env_var="CRIBL_READ_TOKEN",
        description="Cribl read-only token",
        actions={"get_pipeline_status", "list_pipelines", "list_routes",
                 "list_packs", "list_worker_groups"},
    ),
    ConnectorCredential(
        name="cribl_write",
        service="cribl",
        scope=CredentialScope.WRITE,
        env_var="CRIBL_WRITE_TOKEN",
        description="Cribl write token (deploy, update operations)",
        actions={"update_pipeline", "deploy_pipeline", "create_route"},
    ),
    ConnectorCredential(
        name="cribl_admin",
        service="cribl",
        scope=CredentialScope.ADMIN,
        env_var="CRIBL_ADMIN_TOKEN",
        description="Cribl admin token (delete, rollback operations)",
        actions={"delete_pipeline", "rollback_pipeline"},
    ),
    # HEC
    ConnectorCredential(
        name="splunk_hec",
        service="splunk",
        scope=CredentialScope.WRITE,
        env_var="SPLUNK_HEC_TOKEN",
        description="Splunk HEC token for event ingestion",
        actions={"send_hec_event"},
    ),
]

# Scope hierarchy: higher scopes can do everything lower scopes can
_SCOPE_HIERARCHY = {
    CredentialScope.READ: 0,
    CredentialScope.WRITE: 1,
    CredentialScope.ADMIN: 2,
    CredentialScope.SUPERADMIN: 3,
}


# ---------------------------------------------------------------------------
# Credential Manager
# ---------------------------------------------------------------------------

class CredentialManager:
    """Manages scoped credentials for external service connectors."""

    def __init__(self):
        self._credentials: Dict[str, ConnectorCredential] = {}
        self._lock = threading.Lock()

        for cred in _DEFAULT_CREDENTIALS:
            cred.is_set = bool(os.getenv(cred.env_var, "").strip())
            self._credentials[cred.name] = cred

    def get_credential(self, service: str, action: str) -> Optional[ConnectorCredential]:
        """Get the least-privilege credential for a service+action pair.

        Returns the credential with the minimum scope that supports the action.
        Falls back to higher-scope credentials if the exact scope isn't available.
        """
        # Determine required scope
        service_scopes = _TOOL_SCOPES.get(service, {})
        required_scope = service_scopes.get(action, CredentialScope.READ)
        required_level = _SCOPE_HIERARCHY[required_scope]

        # Find the best credential: prefer exact scope match, then fallback up
        candidates = [
            c for c in self._credentials.values()
            if c.service == service and c.is_set
        ]

        if not candidates:
            logger.warning("[CRED] No credentials available for %s:%s", service, action)
            return None

        # Sort by scope level (ascending) and filter to those that can handle this action
        candidates.sort(key=lambda c: _SCOPE_HIERARCHY[c.scope])

        # First try: exact action match
        for cred in candidates:
            if action in cred.actions and _SCOPE_HIERARCHY[cred.scope] >= required_level:
                self._record_use(cred)
                return cred

        # Second try: scope level match (credential covers the scope even without explicit action)
        for cred in candidates:
            if _SCOPE_HIERARCHY[cred.scope] >= required_level:
                self._record_use(cred)
                return cred

        logger.warning("[CRED] No sufficient credential for %s:%s (need %s)", service, action, required_scope.value)
        return None

    def _record_use(self, cred: ConnectorCredential) -> None:
        """Track credential usage."""
        cred.last_used = datetime.now(timezone.utc).isoformat()
        cred.use_count += 1

    def get_all_credentials(self) -> List[ConnectorCredential]:
        """Get all registered credentials."""
        return list(self._credentials.values())

    def get_for_service(self, service: str) -> List[ConnectorCredential]:
        """Get all credentials for a service."""
        return [c for c in self._credentials.values() if c.service == service]

    def get_connector_health(self) -> Dict[str, Any]:
        """Get health status of all connectors."""
        services: Dict[str, Dict[str, Any]] = {}
        for cred in self._credentials.values():
            if cred.service not in services:
                services[cred.service] = {
                    "service": cred.service,
                    "credentials": [],
                    "any_set": False,
                    "scopes_available": set(),
                }
            services[cred.service]["credentials"].append(cred.to_dict())
            if cred.is_set:
                services[cred.service]["any_set"] = True
                services[cred.service]["scopes_available"].add(cred.scope.value)

        # Convert sets to lists for JSON serialization
        for svc in services.values():
            svc["scopes_available"] = sorted(svc["scopes_available"])

        return {
            "connectors": services,
            "total_credentials": len(self._credentials),
            "set_count": sum(1 for c in self._credentials.values() if c.is_set),
            "unset_count": sum(1 for c in self._credentials.values() if not c.is_set),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_scope_for_action(self, service: str, action: str) -> str:
        """Get the required scope for a service action."""
        service_scopes = _TOOL_SCOPES.get(service, {})
        scope = service_scopes.get(action, CredentialScope.READ)
        return scope.value

    def get_all_scopes(self) -> Dict[str, Dict[str, str]]:
        """Get all tool-to-scope mappings."""
        return {
            service: {action: scope.value for action, scope in actions.items()}
            for service, actions in _TOOL_SCOPES.items()
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[CredentialManager] = None
_instance_lock = threading.Lock()


def get_credential_manager() -> CredentialManager:
    """Get the global CredentialManager singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CredentialManager()
    return _instance
