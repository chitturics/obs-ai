"""
SplunkConfigManager — loads, ranks, and caches Splunk configurations.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.spl_query_optimizer import SPLQueryOptimizer
from shared.spl_validator import SPLValidator

from .utils import _parse_conf_file, _resolve_data_root

# Optional NLP generator
try:
    from shared.nlp_to_spl import get_nlp_generator
    _NLP_AVAILABLE = True
except ImportError:
    _NLP_AVAILABLE = False
    get_nlp_generator = None

logger = logging.getLogger(__name__)


class SplunkConfigManager:
    """
    Centralized manager for Splunk configurations from organization repositories.

    Loads from:
    - Production: /opt/obsai/chatbot/documents/repo/splunk/ (or SPLUNK_REPO_ROOT env)
    - Dev/local: ./documents/repo/splunk/

    Features:
    - Parses commands.conf, macros.conf, savedsearches.conf
    - Ranks items by complexity, usage patterns, scheduling
    - Persists indexed data locally for fast access
    - Provides search/lookup capabilities
    """

    DEFAULT_REPO_PATHS = [
        "/opt/obsai/chatbot/documents/repo/splunk",
        "/opt/obsai/documents/repo/splunk",
        "/app/public/documents/repo/splunk",
    ]

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or _resolve_data_root()
        self._commands_cache: Dict[str, Dict[str, Any]] = {}
        self._macros_cache: Dict[str, Dict[str, Any]] = {}
        self._searches_cache: Dict[str, Dict[str, Any]] = {}
        self._usage_stats: Dict[str, int] = {}
        self._loaded = False

    def _get_repo_roots(self) -> List[Path]:
        """Get repository roots to scan for Splunk configs."""
        env_root = os.getenv("SPLUNK_REPO_ROOT")
        if env_root:
            roots = [Path(p.strip()) for p in env_root.split(",")]
        else:
            roots = [Path(p) for p in self.DEFAULT_REPO_PATHS]

        local_root = Path.cwd() / "documents" / "repo" / "splunk"
        if local_root.exists() and local_root not in roots:
            roots.append(local_root)

        savedsearch_roots = os.getenv("SAVEDSEARCH_ROOTS")
        if savedsearch_roots:
            for r in savedsearch_roots.split(","):
                p = Path(r.strip())
                if p.exists() and p not in roots:
                    roots.append(p)

        return [r for r in roots if r.exists()]

    def load_all(self, force: bool = False) -> Dict[str, int]:
        """Load all Splunk configurations from repo roots."""
        if self._loaded and not force:
            return {
                "commands": len(self._commands_cache),
                "macros": len(self._macros_cache),
                "searches": len(self._searches_cache),
            }

        roots = self._get_repo_roots()
        logger.info(f"Loading Splunk configs from {len(roots)} roots: {roots}")

        for root in roots:
            self._load_commands(root)
            self._load_macros(root)
            self._load_searches(root)

        self._compute_rankings()
        self._persist_cache()
        self._register_with_optimizer()

        self._loaded = True

        counts = {
            "commands": len(self._commands_cache),
            "macros": len(self._macros_cache),
            "searches": len(self._searches_cache),
        }
        logger.info(f"Loaded Splunk configs: {counts}")
        return counts

    def _load_commands(self, root: Path) -> None:
        """Load commands.conf files from a root directory."""
        for conf_path in root.rglob("commands.conf"):
            try:
                for stanza in _parse_conf_file(conf_path):
                    name = stanza["name"]
                    if name == "default":
                        continue
                    fields = stanza.get("fields", {})
                    self._commands_cache[name] = {
                        "name": name,
                        "file": str(conf_path),
                        "app": self._extract_app_name(conf_path),
                        "type": fields.get("type", "python"),
                        "filename": fields.get("filename", ""),
                        "streaming": fields.get("streaming", "false").lower() == "true",
                        "generating": fields.get("generating", "false").lower() == "true",
                        "retainsevents": fields.get("retainsevents", "false").lower() == "true",
                        "description": fields.get("description", ""),
                        "chunked": fields.get("chunked", "false").lower() == "true",
                        "maxinputs": int(fields.get("maxinputs", 0)) if fields.get("maxinputs") else 0,
                        "rank": 0,
                    }
            except Exception as e:
                logger.warning(f"Failed to parse {conf_path}: {e}")

    def _load_macros(self, root: Path) -> None:
        """Load macros.conf files from a root directory."""
        for conf_path in root.rglob("macros.conf"):
            try:
                for stanza in _parse_conf_file(conf_path):
                    name = stanza["name"]
                    if name == "default":
                        continue
                    fields = stanza.get("fields", {})
                    definition = stanza.get("search") or fields.get("definition", "")
                    arg_match = re.match(r"(.+)\((\d+)\)$", name)
                    if arg_match:
                        base_name = arg_match.group(1)
                        arg_count = int(arg_match.group(2))
                    else:
                        base_name = name
                        arg_count = 0

                    self._macros_cache[name] = {
                        "name": name,
                        "base_name": base_name,
                        "file": str(conf_path),
                        "app": self._extract_app_name(conf_path),
                        "definition": definition,
                        "description": fields.get("description", ""),
                        "arg_count": arg_count,
                        "args": [fields.get(f"args.{i}", "") for i in range(arg_count)],
                        "validation": fields.get("validation", ""),
                        "errormsg": fields.get("errormsg", ""),
                        "iseval": fields.get("iseval", "false").lower() == "true",
                        "has_index": "index=" in definition.lower() if definition else False,
                        "has_sourcetype": "sourcetype=" in definition.lower() if definition else False,
                        "rank": 0,
                    }
            except Exception as e:
                logger.warning(f"Failed to parse {conf_path}: {e}")

    def _load_searches(self, root: Path) -> None:
        """Load savedsearches.conf files from a root directory."""
        for conf_path in root.rglob("savedsearches.conf"):
            try:
                for stanza in _parse_conf_file(conf_path):
                    name = stanza["name"]
                    if name == "default":
                        continue
                    fields = stanza.get("fields", {})
                    search = stanza.get("search") or fields.get("search", "")
                    if not search:
                        continue
                    cron = fields.get("cron_schedule", "")
                    is_scheduled = fields.get("enableSched", "0") == "1"
                    is_alert = bool(fields.get("alert.track") or fields.get("actions"))
                    alert_actions = fields.get("actions", "").split(",") if fields.get("actions") else []
                    expanded_search, macros_used = self._expand_macros_in_search(search)

                    self._searches_cache[name] = {
                        "name": name,
                        "file": str(conf_path),
                        "app": self._extract_app_name(conf_path),
                        "search": search,
                        "search_expanded": expanded_search,
                        "macros_used": macros_used,
                        "description": fields.get("description", ""),
                        "is_scheduled": is_scheduled,
                        "cron_schedule": cron,
                        "is_alert": is_alert,
                        "alert_actions": alert_actions,
                        "dispatch_earliest": fields.get("dispatch.earliest_time", ""),
                        "dispatch_latest": fields.get("dispatch.latest_time", ""),
                        "rank": 0,
                    }
            except Exception as e:
                logger.warning(f"Failed to parse {conf_path}: {e}")

    def _extract_app_name(self, conf_path: Path) -> str:
        """Extract app name from config file path."""
        parts = conf_path.parts
        for i, part in enumerate(parts):
            if part in ("apps", "local", "default") and i + 1 < len(parts):
                return parts[i + 1]
        return "unknown"

    def _expand_macros_in_search(self, search: str) -> Tuple[str, List[str]]:
        """Expand macros in a search string using loaded macro definitions."""
        macros_used = []
        pattern = re.compile(r"`([^`(]+)(?:\([^\)]*\))?`")

        def replace_macro(match):
            name = match.group(1)
            macros_used.append(name)
            macro = self._macros_cache.get(name) or self._macros_cache.get(f"{name}(1)") or self._macros_cache.get(f"{name}(2)")
            if macro and macro.get("definition"):
                return macro["definition"]
            return match.group(0)

        expanded = pattern.sub(replace_macro, search)
        return expanded, macros_used

    def _compute_rankings(self) -> None:
        """Compute relevance rankings for all items."""
        for name, cmd in self._commands_cache.items():
            rank = 10
            if cmd.get("generating"):
                rank += 20
            if cmd.get("streaming"):
                rank += 10
            if cmd.get("description"):
                rank += 5
            cmd["rank"] = rank

        macro_usage = {}
        for search in self._searches_cache.values():
            for macro_name in search.get("macros_used", []):
                macro_usage[macro_name] = macro_usage.get(macro_name, 0) + 1

        for name, macro in self._macros_cache.items():
            rank = 10
            base_name = macro.get("base_name", name)
            rank += macro_usage.get(base_name, 0) * 5
            rank += macro_usage.get(name, 0) * 5
            if macro.get("has_index"):
                rank += 15
            if macro.get("has_sourcetype"):
                rank += 10
            if macro.get("description"):
                rank += 5
            macro["rank"] = rank

        for name, search in self._searches_cache.items():
            rank = 10
            if search.get("is_scheduled"):
                rank += 30
            if search.get("is_alert"):
                rank += 25
            if search.get("macros_used"):
                rank += len(search["macros_used"]) * 3
            if search.get("description"):
                rank += 5
            search_len = len(search.get("search", ""))
            if search_len > 500:
                rank += 10
            elif search_len > 200:
                rank += 5
            search["rank"] = rank

    def _persist_cache(self) -> None:
        """Persist loaded configs to local cache files."""
        cache_dir = self.data_root / "splunk_configs"
        cache_dir.mkdir(parents=True, exist_ok=True)

        commands_file = cache_dir / "commands_index.json"
        commands_file.write_text(json.dumps(self._commands_cache, indent=2, default=str), encoding="utf-8")

        macros_file = cache_dir / "macros_index.json"
        macros_file.write_text(json.dumps(self._macros_cache, indent=2, default=str), encoding="utf-8")

        searches_sorted = sorted(self._searches_cache.values(), key=lambda x: x.get("rank", 0), reverse=True)
        searches_file = cache_dir / "searches_index.json"
        searches_file.write_text(json.dumps(searches_sorted, indent=2, default=str), encoding="utf-8")

        summary = {
            "loaded_at": datetime.now().isoformat(),
            "counts": {
                "commands": len(self._commands_cache),
                "macros": len(self._macros_cache),
                "searches": len(self._searches_cache),
            },
            "top_macros": [
                {"name": m["name"], "rank": m["rank"], "has_index": m.get("has_index")}
                for m in sorted(self._macros_cache.values(), key=lambda x: x.get("rank", 0), reverse=True)[:20]
            ],
            "top_searches": [
                {"name": s["name"], "rank": s["rank"], "is_scheduled": s.get("is_scheduled")}
                for s in searches_sorted[:20]
            ],
        }
        summary_file = cache_dir / "config_summary.json"
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        logger.info(f"Persisted Splunk configs to {cache_dir}")

    def _register_with_optimizer(self) -> None:
        """Register loaded macros with the SPL optimizer and NLP generator."""
        macro_defs = {}
        for name, macro in self._macros_cache.items():
            if macro.get("definition"):
                base_name = macro.get("base_name", name)
                macro_defs[base_name] = macro["definition"]
                macro_defs[name] = macro["definition"]

        if macro_defs:
            SPLQueryOptimizer.register_macros(macro_defs)
            logger.info(f"Registered {len(macro_defs)} macros with SPL optimizer")

        if self._commands_cache:
            SPLValidator.register_custom_commands(set(self._commands_cache.keys()))
            logger.info(f"Registered {len(self._commands_cache)} custom commands with SPL validator")

        if _NLP_AVAILABLE:
            try:
                nlp_gen = get_nlp_generator()
                if self._macros_cache:
                    macro_count = nlp_gen.load_macros(self._macros_cache)
                    logger.info(f"Loaded {macro_count} macros for NLP generation")
                if self._searches_cache:
                    search_count = nlp_gen.load_saved_searches(self._searches_cache)
                    logger.info(f"Loaded {search_count} saved searches for NLP generation")
            except Exception as e:
                logger.warning(f"Failed to register with NLP generator: {e}")

    # -- Public accessors --

    def get_commands(self) -> Dict[str, Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        return self._commands_cache

    def get_macros(self) -> Dict[str, Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        return self._macros_cache

    def get_searches(self) -> Dict[str, Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        return self._searches_cache

    def get_macro(self, name: str) -> Optional[Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        return self._macros_cache.get(name)

    def search_macros(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        query_lower = query.lower()
        results = []
        for name, macro in self._macros_cache.items():
            score = 0
            if query_lower in name.lower():
                score += 50
            if query_lower in (macro.get("definition") or "").lower():
                score += 20
            if query_lower in (macro.get("description") or "").lower():
                score += 10
            if score > 0:
                results.append((score + macro.get("rank", 0), macro))
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def search_saved_searches(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        query_lower = query.lower()
        results = []
        for name, search in self._searches_cache.items():
            score = 0
            if query_lower in name.lower():
                score += 50
            if query_lower in (search.get("search") or "").lower():
                score += 20
            if query_lower in (search.get("description") or "").lower():
                score += 10
            if score > 0:
                results.append((score + search.get("rank", 0), search))
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def get_top_macros(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        return sorted(self._macros_cache.values(), key=lambda x: x.get("rank", 0), reverse=True)[:limit]

    def get_top_searches(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        return sorted(self._searches_cache.values(), key=lambda x: x.get("rank", 0), reverse=True)[:limit]

    def record_usage(self, item_type: str, name: str) -> None:
        key = f"{item_type}:{name}"
        self._usage_stats[key] = self._usage_stats.get(key, 0) + 1
        if sum(self._usage_stats.values()) % 100 == 0:
            usage_file = self.data_root / "splunk_configs" / "usage_stats.json"
            usage_file.parent.mkdir(parents=True, exist_ok=True)
            usage_file.write_text(json.dumps(self._usage_stats, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_splunk_config_manager: Optional[SplunkConfigManager] = None


def get_splunk_config_manager() -> SplunkConfigManager:
    """Get the global Splunk config manager instance."""
    global _splunk_config_manager
    if _splunk_config_manager is None:
        _splunk_config_manager = SplunkConfigManager()
    return _splunk_config_manager
