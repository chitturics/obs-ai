"""Archival Memory -- Long-term persistent knowledge store with keyword search."""
import hashlib
import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


def _make_note(id: str, content: str, source: str = "user", category: str = "fact",
               tags: list = None, related_to: list = None, user_id: str = "",
               created_at: str = "", access_count: int = 0, last_accessed: str = "",
               importance: float = 0.5) -> Dict[str, Any]:
    return {"id": id, "content": content, "source": source, "category": category,
            "tags": tags or [], "related_to": related_to or [], "user_id": user_id,
            "created_at": created_at, "access_count": access_count,
            "last_accessed": last_accessed, "importance": importance}

# Backward compat alias
MemoryNote = _make_note


class ArchivalMemory:
    def __init__(self, storage_path: str = "/app/data/archival_memory.json", max_notes: int = 10000):
        self._notes: Dict[str, Dict] = {}
        self._tag_index: Dict[str, List[str]] = defaultdict(list)
        self._user_index: Dict[str, List[str]] = defaultdict(list)
        self._lock = threading.Lock()
        self._storage_path = storage_path
        self._max_notes = max_notes
        self._dirty = False
        self._load()

    def store(self, content: str, source="user", category="fact", tags=None,
              user_id="", importance=0.5, related_to=None) -> Dict:
        nid = hashlib.sha256(f"{content}:{time.time()}".encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc).isoformat()
        note = _make_note(nid, content, source, category, tags, related_to, user_id, now, 0, now, importance)
        with self._lock:
            self._notes[nid] = note
            for tag in note["tags"]:
                self._tag_index[tag].append(nid)
            if user_id:
                self._user_index[user_id].append(nid)
            self._dirty = True
            if len(self._notes) > self._max_notes:
                self._evict()
        logger.info("[ARCHIVAL] Stored %s: %s...", nid[:8], content[:60])
        return note

    def recall(self, query: str, user_id: str = "", limit: int = 5) -> List[Dict]:
        qtoks = set(query.lower().split())
        scored: List[Tuple[float, Dict]] = []
        with self._lock:
            for note in self._notes.values():
                if user_id and note["user_id"] and note["user_id"] != user_id:
                    continue
                overlap = len(qtoks & set(note["content"].lower().split())) / max(len(qtoks), 1)
                tag_match = len(qtoks & {t.lower() for t in note["tags"]}) / max(len(qtoks), 1)
                score = overlap * 0.4 + tag_match * 0.3 + note["importance"] * 0.2 + 0.1
                if score > 0.2:
                    scored.append((score, note))
                    note["access_count"] += 1
                    note["last_accessed"] = datetime.now(timezone.utc).isoformat()
        scored.sort(key=lambda x: -x[0])
        return [n for _, n in scored[:limit]]

    def get_by_category(self, category: str, limit=20) -> List[Dict]:
        with self._lock:
            notes = sorted([n for n in self._notes.values() if n["category"] == category],
                           key=lambda n: n["importance"], reverse=True)
        return notes[:limit]

    def get_by_tags(self, tags: List[str], limit=10) -> List[Dict]:
        with self._lock:
            ids = {nid for tag in tags for nid in self._tag_index.get(tag, [])}
            return [self._notes[nid] for nid in list(ids)[:limit] if nid in self._notes]

    def get_user_memories(self, user_id: str, limit=20) -> List[Dict]:
        with self._lock:
            return [self._notes[nid] for nid in self._user_index.get(user_id, [])[-limit:] if nid in self._notes]

    def delete(self, note_id: str) -> bool:
        with self._lock:
            note = self._notes.pop(note_id, None)
            if not note:
                return False
            for tag in note["tags"]:
                if note_id in (idx := self._tag_index.get(tag, [])):
                    idx.remove(note_id)
            if note["user_id"] and note_id in (idx := self._user_index.get(note["user_id"], [])):
                idx.remove(note_id)
            self._dirty = True
        return True

    def get_stats(self) -> Dict:
        with self._lock:
            cats, srcs = defaultdict(int), defaultdict(int)
            for n in self._notes.values():
                cats[n["category"]] += 1
                srcs[n["source"]] += 1
            return {"total_notes": len(self._notes), "max_notes": self._max_notes,
                    "by_category": dict(cats), "by_source": dict(srcs),
                    "unique_users": len(self._user_index), "unique_tags": len(self._tag_index),
                    "storage_path": self._storage_path}

    def _evict(self):
        if len(self._notes) <= self._max_notes:
            return
        for note in sorted(self._notes.values(), key=lambda n: n["importance"])[:len(self._notes) - self._max_notes + 100]:
            del self._notes[note["id"]]
        self._dirty = True

    def save(self):
        if not self._dirty:
            return
        with self._lock:
            data = list(self._notes.values())
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2)
            self._dirty = False
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("[ARCHIVAL] Save failed: %s", e)

    def _load(self):
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path) as f:
                for d in json.load(f):
                    self._notes[d["id"]] = d
                    for tag in d.get("tags", []):
                        self._tag_index[tag].append(d["id"])
                    if d.get("user_id"):
                        self._user_index[d["user_id"]].append(d["id"])
            logger.info("[ARCHIVAL] Loaded %d notes", len(self._notes))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("[ARCHIVAL] Load failed: %s", e)


_archival: Optional[ArchivalMemory] = None

def get_archival_memory() -> ArchivalMemory:
    global _archival
    if _archival is None:
        _archival = ArchivalMemory()
    return _archival
