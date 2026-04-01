import contextvars
import json
import logging
import logging.handlers
import os
import time
import re
import uuid
from typing import Optional

# ---------------------------------------------------------------------------
# Request context — async-safe via contextvars
# ---------------------------------------------------------------------------

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")
_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("session_id", default="")

logger = logging.getLogger(__name__)


def set_request_context(
    request_id: Optional[str] = None,
    user_id: str = "",
    session_id: str = "",
) -> str:
    """
    Set request-scoped context for structured logging.

    Call at the start of each message handler invocation.
    Returns the request_id (generated if not provided).
    """
    rid = request_id or uuid.uuid4().hex[:12]
    _request_id.set(rid)
    if user_id:
        _user_id.set(user_id)
    if session_id:
        _session_id.set(session_id)
    return rid


def get_request_id() -> str:
    """Return current request correlation ID."""
    return _request_id.get("")


def clear_request_context():
    """Clear request context after handling completes."""
    _request_id.set("")
    _user_id.set("")
    _session_id.set("")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

class KeyValueFormatter(logging.Formatter):
    """Formatter that omits empty fields and keeps key=value style."""

    def __init__(self, app_name: str):
        super().__init__(datefmt="%Y-%m-%dT%H:%M:%S")
        self.app_name = app_name
        self.converter = time.gmtime  # UTC timestamps

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        message = record.getMessage()
        status = getattr(record, "status", None)
        result = getattr(record, "result", None)

        # If status/result missing, try to extract from HTTP-style message
        if (status in (None, "", [])) or (result in (None, "", [])):
            match = re.search(r'HTTP/1\.1\s+(\d{3})\s+([A-Za-z]+)', message)
            if match:
                if not status:
                    status = match.group(1)
                if not result:
                    result = match.group(2)
        parts = [
            f"{ts}.{int(record.msecs):03d}Z",
            f"level={record.levelname}",
            f"app={getattr(record, 'app', self.app_name)}",
            f"function={record.funcName}",
        ]

        # Inject request context if available
        rid = _request_id.get("")
        if rid:
            parts.append(f"request_id={rid}")
        uid = _user_id.get("")
        if uid:
            parts.append(f"user={uid}")

        if status not in (None, "", []):
            parts.append(f"status={status}")
        if result not in (None, "", []):
            parts.append(f"result={result}")

        # Include structured extra fields from logger.info("msg", extra={...})
        extra_fields = getattr(record, "structured", None)
        if extra_fields and isinstance(extra_fields, dict):
            for k, v in extra_fields.items():
                if v is not None and v != "":
                    parts.append(f"{k}={v}")

        parts.append(f'msg="{message}"')
        return " ".join(parts)


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for centralized logging (ELK, Splunk, etc.)."""

    def __init__(self, app_name: str):
        super().__init__()
        self.app_name = app_name
        self.converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", self.converter(record.created))
                         + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "app": getattr(record, "app", self.app_name),
            "logger": record.name,
            "function": record.funcName,
            "message": record.getMessage(),
        }

        # Request context
        rid = _request_id.get("")
        if rid:
            entry["request_id"] = rid
        uid = _user_id.get("")
        if uid:
            entry["user_id"] = uid
        sid = _session_id.get("")
        if sid:
            entry["session_id"] = sid

        # Structured extra fields
        extra_fields = getattr(record, "structured", None)
        if extra_fields and isinstance(extra_fields, dict):
            entry.update(extra_fields)

        # Exception info
        if record.exc_info and record.exc_info[1]:
            entry["error"] = str(record.exc_info[1])
            entry["error_type"] = type(record.exc_info[1]).__name__

        return json.dumps(entry, default=str)


# ---------------------------------------------------------------------------
# Latency tracker — lightweight timing context manager
# ---------------------------------------------------------------------------

def structured_log(
    logger_instance: logging.Logger,
    level: int,
    tag: str,
    message: str,
    **fields,
) -> None:
    """
    Emit a structured log line with a pipeline tag and key-value fields.

    Usage:
        structured_log(logger, logging.INFO, "ROUTE", "Query routed",
                       intent="spl_help", profile="general", latency_ms=12)

    Produces (key-value mode):
        ... [ROUTE] msg="Query routed" intent=spl_help profile=general latency_ms=12

    In JSON mode, the fields are merged into the JSON object.
    """
    # Filter out None values
    clean_fields = {k: v for k, v in fields.items() if v is not None}
    logger_instance.log(
        level,
        "[%s] %s",
        tag,
        message,
        extra={"structured": clean_fields},
    )


class LatencyTracker:
    """Track latency of pipeline components."""

    def __init__(self):
        self._timings: dict = {}
        self._start_times: dict = {}

    def start(self, component: str):
        """Start timing a component."""
        self._start_times[component] = time.monotonic()

    def stop(self, component: str) -> float:
        """Stop timing and return elapsed milliseconds."""
        start = self._start_times.pop(component, None)
        if start is None:
            return 0.0
        elapsed_ms = (time.monotonic() - start) * 1000
        self._timings[component] = elapsed_ms
        return elapsed_ms

    def get(self, component: str) -> float:
        """Get recorded latency for a component in ms."""
        return self._timings.get(component, 0.0)

    def to_dict(self) -> dict:
        """Return all timings as a dict."""
        return dict(self._timings)

    def summary(self) -> str:
        """Human-readable summary of all tracked latencies."""
        if not self._timings:
            return ""
        parts = [f"{k}={v:.0f}ms" for k, v in self._timings.items()]
        return ", ".join(parts)


# ---------------------------------------------------------------------------
# PII Redaction Filter
# ---------------------------------------------------------------------------

class PIIRedactionFilter(logging.Filter):
    """Scrub personally identifiable information from log messages.

    Redacted patterns:
    - Email addresses      -> [REDACTED_EMAIL]
    - SSNs (XXX-XX-XXXX)   -> [REDACTED_SSN]
    - Credit card numbers   -> [REDACTED_CARD]
    - API keys / tokens     -> [REDACTED_KEY]
    """

    # Compiled patterns (order matters — more specific first)
    _PATTERNS = [
        # SSN: exactly 3-2-4 digits with dashes (word-bounded to avoid matching other dash-separated numbers)
        (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[REDACTED_SSN]'),
        # Credit card: 13-19 digit sequences (with optional spaces/dashes between groups)
        (re.compile(r'\b(?:\d[ -]*?){13,19}\b'), '[REDACTED_CARD]'),
        # API keys: obsai_*, sk-*, Bearer tokens
        (re.compile(r'\b(obsai_[A-Za-z0-9_\-]{8,})\b'), '[REDACTED_KEY]'),
        (re.compile(r'\b(sk-[A-Za-z0-9_\-]{8,})\b'), '[REDACTED_KEY]'),
        (re.compile(r'(Bearer\s+[A-Za-z0-9_\-\.]{8,})'), '[REDACTED_KEY]'),
        # Email addresses (must come after API key patterns to avoid partial matches)
        (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b'), '[REDACTED_EMAIL]'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact PII from the log record message and args."""
        if record.args:
            # Format the message with args first, then redact
            try:
                record.msg = record.getMessage()
                record.args = None
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass
        record.msg = self._redact(str(record.msg))
        return True

    def _redact(self, text: str) -> str:
        for pattern, replacement in self._PATTERNS:
            text = pattern.sub(replacement, text)
        return text


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_current_log_level: str = "INFO"


def set_log_level(level: str) -> str:
    """
    Dynamically change the log level at runtime.

    Returns the new effective level name.
    """
    global _current_log_level
    log_level = getattr(logging, level.upper(), None)
    if log_level is None:
        return _current_log_level
    _current_log_level = level.upper()
    root = logging.getLogger()
    root.setLevel(log_level)
    for name, logger_obj in logging.root.manager.loggerDict.items():
        if isinstance(logger_obj, logging.Logger):
            logger_obj.setLevel(log_level)
    return _current_log_level


def get_log_level() -> str:
    """Return the current effective log level."""
    return _current_log_level


def setup_logging(app_name: str = "chainlit", level: str = "INFO") -> logging.Logger:
    """
    Configure a consistent logging format across the project.

    Uses JSON format if LOG_FORMAT=json env var is set, otherwise key=value.
    """
    global _current_log_level
    log_level = getattr(logging, level.upper(), logging.INFO)
    _current_log_level = level.upper()
    use_json = os.getenv("LOG_FORMAT", "").lower() == "json"

    # Inject default app into every record
    factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = factory(*args, **kwargs)
        record.app = app_name
        return record

    logging.setLogRecordFactory(record_factory)

    formatter: logging.Formatter
    if use_json:
        formatter = JSONFormatter(app_name)
    else:
        formatter = KeyValueFormatter(app_name)

    # PII redaction filter — applied to all handlers
    pii_filter = PIIRedactionFilter()

    # Configure root to avoid duplicate mixed formats
    root = logging.getLogger()
    root.setLevel(log_level)
    for h in list(root.handlers):
        root.removeHandler(h)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(pii_filter)
    root.addHandler(stream)

    # Time-based rotating file handler — daily rotation, 30-day retention
    # Always JSON format for machine-parseable log files
    log_dir = os.getenv("LOG_DIR", "/app/data/logs")
    log_retention_days = int(os.getenv("LOG_RETENTION_DAYS", "30"))
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            when="midnight",
            interval=1,
            backupCount=log_retention_days,
            encoding="utf-8",
            utc=True,
        )
        file_handler.suffix = "%Y-%m-%d"  # app.log.2026-03-18
        file_handler.setFormatter(JSONFormatter(app_name))
        file_handler.setLevel(log_level)
        file_handler.addFilter(pii_filter)
        # Compress rotated logs to save disk space
        _original_rotator = file_handler.rotator

        def _compress_rotated_log(source, destination):
            """Compress rotated log files with gzip."""
            import gzip
            import shutil
            if _original_rotator:
                _original_rotator(source, destination)
            else:
                shutil.move(source, destination)
            # Compress the rotated file
            try:
                with open(destination, 'rb') as f_in:
                    with gzip.open(destination + '.gz', 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(destination)
            except Exception as _exc:  # broad catch — resilience against all failures
                pass  # Keep uncompressed if gzip fails

        file_handler.rotator = _compress_rotated_log
        file_handler.namer = lambda name: name  # Keep default naming
        root.addHandler(file_handler)
    except OSError:
        # If the log directory can't be created (e.g. read-only fs), skip
        # file logging silently — console output is still active.
        pass

    # Force existing named loggers to propagate
    for name, logger_obj in logging.root.manager.loggerDict.items():
        if isinstance(logger_obj, logging.Logger):
            logger_obj.handlers.clear()
            logger_obj.propagate = True

    logger = logging.getLogger(app_name)
    logger.setLevel(log_level)
    logger.propagate = True
    return logger
