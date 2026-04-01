"""Vectorstore initialization — store creation, embedding model setup, singleton management.

Extracted from vectorstore.py. Contains: embedding model helpers, get_vector_store,
ensure_vector_store, ensure_secondary_store, ensure_feedback_store.
"""
import logging
from typing import Optional, List

import requests
from chromadb import HttpClient, PersistentClient
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings re-exported for submodules that import from vectorstore_init
# ---------------------------------------------------------------------------
_cfg = get_settings()

CHROMA_DIR = _cfg.chroma.dir
DEFAULT_EMBED_MODEL = _cfg.ollama.embed_model
DEFAULT_COLLECTION = f"assistant_memory_{DEFAULT_EMBED_MODEL.replace(':', '_').replace('-', '_')}"
COLLECTION_NAME = _cfg.chroma.collection or DEFAULT_COLLECTION
CHROMA_HTTP_URL = _cfg.chroma.http_url
SECONDARY_COLLECTION = _cfg.chroma.secondary_collection
SECONDARY_DIR = _cfg.chroma.secondary_dir
SECONDARY_EMBED_MODEL = _cfg.chroma.secondary_embed_model or DEFAULT_EMBED_MODEL
FEEDBACK_COLLECTION = (
    _cfg.chroma.feedback_collection
    or f"feedback_qa_{DEFAULT_EMBED_MODEL.replace(':', '_').replace('-', '_')}"
)

# Vector store singletons (module-level state; vectorstore.py references these)
_VECTOR_STORE: Optional[Chroma] = None
_SECONDARY_STORE: Optional[Chroma] = None
_FEEDBACK_STORE: Optional[Chroma] = None

# Models that support instruction-prefix asymmetric embeddings
_INSTRUCTION_PREFIX_MODELS = {
    "nomic-embed-text": {
        "query": "search_query: ",
        "document": "search_document: ",
    },
}


def _ensure_model_available(base_url: str, model: str) -> None:
    """If the model is not listed in /api/tags, trigger a pull once.
    Keeps failures non-fatal to avoid crashing the app."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        if resp.status_code != 200:
            logger.info(f"Embed model check skipped: Ollama returned {resp.status_code}")
            return
        tags = resp.json().get("models", [])
        names = set()
        for t in tags:
            if isinstance(t, dict) and t.get("name"):
                names.add(t["name"])
                # Also match without :latest tag
                names.add(t["name"].replace(":latest", ""))
        if model in names:
            return
        logger.info(f"Embed model '{model}' not found locally, triggering pull...")
        pull_resp = requests.post(f"{base_url}/api/pull", json={"model": model}, timeout=10)
        if pull_resp.status_code >= 400:
            logger.warning(f"Failed to pull embed model {model}: {pull_resp.text}")
    except requests.exceptions.ConnectionError:
        logger.info(f"Embed model check skipped: Ollama not reachable at {base_url}")
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.info(f"Embed model check skipped: {exc}")


class InstructionPrefixEmbeddings:
    """Wrapper around OllamaEmbeddings that adds instruction prefixes for models
    that support asymmetric query/document embeddings (e.g., nomic-embed-text).

    For models that don't support prefixes (e.g., mxbai-embed-large), this is a
    transparent pass-through.
    """

    def __init__(self, base_embeddings: OllamaEmbeddings, model_name: str):
        self._base = base_embeddings
        self._prefixes = _INSTRUCTION_PREFIX_MODELS.get(model_name, {})
        self._query_prefix = self._prefixes.get("query", "")
        self._doc_prefix = self._prefixes.get("document", "")
        if self._prefixes:
            logger.info(f"Instruction prefix embeddings enabled for {model_name}")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if self._doc_prefix:
            texts = [f"{self._doc_prefix}{t}" for t in texts]
        return self._base.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        if self._query_prefix:
            text = f"{self._query_prefix}{text}"
        return self._base.embed_query(text)

    def __getattr__(self, name):
        """Delegate all other attribute access to the base embeddings."""
        return getattr(self._base, name)


def _embedding_model(model: Optional[str] = None, base_url: Optional[str] = None) -> OllamaEmbeddings:
    ollama_cfg = get_settings().ollama
    base = base_url or ollama_cfg.base_url
    mod = model or ollama_cfg.embed_model
    _ensure_model_available(base, mod)
    base_emb = OllamaEmbeddings(model=mod, base_url=base)
    # Wrap with instruction prefix support if the model supports it
    if mod in _INSTRUCTION_PREFIX_MODELS:
        return InstructionPrefixEmbeddings(base_emb, mod)
    return base_emb


# Public alias used by negative_feedback.py and other modules
get_embeddings_model = _embedding_model


def _ensure_collection_exists(store: Chroma) -> bool:
    """Ensure the Chroma collection actually exists on the server."""
    try:
        if not store:
            return False
        coll = getattr(store, "_collection", None)
        if coll is None:
            logger.warning("[VECTORSTORE] Collection object not initialized")
            return False
        try:
            coll.count()
            return True
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
            logger.info(f"[VECTORSTORE] Collection doesn't exist, creating: {coll.name}")
            return True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[VECTORSTORE] Failed to ensure collection exists: {exc}")
        return False


def get_vector_store(
    embedding_model: Optional[str] = None,
    collection_name: Optional[str] = None,
    persist_directory: Optional[str] = None,
) -> Chroma:
    """Create a Chroma store with optional overrides for model, collection, and directory.
    Prefers the REST (v2) client when CHROMA_HTTP_URL is set to avoid local rust bindings.
    """
    directory = persist_directory or CHROMA_DIR
    import os
    os.makedirs(directory, exist_ok=True)
    coll = collection_name or COLLECTION_NAME
    embeddings = _embedding_model(embedding_model)

    # Parse host/port from CHROMA_HTTP_URL (v2 REST). Example: http://127.0.0.1:8001
    http_url = (CHROMA_HTTP_URL or "").strip()
    if http_url:
        from urllib.parse import urlparse
        parsed = urlparse(http_url if "://" in http_url else f"http://{http_url}")
        host = parsed.hostname or "127.0.0.1"
        port_int = parsed.port or 8001
        logger.info("[VECTORSTORE] Using HTTP client: %s:%d", host, port_int)
        chroma_client = HttpClient(
            host=host,
            port=port_int,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
    else:
        logger.info("[VECTORSTORE] Using PersistentClient: %s", directory)
        chroma_client = PersistentClient(
            path=directory, settings=Settings(anonymized_telemetry=False, allow_reset=True)
        )

    store = Chroma(collection_name=coll, embedding_function=embeddings, client=chroma_client)
    _ensure_collection_exists(store)
    return store


def ensure_vector_store() -> Chroma:
    """Get or create the primary vector store with collection validation."""
    global _VECTOR_STORE
    if _VECTOR_STORE is not None:
        # Validate existing store still has valid collection
        if not _ensure_collection_exists(_VECTOR_STORE):
            logger.warning("[VECTORSTORE] Primary collection invalid, reinitializing...")
            _VECTOR_STORE = None

    if _VECTOR_STORE is None:
        _VECTOR_STORE = get_vector_store()

    return _VECTOR_STORE


def ensure_secondary_store() -> Optional[Chroma]:
    """Optional secondary collection (e.g., specs) to widen retrieval without
    changing the primary store. Controlled via CHROMA_SECONDARY_COLLECTION,
    CHROMA_SECONDARY_DIR, and CHROMA_SECONDARY_EMBED_MODEL settings.
    """
    global _SECONDARY_STORE
    if _SECONDARY_STORE is not None:
        return _SECONDARY_STORE
    if not SECONDARY_COLLECTION:
        return None

    try:
        _SECONDARY_STORE = get_vector_store(
            embedding_model=SECONDARY_EMBED_MODEL,
            collection_name=SECONDARY_COLLECTION,
            persist_directory=SECONDARY_DIR,
        )
        logger.info(f"Secondary store initialized: collection={SECONDARY_COLLECTION}")
        return _SECONDARY_STORE
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Failed to initialize secondary store: {e}")
        return None


def ensure_feedback_store() -> Optional[Chroma]:
    """Feedback collection for liked queries — HIGHEST PRIORITY.
    Stores Q&A pairs that users have given thumbs up.
    """
    global _FEEDBACK_STORE
    if _FEEDBACK_STORE is not None:
        return _FEEDBACK_STORE

    try:
        _FEEDBACK_STORE = get_vector_store(
            embedding_model=DEFAULT_EMBED_MODEL,
            collection_name=FEEDBACK_COLLECTION,
            persist_directory=CHROMA_DIR,
        )
        logger.info(f"Feedback store initialized: collection={FEEDBACK_COLLECTION}")
        return _FEEDBACK_STORE
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Failed to initialize feedback store: {e}")
        return None
