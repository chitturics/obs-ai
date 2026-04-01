"""Comprehensive unit tests for chat_app.vectorstore."""
import hashlib
import os
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from chat_app.settings import get_settings

get_settings.cache_clear()

# ---------------------------------------------------------------------------
# Mock heavy dependencies that may not be installed in the test environment
# ---------------------------------------------------------------------------
_MOCK_MODULES = [
    "chromadb", "chromadb.config",
    "langchain_chroma", "langchain_ollama", "langchain_text_splitters",
    "pypdf", "ollama",
    "langchain_community", "langchain_community.document_loaders",
    "cloudscraper", "playwright", "playwright.sync_api",
    "puppeteer",
]
for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Now we can safely import vectorstore
import chat_app.vectorstore  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_vectorstore_singletons():
    """Reset module-level singletons between tests.

    Singletons were moved to sub-modules in v3.5 refactor:
      _VECTOR_STORE, _SECONDARY_STORE, _FEEDBACK_STORE -> vectorstore_init
      _ADDITIONAL_STORES, _AUTO_COLLECTIONS -> vectorstore_collections
    We reset both the sub-modules (authoritative) and the top-level module
    namespace (backward compat) so that test patches work regardless of
    which path code takes.
    """
    import chat_app.vectorstore as mod
    import chat_app.vectorstore_init as mod_init
    import chat_app.vectorstore_collections as mod_coll

    def _reset():
        # Sub-modules (authoritative)
        mod_init._VECTOR_STORE = None
        mod_init._SECONDARY_STORE = None
        mod_init._FEEDBACK_STORE = None
        mod_coll._ADDITIONAL_STORES = None
        mod_coll._AUTO_COLLECTIONS.clear()
        # Top-level aliases (backward compat)
        mod._VECTOR_STORE = None
        mod._SECONDARY_STORE = None
        mod._ADDITIONAL_STORES = None
        mod._FEEDBACK_STORE = None
        if hasattr(mod, "_AUTO_COLLECTIONS"):
            mod._AUTO_COLLECTIONS.clear()

    _reset()
    yield
    _reset()


# ---------------------------------------------------------------------------
# _ensure_model_available
# ---------------------------------------------------------------------------

class TestEnsureModelAvailable:
    @patch("chat_app.vectorstore_init.requests.get")
    def test_model_already_present(self, mock_get):
        from chat_app.vectorstore import _ensure_model_available
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "mxbai-embed-large:latest"}]},
        )
        _ensure_model_available("http://localhost:11434", "mxbai-embed-large")
        # No pull should be triggered
        assert mock_get.call_count == 1  # Only the tags request

    @patch("chat_app.vectorstore_init.requests.post")
    @patch("chat_app.vectorstore_init.requests.get")
    def test_model_missing_triggers_pull(self, mock_get, mock_post):
        from chat_app.vectorstore import _ensure_model_available
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "other-model"}]},
        )
        mock_post.return_value = MagicMock(status_code=200)
        _ensure_model_available("http://localhost:11434", "mxbai-embed-large")
        mock_post.assert_called_once()
        assert "mxbai-embed-large" in str(mock_post.call_args)

    @patch("chat_app.vectorstore_init.requests.get")
    def test_ollama_unreachable(self, mock_get):
        from chat_app.vectorstore import _ensure_model_available
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        # Should not raise
        _ensure_model_available("http://localhost:11434", "mxbai-embed-large")

    @patch("chat_app.vectorstore_init.requests.get")
    def test_non_200_status(self, mock_get):
        from chat_app.vectorstore import _ensure_model_available
        mock_get.return_value = MagicMock(status_code=503)
        _ensure_model_available("http://localhost:11434", "mxbai-embed-large")


# ---------------------------------------------------------------------------
# InstructionPrefixEmbeddings
# ---------------------------------------------------------------------------

class TestInstructionPrefixEmbeddings:
    def test_nomic_embed_text_adds_prefixes(self):
        from chat_app.vectorstore import InstructionPrefixEmbeddings
        base = MagicMock()
        base.embed_documents.return_value = [[0.1, 0.2]]
        base.embed_query.return_value = [0.3, 0.4]

        wrapper = InstructionPrefixEmbeddings(base, "nomic-embed-text")
        wrapper.embed_documents(["hello"])
        base.embed_documents.assert_called_once_with(["search_document: hello"])

        wrapper.embed_query("question")
        base.embed_query.assert_called_once_with("search_query: question")

    def test_mxbai_no_prefix(self):
        from chat_app.vectorstore import InstructionPrefixEmbeddings
        base = MagicMock()
        base.embed_documents.return_value = [[0.1]]
        base.embed_query.return_value = [0.1]

        wrapper = InstructionPrefixEmbeddings(base, "mxbai-embed-large")
        wrapper.embed_documents(["hello"])
        base.embed_documents.assert_called_once_with(["hello"])

        wrapper.embed_query("question")
        base.embed_query.assert_called_once_with("question")

    def test_delegates_unknown_attrs(self):
        from chat_app.vectorstore import InstructionPrefixEmbeddings
        base = MagicMock()
        base.some_method.return_value = "ok"
        wrapper = InstructionPrefixEmbeddings(base, "mxbai-embed-large")
        assert wrapper.some_method() == "ok"


# ---------------------------------------------------------------------------
# get_vector_store
# ---------------------------------------------------------------------------

class TestGetVectorStore:
    @patch("os.makedirs")
    @patch("chat_app.vectorstore_init._ensure_collection_exists", return_value=True)
    @patch("chat_app.vectorstore_init._embedding_model")
    @patch("chat_app.vectorstore_init.Chroma")
    @patch("chat_app.vectorstore_init.HttpClient")
    def test_http_client_when_url_set(self, mock_http, mock_chroma, mock_emb, mock_ensure, mock_mkdirs):
        from chat_app.vectorstore import get_vector_store
        mock_emb.return_value = MagicMock()
        mock_chroma.return_value = MagicMock()
        with patch("chat_app.vectorstore_init.CHROMA_HTTP_URL", "http://chromadb:8001"):
            store = get_vector_store()
        mock_http.assert_called_once()
        assert mock_chroma.called

    @patch("os.makedirs")
    @patch("chat_app.vectorstore_init._ensure_collection_exists", return_value=True)
    @patch("chat_app.vectorstore_init._embedding_model")
    @patch("chat_app.vectorstore_init.Chroma")
    @patch("chat_app.vectorstore_init.PersistentClient")
    def test_persistent_client_when_no_url(self, mock_persist, mock_chroma, mock_emb, mock_ensure, mock_mkdirs):
        from chat_app.vectorstore import get_vector_store
        mock_emb.return_value = MagicMock()
        mock_chroma.return_value = MagicMock()
        with patch("chat_app.vectorstore_init.CHROMA_HTTP_URL", ""):
            store = get_vector_store(persist_directory="/tmp/test_chroma")
        mock_persist.assert_called_once()

    @patch("os.makedirs")
    @patch("chat_app.vectorstore_init._ensure_collection_exists", return_value=True)
    @patch("chat_app.vectorstore_init._embedding_model")
    @patch("chat_app.vectorstore_init.Chroma")
    @patch("chat_app.vectorstore_init.HttpClient")
    def test_custom_collection_name(self, mock_http, mock_chroma, mock_emb, mock_ensure, mock_mkdirs):
        from chat_app.vectorstore import get_vector_store
        mock_emb.return_value = MagicMock()
        mock_chroma.return_value = MagicMock()
        with patch("chat_app.vectorstore_init.CHROMA_HTTP_URL", "http://chromadb:8001"):
            get_vector_store(collection_name="my_custom_collection")
        call_kwargs = mock_chroma.call_args
        assert call_kwargs[1]["collection_name"] == "my_custom_collection" or call_kwargs[0][0] == "my_custom_collection"

    @patch("os.makedirs")
    @patch("chat_app.vectorstore_init._ensure_collection_exists", return_value=True)
    @patch("chat_app.vectorstore_init._embedding_model")
    @patch("chat_app.vectorstore_init.Chroma")
    @patch("chat_app.vectorstore_init.HttpClient")
    def test_custom_embedding_model(self, mock_http, mock_chroma, mock_emb, mock_ensure, mock_mkdirs):
        from chat_app.vectorstore import get_vector_store
        mock_emb.return_value = MagicMock()
        with patch("chat_app.vectorstore_init.CHROMA_HTTP_URL", "http://chromadb:8001"):
            get_vector_store(embedding_model="nomic-embed-text")
        mock_emb.assert_called_once_with("nomic-embed-text")


# ---------------------------------------------------------------------------
# ensure_vector_store (singleton)
# ---------------------------------------------------------------------------

class TestEnsureVectorStore:
    @patch("chat_app.vectorstore_init.get_vector_store")
    def test_creates_store_on_first_call(self, mock_gvs):
        from chat_app.vectorstore import ensure_vector_store
        mock_store = MagicMock()
        mock_gvs.return_value = mock_store
        result = ensure_vector_store()
        assert result is mock_store
        mock_gvs.assert_called_once()

    @patch("chat_app.vectorstore_init.get_vector_store")
    def test_returns_cached_store(self, mock_gvs):
        import chat_app.vectorstore_init as mod_init
        mock_store = MagicMock()
        mod_init._VECTOR_STORE = mock_store
        with patch("chat_app.vectorstore_init._ensure_collection_exists", return_value=True):
            from chat_app.vectorstore import ensure_vector_store
            result = ensure_vector_store()
        assert result is mock_store
        mock_gvs.assert_not_called()

    @patch("chat_app.vectorstore_init.get_vector_store")
    @patch("chat_app.vectorstore_init._ensure_collection_exists", return_value=False)
    def test_reinitializes_on_invalid_collection(self, mock_ensure, mock_gvs):
        import chat_app.vectorstore_init as mod_init
        old_store = MagicMock()
        mod_init._VECTOR_STORE = old_store
        new_store = MagicMock()
        mock_gvs.return_value = new_store
        from chat_app.vectorstore import ensure_vector_store
        result = ensure_vector_store()
        assert result is new_store


# ---------------------------------------------------------------------------
# ensure_secondary_store
# ---------------------------------------------------------------------------

class TestEnsureSecondaryStore:
    @patch("chat_app.vectorstore_init.get_vector_store")
    def test_returns_none_when_no_secondary_collection(self, mock_gvs):
        import chat_app.vectorstore_init as mod_init
        with patch.object(mod_init, "SECONDARY_COLLECTION", ""):
            from chat_app.vectorstore import ensure_secondary_store
            result = ensure_secondary_store()
        assert result is None
        mock_gvs.assert_not_called()

    @patch("chat_app.vectorstore_init.get_vector_store")
    def test_creates_secondary_store(self, mock_gvs):
        import chat_app.vectorstore_init as mod_init
        mock_store = MagicMock()
        mock_gvs.return_value = mock_store
        with patch.object(mod_init, "SECONDARY_COLLECTION", "specs_collection"):
            from chat_app.vectorstore import ensure_secondary_store
            result = ensure_secondary_store()
        assert result is mock_store

    @patch("chat_app.vectorstore_init.get_vector_store", side_effect=RuntimeError("connection failed"))
    def test_returns_none_on_error(self, mock_gvs):
        import chat_app.vectorstore_init as mod_init
        with patch.object(mod_init, "SECONDARY_COLLECTION", "specs_collection"):
            from chat_app.vectorstore import ensure_secondary_store
            result = ensure_secondary_store()
        assert result is None


# ---------------------------------------------------------------------------
# ensure_feedback_store
# ---------------------------------------------------------------------------

class TestEnsureFeedbackStore:
    @patch("chat_app.vectorstore_init.get_vector_store")
    def test_creates_feedback_store(self, mock_gvs):
        mock_store = MagicMock()
        mock_gvs.return_value = mock_store
        from chat_app.vectorstore import ensure_feedback_store
        result = ensure_feedback_store()
        assert result is mock_store

    @patch("chat_app.vectorstore_init.get_vector_store", side_effect=RuntimeError("fail"))
    def test_returns_none_on_error(self, mock_gvs):
        from chat_app.vectorstore import ensure_feedback_store
        result = ensure_feedback_store()
        assert result is None


# ---------------------------------------------------------------------------
# _ensure_collection_exists
# ---------------------------------------------------------------------------

class TestEnsureCollectionExists:
    def test_none_store_returns_false(self):
        from chat_app.vectorstore import _ensure_collection_exists
        assert _ensure_collection_exists(None) is False

    def test_no_collection_attr_returns_false(self):
        from chat_app.vectorstore import _ensure_collection_exists
        store = MagicMock(spec=[])
        store._collection = None
        assert _ensure_collection_exists(store) is False

    def test_valid_collection_count(self):
        from chat_app.vectorstore import _ensure_collection_exists
        store = MagicMock()
        store._collection.count.return_value = 42
        assert _ensure_collection_exists(store) is True

    def test_collection_count_raises_still_returns_true(self):
        from chat_app.vectorstore import _ensure_collection_exists
        store = MagicMock()
        store._collection.count.side_effect = RuntimeError("not found")
        # The function catches this and returns True (auto-create)
        assert _ensure_collection_exists(store) is True


# ---------------------------------------------------------------------------
# _list_all_collections
# ---------------------------------------------------------------------------

class TestListAllCollections:
    @patch("chat_app.vectorstore_collections.HttpClient")
    def test_http_client_list(self, mock_http_cls):
        from chat_app.vectorstore import _list_all_collections
        mock_client = MagicMock()
        mock_col1 = MagicMock()
        mock_col1.name = "collection_one"
        mock_col2 = MagicMock()
        mock_col2.name = "collection_two"
        mock_client.list_collections.return_value = [mock_col1, mock_col2]
        mock_http_cls.return_value = mock_client
        with patch("chat_app.vectorstore_collections.CHROMA_HTTP_URL", "http://chromadb:8001"):
            result = _list_all_collections()
        assert result == ["collection_one", "collection_two"]

    @patch("chat_app.vectorstore_collections.HttpClient")
    def test_dict_style_collections(self, mock_http_cls):
        from chat_app.vectorstore import _list_all_collections
        mock_client = MagicMock()
        mock_client.list_collections.return_value = [
            {"name": "col_a"},
            {"name": "col_b"},
        ]
        mock_http_cls.return_value = mock_client
        with patch("chat_app.vectorstore_collections.CHROMA_HTTP_URL", "http://chromadb:8001"):
            result = _list_all_collections()
        assert result == ["col_a", "col_b"]

    @patch("chat_app.vectorstore_collections.HttpClient", side_effect=RuntimeError("unreachable"))
    def test_error_returns_empty(self, _):
        from chat_app.vectorstore import _list_all_collections
        with patch("chat_app.vectorstore_collections.CHROMA_HTTP_URL", "http://chromadb:8001"):
            result = _list_all_collections()
        assert result == []


# ---------------------------------------------------------------------------
# _persist
# ---------------------------------------------------------------------------

class TestPersist:
    def test_persist_calls_store_persist(self):
        from chat_app.vectorstore import _persist
        store = MagicMock()
        _persist(store)
        store.persist.assert_called_once()

    def test_persist_none_store(self):
        from chat_app.vectorstore import _persist
        _persist(None)  # Should not raise

    def test_persist_fallback_to_client_persist(self):
        from chat_app.vectorstore import _persist
        store = MagicMock(spec=[])
        store._client = MagicMock()
        # No store.persist, but store._client.persist exists
        del store.persist  # ensure hasattr returns False
        # Use a fresh mock that lacks persist attr
        store2 = MagicMock()
        store2.persist.side_effect = AttributeError()
        # Just ensure no crash
        _persist(store2)


# ---------------------------------------------------------------------------
# fingerprint functions
# ---------------------------------------------------------------------------

class TestFingerprints:
    def test_fingerprint_bytes(self):
        from chat_app.vectorstore import _fingerprint_bytes
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        assert _fingerprint_bytes(data) == expected

    def test_has_fingerprint_none_store(self):
        from chat_app.vectorstore import has_fingerprint
        assert has_fingerprint(None, "abc") is False

    def test_has_fingerprint_empty_string(self):
        from chat_app.vectorstore import has_fingerprint
        store = MagicMock()
        assert has_fingerprint(store, "") is False

    def test_has_fingerprint_found(self):
        from chat_app.vectorstore import has_fingerprint
        store = MagicMock()
        store._collection.get.return_value = {"ids": ["doc1"]}
        assert has_fingerprint(store, "abc123") is True

    def test_has_fingerprint_not_found(self):
        from chat_app.vectorstore import has_fingerprint
        store = MagicMock()
        store._collection.get.return_value = {"ids": []}
        assert has_fingerprint(store, "abc123") is False

    def test_has_fingerprint_error(self):
        from chat_app.vectorstore import has_fingerprint
        store = MagicMock()
        store._collection.get.side_effect = ValueError("chromadb down")
        assert has_fingerprint(store, "abc123") is False


# ---------------------------------------------------------------------------
# get_existing_fingerprints
# ---------------------------------------------------------------------------

class TestGetExistingFingerprints:
    def test_empty_input(self):
        from chat_app.vectorstore import get_existing_fingerprints
        assert get_existing_fingerprints(None, []) == set()
        assert get_existing_fingerprints(MagicMock(), []) == set()

    def test_none_store(self):
        from chat_app.vectorstore import get_existing_fingerprints
        assert get_existing_fingerprints(None, ["fp1"]) == set()

    def test_batch_lookup(self):
        from chat_app.vectorstore import get_existing_fingerprints
        store = MagicMock()
        store._collection.get.return_value = {
            "metadatas": [{"fingerprint": "fp1"}, {"fingerprint": "fp2"}],
        }
        result = get_existing_fingerprints(store, ["fp1", "fp2", "fp3"])
        assert result == {"fp1", "fp2"}

    def test_no_collection_attr(self):
        from chat_app.vectorstore import get_existing_fingerprints
        store = MagicMock()
        store._collection = None
        result = get_existing_fingerprints(store, ["fp1"])
        assert result == set()

    @patch("chat_app.vectorstore_fingerprint.has_fingerprint", side_effect=lambda s, fp: fp == "fp1")
    def test_fallback_on_batch_error(self, mock_has):
        from chat_app.vectorstore import get_existing_fingerprints
        store = MagicMock()
        store._collection.get.side_effect = ValueError("$in not supported")
        result = get_existing_fingerprints(store, ["fp1", "fp2"])
        assert "fp1" in result
        assert "fp2" not in result


# ---------------------------------------------------------------------------
# _resolve_auto_collections
# ---------------------------------------------------------------------------

class TestResolveAutoCollections:
    @patch("chat_app.vectorstore_collections._list_all_collections")
    def test_explicit_additional_collections(self, mock_list):
        import chat_app.vectorstore_collections as mod_coll
        with patch.object(mod_coll, "ADDITIONAL_COLLECTIONS", ["extra1", "extra2"]):
            with patch.object(mod_coll, "EXCLUDE_COLLECTIONS", {"extra2"}):
                from chat_app.vectorstore import _resolve_auto_collections
                result = _resolve_auto_collections()
        assert result == ["extra1"]
        mock_list.assert_not_called()

    @patch("chat_app.vectorstore_collections._list_all_collections", return_value=["primary", "secondary", "extra1", "extra2"])
    def test_discover_all_minus_known(self, _):
        import chat_app.vectorstore_collections as mod_coll
        with patch.object(mod_coll, "ADDITIONAL_COLLECTIONS", []):
            with patch.object(mod_coll, "COLLECTION_NAME", "primary"):
                with patch.object(mod_coll, "SECONDARY_COLLECTION", "secondary"):
                    with patch.object(mod_coll, "FEEDBACK_COLLECTION", "feedback"):
                        with patch.object(mod_coll, "EXCLUDE_COLLECTIONS", set()):
                            from chat_app.vectorstore import _resolve_auto_collections
                            result = _resolve_auto_collections()
        assert "primary" not in result
        assert "extra1" in result
        assert "extra2" in result


# ---------------------------------------------------------------------------
# ensure_additional_stores
# ---------------------------------------------------------------------------

class TestEnsureAdditionalStores:
    @patch("chat_app.vectorstore_collections._resolve_auto_collections", return_value=[])
    def test_no_additional(self, _):
        from chat_app.vectorstore import ensure_additional_stores
        result = ensure_additional_stores()
        assert result == []

    @patch("chat_app.vectorstore_collections.get_vector_store")
    @patch("chat_app.vectorstore_collections._resolve_auto_collections", return_value=["extra1"])
    def test_creates_additional_stores(self, _, mock_gvs):
        mock_store = MagicMock()
        mock_gvs.return_value = mock_store
        from chat_app.vectorstore import ensure_additional_stores
        result = ensure_additional_stores()
        assert len(result) == 1
        assert result[0] is mock_store

    @patch("chat_app.vectorstore_collections.get_vector_store", side_effect=ValueError("fail"))
    @patch("chat_app.vectorstore_collections._resolve_auto_collections", return_value=["extra1"])
    def test_error_in_one_collection(self, _, mock_gvs):
        from chat_app.vectorstore import ensure_additional_stores
        result = ensure_additional_stores()
        assert result == []


# ---------------------------------------------------------------------------
# _embedding_model
# ---------------------------------------------------------------------------

class TestEmbeddingModel:
    @patch("chat_app.vectorstore_init._ensure_model_available")
    @patch("chat_app.vectorstore_init.OllamaEmbeddings")
    def test_default_model(self, mock_ollama_emb, mock_ensure):
        from chat_app.vectorstore import _embedding_model
        mock_ollama_emb.return_value = MagicMock()
        result = _embedding_model()
        assert mock_ollama_emb.called

    @patch("chat_app.vectorstore_init._ensure_model_available")
    @patch("chat_app.vectorstore_init.OllamaEmbeddings")
    def test_nomic_wraps_with_instruction_prefix(self, mock_ollama_emb, mock_ensure):
        from chat_app.vectorstore import _embedding_model, InstructionPrefixEmbeddings
        mock_ollama_emb.return_value = MagicMock()
        result = _embedding_model(model="nomic-embed-text")
        assert isinstance(result, InstructionPrefixEmbeddings)

    @patch("chat_app.vectorstore_init._ensure_model_available")
    @patch("chat_app.vectorstore_init.OllamaEmbeddings")
    def test_custom_base_url(self, mock_ollama_emb, mock_ensure):
        from chat_app.vectorstore import _embedding_model
        mock_ollama_emb.return_value = MagicMock()
        _embedding_model(base_url="http://custom:11434")
        mock_ensure.assert_called_once_with("http://custom:11434", mock_ollama_emb.call_args[1]["model"])
