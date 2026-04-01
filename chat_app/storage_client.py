"""
Local filesystem storage client for Chainlit blob storage.
"""
import os
from pathlib import Path
from chainlit.logger import logger
try:
    from chainlit.data.storage_clients.base import BaseStorageClient
except ImportError:
    from chainlit.data import BaseStorageClient


class LocalStorageClient(BaseStorageClient):
    """Local filesystem storage client for Chainlit blob storage."""

    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, object_key: str) -> Path:
        safe_key = object_key.lstrip("/")
        resolved = (self.storage_path / safe_key).resolve()
        if not str(resolved).startswith(str(self.storage_path.resolve())):
            raise ValueError(f"Path traversal detected: {object_key}")
        return resolved

    async def upload_file(self, object_key, data, mime="application/octet-stream",
                          overwrite=True, content_disposition=None):
        try:
            file_path = self._get_file_path(object_key)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not overwrite and file_path.exists():
                return {"object_key": object_key, "url": str(file_path)}
            if isinstance(data, str):
                file_path.write_text(data, encoding="utf-8")
            else:
                file_path.write_bytes(data)
            return {"object_key": object_key, "url": str(file_path)}
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning(f"[STORAGE] upload_file failed: {e}")
            return {"object_key": object_key, "url": None}

    async def delete_file(self, object_key):
        try:
            file_path = self._get_file_path(object_key)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except (OSError, ValueError, KeyError, TypeError) as _exc:
            return False

    async def get_read_url(self, object_key):
        file_path = self._get_file_path(object_key)
        if file_path.exists():
            return f"/public/blobs/{object_key}"
        return ""

    async def close(self):
        pass


_storage_client = None


def get_storage_client():
    global _storage_client
    if _storage_client is None:
        blob_path = os.getenv("BLOB_STORAGE_PATH", "/app/.chainlit/blobs")
        try:
            _storage_client = LocalStorageClient(blob_path)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"[STORAGE] Failed to initialize: {e}")
            _storage_client = None
    return _storage_client
