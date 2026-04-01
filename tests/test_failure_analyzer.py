"""
Comprehensive tests for chat_app.failure_analyzer module.

Covers:
- FailureType enum — every member verified
- FailureSeverity levels — correct assignment per failure category
- RecoveryAction enum — str-enum behaviour, all members
- FailureReport dataclass — construction, defaults, mutable-field isolation
- categorize_failure() — dispatches to _classify_by_type then _classify_by_message
- _classify_by_type() — isinstance-based classification (TimeoutError, ConnectionError,
  OSError, RuntimeError with "model")
- _classify_by_message() — string-pattern classification (timeout, connection, auth,
  model-not-found, tool, cribl, chroma/vector, unknown fallback)
- categorize_quality_failure() — quality degradation (zero chunks, sparse+low-confidence,
  short response, boundary conditions, priority ordering)
- Real production exception messages throughout

All tests are pure/synchronous — no mocks, no I/O, no async.
"""
import pytest

from chat_app.failure_analyzer import (
    FailureReport,
    FailureType,
    RecoveryAction,
    categorize_failure,
    categorize_quality_failure,
    _classify_by_type,
    _classify_by_message,
)


# ---------------------------------------------------------------------------
# 1. FailureType enum — every member exists with the correct string value
# ---------------------------------------------------------------------------

class TestFailureTypeEnum:
    """Verify every documented enum member is present and is a str."""

    @pytest.mark.parametrize("member,value", [
        ("RETRIEVAL_EMPTY", "retrieval_empty"),
        ("RETRIEVAL_SPARSE", "retrieval_sparse"),
        ("LLM_TIMEOUT", "llm_timeout"),
        ("LLM_ERROR", "llm_error"),
        ("LLM_EMPTY_RESPONSE", "llm_empty_response"),
        ("TOOL_FAILED", "tool_failed"),
        ("TOOL_TIMEOUT", "tool_timeout"),
        ("HALLUCINATION_DETECTED", "hallucination_detected"),
        ("SPL_INVALID", "spl_invalid"),
        ("SPLUNK_AUTH_FAILED", "splunk_auth_failed"),
        ("SPLUNK_CONNECTION_FAILED", "splunk_connection_failed"),
        ("CRIBL_CONNECTION_FAILED", "cribl_connection_failed"),
        ("REACT_LOOP_FAILED", "react_loop_failed"),
        ("UNKNOWN", "unknown"),
    ])
    def test_enum_member_exists(self, member, value):
        ft = FailureType[member]
        assert ft.value == value

    def test_failure_type_is_str_enum(self):
        """FailureType inherits from str so members are directly usable as strings."""
        assert isinstance(FailureType.UNKNOWN, str)
        assert FailureType.UNKNOWN == "unknown"

    def test_total_member_count(self):
        """Guard against accidentally adding or removing members without updating tests."""
        assert len(FailureType) == 14


# ---------------------------------------------------------------------------
# 2. RecoveryAction enum — spot-checks and str behaviour
# ---------------------------------------------------------------------------

class TestRecoveryActionEnum:

    def test_recovery_action_is_str(self):
        assert isinstance(RecoveryAction.RETRY_BROADER, str)
        assert RecoveryAction.RETRY_BROADER == "retry_broader"

    def test_none_action_exists(self):
        assert RecoveryAction.NONE.value == "none"

    def test_total_member_count(self):
        assert len(RecoveryAction) == 9


# ---------------------------------------------------------------------------
# 3. FailureReport dataclass construction and defaults
# ---------------------------------------------------------------------------

class TestFailureReport:

    def test_minimal_construction(self):
        report = FailureReport(failure_type=FailureType.UNKNOWN)
        assert report.failure_type is FailureType.UNKNOWN
        assert report.severity == "medium"
        assert report.message == ""
        assert report.recovery_actions == []
        assert report.context == {}

    def test_full_construction(self):
        actions = [RecoveryAction.RETRY_BROADER, RecoveryAction.ADMIT_UNCERTAINTY]
        ctx = {"intent": "spl_help"}
        report = FailureReport(
            failure_type=FailureType.LLM_TIMEOUT,
            severity="high",
            message="timed out",
            recovery_actions=actions,
            context=ctx,
        )
        assert report.failure_type is FailureType.LLM_TIMEOUT
        assert report.severity == "high"
        assert report.message == "timed out"
        assert report.recovery_actions == actions
        assert report.context == ctx

    def test_default_mutable_fields_are_independent(self):
        """Each instance should get its own list/dict, not a shared mutable."""
        r1 = FailureReport(failure_type=FailureType.UNKNOWN)
        r2 = FailureReport(failure_type=FailureType.UNKNOWN)
        r1.recovery_actions.append(RecoveryAction.NONE)
        r1.context["key"] = "value"
        assert r2.recovery_actions == []
        assert r2.context == {}


# ---------------------------------------------------------------------------
# 4. _classify_by_type — isinstance-based classification
# ---------------------------------------------------------------------------

class TestClassifyByType:
    """Direct tests for the private _classify_by_type helper."""

    def test_timeout_error_returns_llm_timeout(self):
        exc = TimeoutError("Request to /v1/chat/completions timed out after 120s")
        report = _classify_by_type(exc, "TimeoutError", str(exc).lower(), {})
        assert report is not None
        assert report.failure_type is FailureType.LLM_TIMEOUT
        assert report.severity == "medium"
        assert RecoveryAction.USE_CACHE in report.recovery_actions
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions

    def test_connection_error_generic(self):
        exc = ConnectionError("Connection refused: localhost:11434")
        report = _classify_by_type(exc, "ConnectionError", str(exc).lower(), {})
        assert report is not None
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "high"

    def test_connection_error_with_splunk_keyword(self):
        exc = ConnectionError("Failed to connect to Splunk REST API on port 8089")
        report = _classify_by_type(exc, "ConnectionError", str(exc).lower(), {})
        assert report is not None
        assert report.failure_type is FailureType.SPLUNK_CONNECTION_FAILED
        assert report.severity == "medium"
        assert RecoveryAction.SKIP_TOOL in report.recovery_actions
        assert RecoveryAction.FALLBACK_DOCS in report.recovery_actions

    def test_os_error_treated_like_connection_error(self):
        """OSError is in the isinstance check alongside ConnectionError."""
        exc = OSError("[Errno 111] Connection refused")
        report = _classify_by_type(exc, "OSError", str(exc).lower(), {})
        assert report is not None
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "high"

    def test_os_error_with_splunk_routes_to_splunk(self):
        exc = OSError("Splunk management port 8089: Network is unreachable")
        report = _classify_by_type(exc, "OSError", str(exc).lower(), {})
        assert report.failure_type is FailureType.SPLUNK_CONNECTION_FAILED

    def test_runtime_error_with_model_keyword(self):
        exc = RuntimeError("model 'llama3:70b' not loaded — VRAM exhausted")
        report = _classify_by_type(exc, "RuntimeError", str(exc).lower(), {})
        assert report is not None
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "critical"
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions

    def test_runtime_error_without_model_returns_none(self):
        """RuntimeError without 'model' is not caught here; falls through."""
        exc = RuntimeError("something else broke entirely")
        report = _classify_by_type(exc, "RuntimeError", str(exc).lower(), {})
        assert report is None

    def test_value_error_returns_none(self):
        """ValueError is not handled by _classify_by_type at all."""
        exc = ValueError("invalid literal for int()")
        report = _classify_by_type(exc, "ValueError", str(exc).lower(), {})
        assert report is None

    def test_context_is_forwarded(self):
        ctx = {"intent": "spl_generate", "profile": "admin"}
        exc = TimeoutError("slow")
        report = _classify_by_type(exc, "TimeoutError", str(exc).lower(), ctx)
        assert report.context is ctx


# ---------------------------------------------------------------------------
# 5. _classify_by_message — string-pattern classification
# ---------------------------------------------------------------------------

class TestClassifyByMessage:
    """Direct tests for the private _classify_by_message helper."""

    # -- timeout patterns --------------------------------------------------

    def test_timeout_keyword(self):
        exc = ValueError("Ollama inference timeout after 60s")
        report = _classify_by_message(str(exc).lower(), "ValueError", exc, {})
        assert report.failure_type is FailureType.LLM_TIMEOUT
        assert report.severity == "medium"
        assert RecoveryAction.USE_CACHE in report.recovery_actions

    def test_timed_out_phrase(self):
        exc = Exception("HTTP request timed out waiting for upstream")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.LLM_TIMEOUT

    # -- connection / refused patterns -------------------------------------

    def test_connection_keyword(self):
        exc = Exception("ECONNRESET: connection reset by peer")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "high"
        assert RecoveryAction.USE_CACHE in report.recovery_actions

    def test_refused_keyword(self):
        exc = Exception("TCP connect refused on 127.0.0.1:11434")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.LLM_ERROR

    # -- authentication / 401 patterns -------------------------------------

    def test_authentication_keyword(self):
        exc = Exception("Splunk authentication failed for user=admin, sessionKey expired")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.SPLUNK_AUTH_FAILED
        assert report.severity == "medium"
        assert RecoveryAction.SKIP_TOOL in report.recovery_actions
        assert RecoveryAction.FALLBACK_DOCS in report.recovery_actions

    def test_401_status_code(self):
        exc = Exception("HTTP 401 Unauthorized — invalid bearer token")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.SPLUNK_AUTH_FAILED

    # -- model not found ---------------------------------------------------

    def test_model_not_found(self):
        exc = Exception("Error: model 'gpt-4-turbo' not found on this server")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "critical"
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions

    # -- tool failures -----------------------------------------------------

    def test_tool_failed_keyword(self):
        exc = Exception("Agentic tool 'splunk_search' failed with exit code 1")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.TOOL_FAILED
        assert RecoveryAction.SKIP_TOOL in report.recovery_actions
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions

    def test_tool_error_keyword(self):
        exc = Exception("tool returned error: invalid search command")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.TOOL_FAILED

    def test_tool_timeout_keyword(self):
        exc = Exception("tool execution timeout after 30 seconds")
        # Note: "timeout" matches the timeout branch first, so this is LLM_TIMEOUT
        # because the timeout check comes before the tool check in _classify_by_message.
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.LLM_TIMEOUT

    # -- cribl patterns ----------------------------------------------------

    def test_cribl_keyword(self):
        exc = Exception("Cribl Stream API returned 503 Service Unavailable")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.CRIBL_CONNECTION_FAILED
        assert report.severity == "medium"
        assert RecoveryAction.FALLBACK_DOCS in report.recovery_actions
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions

    # -- chroma / vector store patterns ------------------------------------

    def test_chroma_keyword(self):
        exc = Exception("chromadb.errors.InvalidCollectionException: collection 'spl_docs' not found")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.RETRIEVAL_EMPTY
        assert RecoveryAction.RETRY_BROADER in report.recovery_actions

    def test_vector_keyword(self):
        exc = Exception("vector store index corrupted, rebuild required")
        report = _classify_by_message(str(exc).lower(), "Exception", exc, {})
        assert report.failure_type is FailureType.RETRIEVAL_EMPTY

    # -- unknown fallback --------------------------------------------------

    def test_generic_unknown_fallback(self):
        exc = KeyError("missing_field")
        report = _classify_by_message(str(exc).lower(), "KeyError", exc, {})
        assert report.failure_type is FailureType.UNKNOWN
        assert report.severity == "medium"
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions
        assert "KeyError" in report.message

    def test_unknown_includes_intent_from_context(self):
        """The UNKNOWN path logs the intent from context (tested indirectly via message format)."""
        ctx = {"intent": "spl_generate"}
        exc = ArithmeticError("division by zero in scoring")
        report = _classify_by_message(str(exc).lower(), "ArithmeticError", exc, ctx)
        assert report.failure_type is FailureType.UNKNOWN
        assert report.context == ctx


# ---------------------------------------------------------------------------
# 6. categorize_failure — end-to-end integration through both classifiers
# ---------------------------------------------------------------------------

class TestCategorizeFailureEndToEnd:
    """High-level tests that exercise the full categorize_failure dispatch."""

    def test_timeout_error_production_message(self):
        """Real Ollama timeout message."""
        report = categorize_failure(
            TimeoutError("Request to POST http://ollama:11434/api/chat timed out after 120.0s")
        )
        assert report.failure_type is FailureType.LLM_TIMEOUT
        assert "timed out" in report.message.lower()

    def test_connection_error_splunk_rest_api(self):
        """Real Splunk REST connection failure."""
        report = categorize_failure(
            ConnectionError("HTTPSConnectionPool(host='splunk-hf', port=8089): "
                            "Max retries exceeded — Splunk management unavailable")
        )
        assert report.failure_type is FailureType.SPLUNK_CONNECTION_FAILED

    def test_connection_error_ollama(self):
        """Connection error to Ollama (no 'splunk' keyword)."""
        report = categorize_failure(
            ConnectionError("HTTPConnectionPool(host='ollama', port=11434): "
                            "Max retries exceeded with url: /api/chat")
        )
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "high"

    def test_runtime_error_model_not_loaded(self):
        """RuntimeError with 'model' keyword -> critical LLM_ERROR."""
        report = categorize_failure(
            RuntimeError("model 'mixtral:8x22b' requires 96 GB VRAM, only 24 GB available")
        )
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "critical"

    def test_value_error_with_timeout_in_message(self):
        """ValueError falls through _classify_by_type, caught by 'timeout' message pattern."""
        report = categorize_failure(ValueError("read timeout on socket"))
        assert report.failure_type is FailureType.LLM_TIMEOUT

    def test_exception_with_401_in_message(self):
        """Generic exception with '401' triggers auth classification."""
        report = categorize_failure(Exception("Splunk REST returned 401 — session expired"))
        assert report.failure_type is FailureType.SPLUNK_AUTH_FAILED

    def test_key_error_falls_to_unknown(self):
        """KeyError with no matching keywords -> UNKNOWN."""
        report = categorize_failure(KeyError("user_profile"))
        assert report.failure_type is FailureType.UNKNOWN
        assert "KeyError" in report.message

    def test_none_context_becomes_empty_dict(self):
        report = categorize_failure(TimeoutError("oops"), context=None)
        assert report.context == {}

    def test_default_context_when_omitted(self):
        report = categorize_failure(TimeoutError("oops"))
        assert report.context == {}

    def test_context_dict_propagated_through_type_branch(self):
        ctx = {"intent": "spl_generate", "profile": "admin", "chunks_found": 0}
        report = categorize_failure(TimeoutError("slow"), context=ctx)
        assert report.context is ctx

    def test_context_dict_propagated_through_message_branch(self):
        ctx = {"intent": "general_qa"}
        report = categorize_failure(Exception("cribl edge node unreachable"), context=ctx)
        assert report.context is ctx
        assert report.failure_type is FailureType.CRIBL_CONNECTION_FAILED


# ---------------------------------------------------------------------------
# 7. categorize_failure — recovery actions are always present
# ---------------------------------------------------------------------------

class TestRecoveryActionsPresent:
    """Every FailureReport returned by categorize_failure must have >= 1 recovery action."""

    @pytest.mark.parametrize("exc", [
        TimeoutError("timeout"),
        ConnectionError("refused"),
        ConnectionError("Splunk host down"),
        OSError("network unreachable"),
        RuntimeError("model llama3 not loaded"),
        ValueError("operation timeout reached"),
        Exception("connection reset"),
        Exception("authentication failed"),
        Exception("HTTP 401"),
        Exception("model gpt-4 not found"),
        Exception("tool execution failed"),
        Exception("cribl api error"),
        Exception("chromadb collection missing"),
        Exception("vector store error"),
        KeyError("something_random"),
    ])
    def test_recovery_actions_non_empty(self, exc):
        report = categorize_failure(exc)
        assert len(report.recovery_actions) >= 1, (
            f"No recovery actions for {type(exc).__name__}('{exc}')"
        )


# ---------------------------------------------------------------------------
# 8. Severity levels are correctly assigned per failure category
# ---------------------------------------------------------------------------

class TestSeverityAssignment:
    """Verify the severity string matches expectations for each classification path."""

    def test_timeout_is_medium(self):
        assert categorize_failure(TimeoutError("t")).severity == "medium"

    def test_generic_connection_is_high(self):
        assert categorize_failure(ConnectionError("refused")).severity == "high"

    def test_splunk_connection_is_medium(self):
        assert categorize_failure(ConnectionError("splunk down")).severity == "medium"

    def test_runtime_model_is_critical(self):
        assert categorize_failure(RuntimeError("model not loaded")).severity == "critical"

    def test_auth_failure_is_medium(self):
        assert categorize_failure(Exception("authentication denied")).severity == "medium"

    def test_model_not_found_message_is_critical(self):
        assert categorize_failure(Exception("model gpt-4 not found")).severity == "critical"

    def test_tool_failed_is_medium(self):
        assert categorize_failure(Exception("tool execution failed")).severity == "medium"

    def test_cribl_is_medium(self):
        assert categorize_failure(Exception("cribl unreachable")).severity == "medium"

    def test_chroma_is_medium(self):
        assert categorize_failure(Exception("chroma error")).severity == "medium"

    def test_unknown_is_medium(self):
        assert categorize_failure(KeyError("x")).severity == "medium"


# ---------------------------------------------------------------------------
# 9. categorize_quality_failure — quality-level failures
# ---------------------------------------------------------------------------

class TestCategorizeQualityFailure:

    def test_zero_chunks_returns_retrieval_empty(self):
        report = categorize_quality_failure(chunks_found=0, confidence=0.9, response_length=500)
        assert report is not None
        assert report.failure_type is FailureType.RETRIEVAL_EMPTY
        assert report.severity == "high"
        assert RecoveryAction.RETRY_BROADER in report.recovery_actions
        assert RecoveryAction.RETRY_SIMPLIFIED in report.recovery_actions
        assert RecoveryAction.FALLBACK_DOCS in report.recovery_actions

    def test_sparse_chunks_with_low_confidence(self):
        report = categorize_quality_failure(chunks_found=2, confidence=0.3, response_length=500)
        assert report is not None
        assert report.failure_type is FailureType.RETRIEVAL_SPARSE
        assert report.severity == "medium"
        assert RecoveryAction.RETRY_BROADER in report.recovery_actions
        assert RecoveryAction.ASK_CLARIFICATION in report.recovery_actions
        assert "2" in report.message
        assert "0.30" in report.message

    def test_single_chunk_low_confidence(self):
        """1 chunk + confidence 0.1 satisfies both conditions (< 3 and < 0.4)."""
        report = categorize_quality_failure(chunks_found=1, confidence=0.1, response_length=200)
        assert report is not None
        assert report.failure_type is FailureType.RETRIEVAL_SPARSE

    def test_short_response_returns_llm_empty_response(self):
        report = categorize_quality_failure(chunks_found=5, confidence=0.8, response_length=30)
        assert report is not None
        assert report.failure_type is FailureType.LLM_EMPTY_RESPONSE
        assert report.severity == "medium"
        assert RecoveryAction.RETRY_BROADER in report.recovery_actions
        assert RecoveryAction.ADMIT_UNCERTAINTY in report.recovery_actions

    def test_all_good_returns_none(self):
        result = categorize_quality_failure(chunks_found=5, confidence=0.85, response_length=300)
        assert result is None

    # -- boundary conditions -----------------------------------------------

    def test_boundary_chunks_3_low_confidence_returns_none(self):
        """chunks_found=3 does NOT trigger RETRIEVAL_SPARSE (condition is < 3)."""
        result = categorize_quality_failure(chunks_found=3, confidence=0.1, response_length=200)
        assert result is None

    def test_boundary_confidence_0_4_returns_none(self):
        """confidence=0.4 does NOT trigger RETRIEVAL_SPARSE (condition is < 0.4)."""
        result = categorize_quality_failure(chunks_found=1, confidence=0.4, response_length=200)
        assert result is None

    def test_boundary_response_length_50_returns_none(self):
        """response_length=50 does NOT trigger LLM_EMPTY_RESPONSE (condition is < 50)."""
        result = categorize_quality_failure(chunks_found=5, confidence=0.8, response_length=50)
        assert result is None

    def test_boundary_response_length_49_triggers(self):
        """response_length=49 triggers LLM_EMPTY_RESPONSE."""
        report = categorize_quality_failure(chunks_found=5, confidence=0.8, response_length=49)
        assert report is not None
        assert report.failure_type is FailureType.LLM_EMPTY_RESPONSE

    # -- priority ordering -------------------------------------------------

    def test_zero_chunks_takes_priority_over_short_response(self):
        """chunks_found=0 is checked first, even when response is also short."""
        report = categorize_quality_failure(chunks_found=0, confidence=0.1, response_length=10)
        assert report.failure_type is FailureType.RETRIEVAL_EMPTY

    def test_sparse_takes_priority_over_short_response(self):
        """Sparse retrieval is checked before short-response."""
        report = categorize_quality_failure(chunks_found=1, confidence=0.2, response_length=20)
        assert report.failure_type is FailureType.RETRIEVAL_SPARSE


# ---------------------------------------------------------------------------
# 10. FailureType enum coverage — at least one categorize path per member
# ---------------------------------------------------------------------------

class TestEveryFailureTypeReachable:
    """
    Ensure every FailureType value is produced by at least one classification path.
    Types that are not produced by categorize_failure or categorize_quality_failure
    (TOOL_TIMEOUT, HALLUCINATION_DETECTED, SPL_INVALID, REACT_LOOP_FAILED) are
    verified as constructable in FailureReport directly.
    """

    def test_retrieval_empty_via_quality(self):
        r = categorize_quality_failure(0, 0.5, 200)
        assert r.failure_type is FailureType.RETRIEVAL_EMPTY

    def test_retrieval_sparse_via_quality(self):
        r = categorize_quality_failure(2, 0.3, 200)
        assert r.failure_type is FailureType.RETRIEVAL_SPARSE

    def test_llm_timeout_via_exception(self):
        r = categorize_failure(TimeoutError("t"))
        assert r.failure_type is FailureType.LLM_TIMEOUT

    def test_llm_error_via_connection(self):
        r = categorize_failure(ConnectionError("refused"))
        assert r.failure_type is FailureType.LLM_ERROR

    def test_llm_empty_response_via_quality(self):
        r = categorize_quality_failure(5, 0.8, 10)
        assert r.failure_type is FailureType.LLM_EMPTY_RESPONSE

    def test_tool_failed_via_message(self):
        r = categorize_failure(Exception("tool execution failed"))
        assert r.failure_type is FailureType.TOOL_FAILED

    def test_tool_timeout_constructable(self):
        """TOOL_TIMEOUT is not produced by current classifiers; verify it is constructable."""
        report = FailureReport(failure_type=FailureType.TOOL_TIMEOUT, severity="medium")
        assert report.failure_type is FailureType.TOOL_TIMEOUT

    def test_hallucination_detected_constructable(self):
        """HALLUCINATION_DETECTED is set by other modules; verify it is constructable."""
        report = FailureReport(failure_type=FailureType.HALLUCINATION_DETECTED, severity="high")
        assert report.failure_type is FailureType.HALLUCINATION_DETECTED

    def test_spl_invalid_constructable(self):
        """SPL_INVALID is set by the validator; verify it is constructable."""
        report = FailureReport(failure_type=FailureType.SPL_INVALID, severity="medium")
        assert report.failure_type is FailureType.SPL_INVALID

    def test_splunk_auth_failed_via_message(self):
        r = categorize_failure(Exception("authentication failed"))
        assert r.failure_type is FailureType.SPLUNK_AUTH_FAILED

    def test_splunk_connection_failed_via_type(self):
        r = categorize_failure(ConnectionError("Splunk REST API unreachable"))
        assert r.failure_type is FailureType.SPLUNK_CONNECTION_FAILED

    def test_cribl_connection_failed_via_message(self):
        r = categorize_failure(Exception("cribl edge node error"))
        assert r.failure_type is FailureType.CRIBL_CONNECTION_FAILED

    def test_react_loop_failed_constructable(self):
        """REACT_LOOP_FAILED is set by the agent loop; verify it is constructable."""
        report = FailureReport(failure_type=FailureType.REACT_LOOP_FAILED, severity="high")
        assert report.failure_type is FailureType.REACT_LOOP_FAILED

    def test_unknown_via_unrecognized_exception(self):
        r = categorize_failure(KeyError("nope"))
        assert r.failure_type is FailureType.UNKNOWN


# ---------------------------------------------------------------------------
# 11. Real production exception messages
# ---------------------------------------------------------------------------

class TestRealProductionMessages:
    """
    Tests using exception messages observed in production logs to
    confirm correct classification under realistic conditions.
    """

    def test_ollama_timeout(self):
        report = categorize_failure(
            TimeoutError("Request to POST http://ollama:11434/api/chat timed out (read timeout=120)")
        )
        assert report.failure_type is FailureType.LLM_TIMEOUT

    def test_splunk_sdk_connection_refused(self):
        report = categorize_failure(
            ConnectionError(
                "HTTPSConnectionPool(host='splunk-hf.internal', port=8089): "
                "Max retries exceeded with url: /services/search/jobs "
                "(Caused by Splunk management port unreachable)"
            )
        )
        assert report.failure_type is FailureType.SPLUNK_CONNECTION_FAILED

    def test_chromadb_collection_not_found(self):
        report = categorize_failure(
            Exception("chromadb.errors.InvalidCollectionException: "
                      "Collection spl_docs does not exist.")
        )
        assert report.failure_type is FailureType.RETRIEVAL_EMPTY

    def test_ollama_model_not_pulled(self):
        report = categorize_failure(
            RuntimeError("model 'mistral-nemo:12b' not found, try `ollama pull mistral-nemo:12b`")
        )
        assert report.failure_type is FailureType.LLM_ERROR
        assert report.severity == "critical"

    def test_splunk_session_key_expired(self):
        report = categorize_failure(
            Exception("401 Client Error: Unauthorized for url: "
                      "https://splunk-hf:8089/services/search/jobs — session key expired")
        )
        assert report.failure_type is FailureType.SPLUNK_AUTH_FAILED

    def test_cribl_stream_api_unavailable(self):
        report = categorize_failure(
            Exception("Cribl Stream leader API returned HTTP 503 during pipeline deploy")
        )
        assert report.failure_type is FailureType.CRIBL_CONNECTION_FAILED

    def test_react_tool_execution_error(self):
        report = categorize_failure(
            Exception("ReAct tool 'splunk_search' returned error: search job failed")
        )
        assert report.failure_type is FailureType.TOOL_FAILED

    def test_generic_python_attribute_error(self):
        report = categorize_failure(
            AttributeError("'NoneType' object has no attribute 'encode'")
        )
        assert report.failure_type is FailureType.UNKNOWN
        assert "AttributeError" in report.message

    def test_vector_store_dimension_mismatch(self):
        report = categorize_failure(
            Exception("vector dimension mismatch: expected 1536, got 768")
        )
        assert report.failure_type is FailureType.RETRIEVAL_EMPTY
