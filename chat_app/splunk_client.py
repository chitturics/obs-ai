"""
Splunk API client for interacting with a Splunk instance.

Provides methods for:
- Saved searches and alerts
- Search execution
- App management
- Index management
- User management
- Data inputs
- Server info and license
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import splunklib.client as client
import splunklib.results as results

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


class SplunkClient:
    """
    Comprehensive Splunk REST API client.

    Connection details are read from centralized settings
    (env vars SPLUNK_HOST, SPLUNK_PORT, SPLUNK_USERNAME,
    SPLUNK_PASSWORD, SPLUNK_TOKEN).
    """

    def __init__(self):
        cfg = get_settings().splunk
        self.host = cfg.host
        self.port = cfg.port
        self.username = cfg.username
        self.password = cfg.password
        self.token = cfg.token
        self.service: Optional[client.Service] = None

    def connect(self):
        """Connect to the Splunk service."""
        if self.service:
            return

        if not self.host:
            raise ConnectionError("SPLUNK_HOST not set. Configure it in settings or environment.")

        try:
            if self.token:
                self.service = client.connect(
                    host=self.host, port=self.port, token=self.token
                )
            elif self.username and self.password:
                self.service = client.connect(
                    host=self.host, port=self.port,
                    username=self.username, password=self.password
                )
            else:
                raise ConnectionError(
                    "Missing Splunk credentials. Set SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD."
                )
            logger.info("Connected to Splunk at %s:%s", self.host, self.port)
        except client.AuthenticationError:
            logger.error("Splunk authentication failed")
            self.service = None
            raise
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("Failed to connect to Splunk: %s", exc)
            self.service = None
            raise

    def _ensure_connected(self):
        if not self.service:
            self.connect()

    # ------------------------------------------------------------------
    # Server Info & License
    # ------------------------------------------------------------------

    def get_server_info(self) -> Dict[str, Any]:
        """Return Splunk server info (version, OS, roles, etc.)."""
        self._ensure_connected()
        info = self.service.info
        return {
            "server_name": info.get("serverName", ""),
            "version": info.get("version", ""),
            "build": info.get("build", ""),
            "os_name": info.get("os_name", ""),
            "os_version": info.get("os_version", ""),
            "cpu_arch": info.get("cpu_arch", ""),
            "server_roles": list(info.get("server_roles", [])),
            "license_state": info.get("licenseState", ""),
            "mode": info.get("mode", ""),
        }

    def get_license_usage(self) -> Dict[str, Any]:
        """Return license usage summary."""
        self._ensure_connected()
        try:
            search_results = self.run_search(
                "| rest /services/licenser/usage | fields quota, slavesUsageBytes",
                max_results=1,
            )
            if search_results:
                row = search_results[0]
                quota = int(row.get("quota", 0))
                used = int(row.get("slavesUsageBytes", 0))
                return {
                    "quota_bytes": quota,
                    "used_bytes": used,
                    "used_gb": round(used / (1024 ** 3), 2),
                    "quota_gb": round(quota / (1024 ** 3), 2),
                    "usage_percent": round(used / quota * 100, 1) if quota else 0,
                }
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("License usage check failed: %s", exc)
        return {}

    # ------------------------------------------------------------------
    # Saved Searches & Alerts
    # ------------------------------------------------------------------

    def get_saved_searches(self, app: str = "-", owner: str = "-") -> List[Dict[str, Any]]:
        """Fetch saved searches from the Splunk instance."""
        self._ensure_connected()
        try:
            saved = self.service.saved_searches.list(app=app, owner=owner)
            return [
                {
                    "name": s.name,
                    "query": s["search"],
                    "app": s.access["app"],
                    "owner": s.access["owner"],
                    "description": s.content.get("description", ""),
                    "cron_schedule": s.content.get("cron_schedule"),
                    "disabled": s.content.get("disabled", "0"),
                }
                for s in saved
            ]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("Failed to fetch saved searches: %s", exc)
            return []

    def create_alert(self, name: str, query: str, **kwargs) -> Any:
        """Create a new Splunk alert (saved search with alert actions)."""
        self._ensure_connected()
        if not query.strip().startswith(("|", "search")):
            query = "search " + query

        params = {
            "search": query,
            "is_scheduled": 1,
            "alert_type": "number of events",
            "alert.comparator": "greater than",
            "alert.threshold": "0",
            "cron_schedule": "*/5 * * * *",
            **kwargs,
        }
        saved_search = self.service.saved_searches.create(name, **params)
        logger.info("Created alert '%s'", name)
        return saved_search

    def delete_alert(self, name: str) -> bool:
        """Delete a saved search/alert by name."""
        self._ensure_connected()
        try:
            self.service.saved_searches.delete(name)
            logger.info("Deleted alert '%s'", name)
            return True
        except client.HTTPError as exc:
            if exc.status == 404:
                logger.warning("Alert '%s' not found", name)
                return False
            raise

    # ------------------------------------------------------------------
    # Search Execution
    # ------------------------------------------------------------------

    def run_search(
        self, spl_query: str, exec_mode: str = "blocking", max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """Run a search query and return results."""
        self._ensure_connected()
        if not spl_query.strip().startswith(("|", "search")):
            spl_query = "search " + spl_query

        logger.info("Running search: %s", spl_query[:100])
        job = self.service.jobs.create(spl_query, exec_mode=exec_mode)
        reader = results.ResultsReader(job.results(count=max_results))
        result_list = [dict(row) for row in reader]
        job.cancel()
        logger.info("Search returned %d results", len(result_list))
        return result_list

    # ------------------------------------------------------------------
    # App Management
    # ------------------------------------------------------------------

    def list_apps(self) -> List[Dict[str, Any]]:
        """List all installed Splunk apps."""
        self._ensure_connected()
        return [
            {
                "name": app.name,
                "label": app.content.get("label", app.name),
                "version": app.content.get("version", ""),
                "visible": app.content.get("visible", "true"),
                "disabled": app.content.get("disabled", "0"),
                "description": app.content.get("description", ""),
            }
            for app in self.service.apps
        ]

    def get_app_info(self, app_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a specific app."""
        self._ensure_connected()
        try:
            app = self.service.apps[app_name]
            return {
                "name": app.name,
                "label": app.content.get("label", ""),
                "version": app.content.get("version", ""),
                "author": app.content.get("author", ""),
                "description": app.content.get("description", ""),
                "visible": app.content.get("visible", "true"),
                "disabled": app.content.get("disabled", "0"),
                "configured": app.content.get("configured", "0"),
            }
        except KeyError:
            return None

    # ------------------------------------------------------------------
    # Index Management
    # ------------------------------------------------------------------

    def list_indexes(self) -> List[Dict[str, Any]]:
        """List all indexes with size and event count."""
        self._ensure_connected()
        return [
            {
                "name": idx.name,
                "total_event_count": idx.content.get("totalEventCount", "0"),
                "current_db_size_mb": idx.content.get("currentDBSizeMB", "0"),
                "max_total_data_size_mb": idx.content.get("maxTotalDataSizeMB", "0"),
                "frozen_time_period_secs": idx.content.get("frozenTimePeriodInSecs", "0"),
                "disabled": idx.content.get("disabled", "0"),
                "datatype": idx.content.get("datatype", "event"),
                "home_path": idx.content.get("homePath", ""),
            }
            for idx in self.service.indexes
        ]

    def get_index_info(self, index_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a specific index."""
        self._ensure_connected()
        try:
            idx = self.service.indexes[index_name]
            return {
                "name": idx.name,
                "total_event_count": idx.content.get("totalEventCount", "0"),
                "current_db_size_mb": idx.content.get("currentDBSizeMB", "0"),
                "max_total_data_size_mb": idx.content.get("maxTotalDataSizeMB", "0"),
                "frozen_time_period_secs": idx.content.get("frozenTimePeriodInSecs", "0"),
                "min_time": idx.content.get("minTime", ""),
                "max_time": idx.content.get("maxTime", ""),
                "disabled": idx.content.get("disabled", "0"),
                "datatype": idx.content.get("datatype", "event"),
                "home_path": idx.content.get("homePath", ""),
                "cold_path": idx.content.get("coldPath", ""),
                "thawed_path": idx.content.get("thawedPath", ""),
            }
        except KeyError:
            return None

    # ------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------

    def list_users(self) -> List[Dict[str, Any]]:
        """List all Splunk users."""
        self._ensure_connected()
        return [
            {
                "name": user.name,
                "realname": user.content.get("realname", ""),
                "email": user.content.get("email", ""),
                "roles": list(user.content.get("roles", [])),
                "type": user.content.get("type", ""),
            }
            for user in self.service.users
        ]

    def get_user_info(self, username: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a specific user."""
        self._ensure_connected()
        try:
            user = self.service.users[username]
            return {
                "name": user.name,
                "realname": user.content.get("realname", ""),
                "email": user.content.get("email", ""),
                "roles": list(user.content.get("roles", [])),
                "capabilities": list(user.content.get("capabilities", [])),
                "default_app": user.content.get("defaultApp", ""),
                "type": user.content.get("type", ""),
            }
        except KeyError:
            return None

    # ------------------------------------------------------------------
    # Data Inputs
    # ------------------------------------------------------------------

    def list_inputs(self, kind: str = "all") -> List[Dict[str, Any]]:
        """
        List data inputs.

        Args:
            kind: Input type filter — 'all', 'monitor', 'tcp', 'udp', 'http', 'script'.
        """
        self._ensure_connected()
        input_list = []

        try:
            if kind in ("all", "monitor"):
                for inp in self.service.inputs.list(kind="monitor"):
                    input_list.append({
                        "type": "monitor",
                        "name": inp.name,
                        "index": inp.content.get("index", "default"),
                        "sourcetype": inp.content.get("sourcetype", ""),
                        "disabled": inp.content.get("disabled", "0"),
                    })

            if kind in ("all", "tcp"):
                for inp in self.service.inputs.list(kind="tcp/raw"):
                    input_list.append({
                        "type": "tcp",
                        "name": inp.name,
                        "index": inp.content.get("index", "default"),
                        "sourcetype": inp.content.get("sourcetype", ""),
                        "disabled": inp.content.get("disabled", "0"),
                    })

            if kind in ("all", "udp"):
                for inp in self.service.inputs.list(kind="udp"):
                    input_list.append({
                        "type": "udp",
                        "name": inp.name,
                        "index": inp.content.get("index", "default"),
                        "sourcetype": inp.content.get("sourcetype", ""),
                        "disabled": inp.content.get("disabled", "0"),
                    })

            if kind in ("all", "http"):
                for inp in self.service.inputs.list(kind="http"):
                    input_list.append({
                        "type": "http",
                        "name": inp.name,
                        "index": inp.content.get("index", "default"),
                        "sourcetype": inp.content.get("sourcetype", ""),
                        "disabled": inp.content.get("disabled", "0"),
                        "token": inp.content.get("token", ""),
                    })
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Failed to list inputs (kind=%s): %s", kind, exc)

        return input_list

    # ------------------------------------------------------------------
    # Lookups & Macros
    # ------------------------------------------------------------------

    def list_lookups(self, app: str = "-") -> List[Dict[str, Any]]:
        """List lookup table files and definitions."""
        self._ensure_connected()
        lookup_list: List[Dict[str, Any]] = []
        try:
            # Lookup definitions (transforms)
            resp = self.service.get(
                "/servicesNS/-/-/data/transforms/lookups",
                output_mode="json", count=0,
            )
            body = json.loads(resp.body.read())
            for entry in body.get("entry", []):
                content = entry.get("content", {})
                lookup_list.append({
                    "name": entry.get("name", ""),
                    "type": content.get("type", "file"),
                    "filename": content.get("filename", ""),
                    "fields_list": content.get("fields_list", ""),
                    "disabled": content.get("disabled", False),
                    "app": entry.get("acl", {}).get("app", ""),
                })
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Failed to list lookups: %s", exc)
        return lookup_list

    def list_macros(self, app: str = "-") -> List[Dict[str, Any]]:
        """List search macros with their definitions."""
        self._ensure_connected()
        macro_list: List[Dict[str, Any]] = []
        try:
            resp = self.service.get(
                "/servicesNS/-/-/configs/conf-macros",
                output_mode="json", count=0,
            )
            body = json.loads(resp.body.read())
            for entry in body.get("entry", []):
                content = entry.get("content", {})
                macro_list.append({
                    "name": entry.get("name", ""),
                    "definition": content.get("definition", ""),
                    "args": content.get("args", ""),
                    "description": content.get("description", ""),
                    "disabled": content.get("disabled", False),
                    "app": entry.get("acl", {}).get("app", ""),
                })
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Failed to list macros: %s", exc)
        return macro_list

    # ------------------------------------------------------------------
    # Index Statistics
    # ------------------------------------------------------------------

    def get_index_stats(self) -> List[Dict[str, Any]]:
        """Get per-index ingestion rates and license usage via REST search."""
        self._ensure_connected()
        try:
            search_results = self.run_search(
                "| rest /services/data/indexes "
                "| fields title, currentDBSizeMB, totalEventCount, "
                "maxTotalDataSizeMB, minTime, maxTime, disabled, datatype",
                max_results=500,
            )
            return search_results
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Failed to get index stats: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Deployment & Forwarder Info
    # ------------------------------------------------------------------

    def list_deployment_clients(self) -> List[Dict[str, Any]]:
        """List deployment server clients and their server classes."""
        self._ensure_connected()
        try:
            search_results = self.run_search(
                "| rest /services/deployment/server/clients "
                "| table clientName, hostname, ip, dns, splunkVersion, "
                "lastPhoneHomeTime, averagePhoneHomeInterval, "
                "build, utsname, serverClasses",
                max_results=500,
            )
            return search_results
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Failed to list deployment clients: %s", exc)
            return []

    def list_forwarders(self) -> List[Dict[str, Any]]:
        """List connected forwarders (requires deployment server role)."""
        self._ensure_connected()
        try:
            search_results = self.run_search(
                "| rest /services/deployment/server/clients "
                "| table clientName, hostname, ip, dns, splunkVersion, "
                "lastPhoneHomeTime, build, utsname",
                max_results=500,
            )
            return search_results
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Failed to list forwarders: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Health & Messages
    # ------------------------------------------------------------------

    def get_messages(self) -> List[Dict[str, Any]]:
        """Get Splunk system messages (license warnings, errors, etc.)."""
        self._ensure_connected()
        messages = []
        try:
            for msg in self.service.messages:
                messages.append({
                    "name": msg.name,
                    "severity": msg.content.get("severity", "info"),
                    "message": msg.content.get("message", ""),
                    "time_created": msg.content.get("timeCreated_epochSecs", ""),
                })
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Failed to get messages: %s", exc)
        return messages

    # ------------------------------------------------------------------
    # Writer Tools (mutating operations — require user approval)
    # ------------------------------------------------------------------

    def update_saved_search(
        self, name: str, app: str = "search", owner: str = "admin", **kwargs
    ) -> Dict[str, Any]:
        """
        Update an existing saved search.

        Supported kwargs: search, description, cron_schedule, is_scheduled,
        disabled, dispatch.earliest_time, dispatch.latest_time,
        alert.threshold, alert.comparator, actions, etc.

        Returns dict with previous and updated values for audit.
        """
        self._ensure_connected()
        try:
            saved = self.service.saved_searches[name, app, owner]
        except KeyError:
            raise ValueError(f"Saved search '{name}' not found in app={app}, owner={owner}")

        # Capture previous state for audit trail
        previous = {
            "name": saved.name,
            "search": saved["search"],
            "description": saved.content.get("description", ""),
            "cron_schedule": saved.content.get("cron_schedule", ""),
            "disabled": saved.content.get("disabled", "0"),
        }

        # Apply updates
        saved.update(**kwargs).refresh()
        logger.info("Updated saved search '%s' (app=%s): %s", name, app, list(kwargs.keys()))

        updated = {
            "name": saved.name,
            "search": saved["search"],
            "description": saved.content.get("description", ""),
            "cron_schedule": saved.content.get("cron_schedule", ""),
            "disabled": saved.content.get("disabled", "0"),
        }

        return {"previous": previous, "updated": updated, "fields_changed": list(kwargs.keys())}

    def create_knowledge_object(
        self,
        object_type: str,
        name: str,
        definition: str,
        app: str = "search",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Create a Splunk knowledge object.

        Supported object_type values:
        - macro: Creates a search macro
        - eventtypes: Creates an event type
        - tags: Creates a tag
        - saved_search: Creates a new saved search

        Returns dict with created object details.
        """
        self._ensure_connected()
        object_type = object_type.lower().strip()

        if object_type == "macro":
            endpoint = f"/servicesNS/nobody/{app}/configs/conf-macros"
            body = {"name": name, "definition": definition, **kwargs}
            self.service.post(endpoint, body=body)
            logger.info("Created macro '%s' in app=%s", name, app)
            return {"type": "macro", "name": name, "definition": definition, "app": app}

        elif object_type == "eventtypes":
            endpoint = f"/servicesNS/nobody/{app}/saved/eventtypes"
            body = {"name": name, "search": definition, **kwargs}
            self.service.post(endpoint, body=body)
            logger.info("Created eventtype '%s' in app=%s", name, app)
            return {"type": "eventtype", "name": name, "search": definition, "app": app}

        elif object_type == "tags":
            # definition should be "field_name=field_value"
            endpoint = f"/servicesNS/nobody/{app}/saved/tags"
            body = {"name": name, "add": definition, **kwargs}
            self.service.post(endpoint, body=body)
            logger.info("Created tag '%s' in app=%s", name, app)
            return {"type": "tag", "name": name, "tag_value": definition, "app": app}

        elif object_type == "saved_search":
            params = {"search": definition, **kwargs}
            self.service.saved_searches.create(name, **params)
            logger.info("Created saved search '%s' in app=%s", name, app)
            return {"type": "saved_search", "name": name, "search": definition, "app": app}

        else:
            raise ValueError(
                f"Unsupported object_type '{object_type}'. "
                "Use: macro, eventtypes, tags, saved_search"
            )

    def get_health_summary(self) -> Dict[str, Any]:
        """Get a comprehensive health summary."""
        self._ensure_connected()
        info = self.get_server_info()
        license_info = self.get_license_usage()
        messages = self.get_messages()

        warning_count = sum(1 for m in messages if m["severity"] in ("warn", "error"))

        return {
            "server": info,
            "license": license_info,
            "messages": messages,
            "warning_count": warning_count,
            "status": "healthy" if warning_count == 0 else "degraded",
        }
