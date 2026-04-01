"""Config versioning — git-style version tracking for configuration changes."""
import hashlib
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _make_commit(id, parent_id, hash, section, diff, message, author, timestamp):
    return {"id": id, "parent_id": parent_id, "hash": hash, "section": section,
            "diff": diff, "message": message, "author": author, "timestamp": timestamp}

ConfigCommit = _make_commit  # alias for backward compat


class ConfigVersionStore:
    def __init__(self, max_commits: int = 500):
        self._commits: deque = deque(maxlen=max_commits)
        self._head: str | None = None
        self._snapshots: dict[str, dict] = {}

    def commit(self, section: str, old_value, new_value,
               message: str = "", author: str = "system") -> dict:
        content = json.dumps(new_value, sort_keys=True, default=str)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        commit_id = hashlib.sha256(f"{content_hash}:{time.time()}".encode()).hexdigest()[:16]

        c = _make_commit(
            id=commit_id, parent_id=self._head, hash=content_hash, section=section,
            diff=self._compute_diff(old_value, new_value),
            message=message or f"Update {section}", author=author,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._commits.append(c)
        self._head = commit_id
        self._snapshots[commit_id] = {"section": section, "value": new_value}
        logger.info("[CONFIG-VERSION] Commit %s: %s by %s", commit_id[:8], c["message"], author)
        return c

    @property
    def head(self) -> str | None:
        return self._head

    def get_history(self, section: str | None = None, limit: int = 50) -> list[dict]:
        commits = [c for c in self._commits if not section or c["section"] == section]
        return list(reversed(commits))[:limit]

    def get_commit(self, commit_id: str) -> dict | None:
        for c in self._commits:
            if c["id"] == commit_id:
                result = dict(c)
                if snap := self._snapshots.get(commit_id):
                    result["snapshot"] = snap
                return result
        return None

    def rollback(self, commit_id: str) -> dict | None:
        return self._snapshots.get(commit_id)

    def _compute_diff(self, old, new) -> dict:
        if old is None:
            return {"type": "created", "new": new}
        if isinstance(old, dict) and isinstance(new, dict):
            return {
                "added": {k: v for k, v in new.items() if k not in old},
                "removed": {k: v for k, v in old.items() if k not in new},
                "changed": {k: {"old": old[k], "new": new[k]} for k in old if k in new and old[k] != new[k]},
            }
        return {"old": old, "new": new}


# Singleton — kept as module var so tests can reset via `mod._store = None`
_store: ConfigVersionStore | None = None

def get_config_version_store() -> ConfigVersionStore:
    global _store
    if _store is None:
        _store = ConfigVersionStore()
    return _store
