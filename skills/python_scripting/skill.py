"""
Python Scripting Skill — Analyze, generate, improve, and explain Python scripts.

Provides static analysis for common anti-patterns, template-based generation
with proper structure, and function-by-function explanation.
"""
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Script Templates
# ---------------------------------------------------------------------------

PYTHON_TEMPLATES: Dict[str, str] = {
    "cli_tool": '''#!/usr/bin/env python3
"""CLI Tool Template — with argument parsing, logging, and error handling."""

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="CLI Tool Description",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -i input.txt -o output.txt
  %(prog)s --verbose -i data.csv
        """,
    )
    parser.add_argument("-i", "--input", type=Path, required=True, help="Input file path")
    parser.add_argument("-o", "--output", type=Path, help="Output file path (default: stdout)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    return parser.parse_args()


def process(input_path: Path, output_path: Path | None = None, dry_run: bool = False) -> int:
    """Main processing logic. Returns exit code."""
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return 1

    logger.info("Processing: %s", input_path)

    # TODO: Add your processing logic here
    data = input_path.read_text()
    result = data  # Transform data

    if dry_run:
        logger.info("Dry run — would write %d bytes", len(result))
        return 0

    if output_path:
        output_path.write_text(result)
        logger.info("Output written to: %s", output_path)
    else:
        sys.stdout.write(result)

    return 0


def main() -> None:
    """Entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    try:
        exit_code = process(args.input, args.output, args.dry_run)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception:
        logger.exception("Unhandled error")
        sys.exit(1)


if __name__ == "__main__":
    main()
''',
    "api_client": '''#!/usr/bin/env python3
"""API Client Template — with retry, timeout, and error handling."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class APIClient:
    """Resilient HTTP API client with retries and timeouts."""

    base_url: str
    api_key: str = ""
    timeout: int = 30
    max_retries: int = 3
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(total=self.max_retries, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        if self.api_key:
            self._session.headers["Authorization"] = f"Bearer {self.api_key}"
        self._session.headers["Content-Type"] = "application/json"

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Dict[str, Any]:
        """Make an HTTP request with error handling."""
        url = urljoin(self.base_url, endpoint)
        kwargs.setdefault("timeout", self.timeout)

        start = time.monotonic()
        try:
            resp = self._session.request(method, url, **kwargs)
            elapsed = time.monotonic() - start
            logger.debug("%s %s -> %d (%.2fs)", method.upper(), endpoint, resp.status_code, elapsed)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP %d from %s: %s", exc.response.status_code, endpoint, exc.response.text[:200])
            raise
        except requests.exceptions.ConnectionError:
            logger.error("Connection failed: %s", url)
            raise
        except requests.exceptions.Timeout:
            logger.error("Timeout after %ds: %s", self.timeout, url)
            raise

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        return self._request("POST", endpoint, json=data)

    def put(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        return self._request("PUT", endpoint, json=data)

    def delete(self, endpoint: str) -> Dict[str, Any]:
        return self._request("DELETE", endpoint)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "APIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# Usage example
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    with APIClient(base_url="https://api.example.com", api_key="your-key") as client:
        users = client.get("/users", params={"limit": 10})
        print(f"Found {len(users.get('data', []))} users")
''',
    "data_pipeline": '''#!/usr/bin/env python3
"""Data Pipeline Template — ETL with validation, transformation, and output."""

import csv
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Pipeline configuration."""
    input_path: Path
    output_path: Path
    input_format: str = "csv"   # csv, json, jsonl
    output_format: str = "json"  # csv, json, jsonl
    batch_size: int = 1000
    skip_errors: bool = False


class DataPipeline:
    """Generic ETL data pipeline."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.stats = {"read": 0, "transformed": 0, "errors": 0, "written": 0}

    def extract(self) -> Generator[Dict[str, Any], None, None]:
        """Read records from input source."""
        path = self.config.input_path
        logger.info("Reading from: %s (format: %s)", path, self.config.input_format)

        if self.config.input_format == "csv":
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.stats["read"] += 1
                    yield dict(row)
        elif self.config.input_format == "jsonl":
            with open(path, encoding="utf-8") as f:
                for line in f:
                    self.stats["read"] += 1
                    yield json.loads(line)
        elif self.config.input_format == "json":
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
            for item in items:
                self.stats["read"] += 1
                yield item

    def transform(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transform a single record. Return None to skip."""
        # TODO: Add your transformation logic here
        # Example: clean, validate, enrich
        transformed = {}
        for key, value in record.items():
            clean_key = key.strip().lower().replace(" ", "_")
            clean_value = str(value).strip() if value else ""
            transformed[clean_key] = clean_value

        self.stats["transformed"] += 1
        return transformed

    def load(self, records: List[Dict[str, Any]]) -> None:
        """Write records to output."""
        path = self.config.output_path
        logger.info("Writing %d records to: %s", len(records), path)

        if self.config.output_format == "json":
            path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
        elif self.config.output_format == "jsonl":
            with open(path, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, default=str) + "\\n")
        elif self.config.output_format == "csv":
            if records:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=records[0].keys())
                    writer.writeheader()
                    writer.writerows(records)

        self.stats["written"] = len(records)

    def run(self) -> Dict[str, int]:
        """Execute the full pipeline."""
        logger.info("Pipeline started")
        results: List[Dict[str, Any]] = []

        for record in self.extract():
            try:
                transformed = self.transform(record)
                if transformed:
                    results.append(transformed)
            except Exception as exc:
                self.stats["errors"] += 1
                if not self.config.skip_errors:
                    raise
                logger.warning("Skipping record %d: %s", self.stats["read"], exc)

        self.load(results)
        logger.info("Pipeline complete: %s", self.stats)
        return self.stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = PipelineConfig(
        input_path=Path(sys.argv[1]) if len(sys.argv) > 1 else Path("input.csv"),
        output_path=Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output.json"),
    )
    pipeline = DataPipeline(config)
    stats = pipeline.run()
    print(f"Done: {stats}")
''',
    "fastapi_server": '''#!/usr/bin/env python3
"""FastAPI Server Template — with health checks, middleware, and error handling."""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: float = 0.0

class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    value: float = Field(default=0.0, ge=0)

class ItemResponse(BaseModel):
    id: int
    name: str
    description: str
    value: float


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

_start_time = time.time()
_items: Dict[int, Dict[str, Any]] = {}
_next_id = 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info("Application starting up...")
    # TODO: Initialize DB connections, caches, etc.
    yield
    logger.info("Application shutting down...")
    # TODO: Close connections, flush caches


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="API Server",
    description="FastAPI server template",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware: request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed = (time.monotonic() - start) * 1000
    logger.info("%s %s -> %d (%.1fms)", request.method, request.url.path, response.status_code, elapsed)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(uptime_seconds=round(time.time() - _start_time, 1))


@app.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(item: ItemCreate):
    global _next_id
    item_id = _next_id
    _next_id += 1
    _items[item_id] = {"id": item_id, **item.model_dump()}
    return _items[item_id]


@app.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int):
    if item_id not in _items:
        raise HTTPException(status_code=404, detail="Item not found")
    return _items[item_id]


@app.get("/items", response_model=list[ItemResponse])
async def list_items(limit: int = 100, offset: int = 0):
    items = list(_items.values())
    return items[offset:offset + limit]


@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    if item_id not in _items:
        raise HTTPException(status_code=404, detail="Item not found")
    del _items[item_id]
    return {"status": "deleted", "id": item_id}


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)
''',
    "test_suite": '''#!/usr/bin/env python3
"""Test Suite Template — pytest with fixtures, parameterization, and mocking."""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any


# ---------------------------------------------------------------------------
# The module under test (replace with your actual import)
# ---------------------------------------------------------------------------

class Calculator:
    """Example class to test."""

    def add(self, a: float, b: float) -> float:
        return a + b

    def divide(self, a: float, b: float) -> float:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b

    def fetch_and_compute(self, url: str) -> float:
        """Example of method that calls external service."""
        import requests
        resp = requests.get(url)
        data = resp.json()
        return self.add(data["a"], data["b"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def calc() -> Calculator:
    """Provide a fresh Calculator instance."""
    return Calculator()


@pytest.fixture
def sample_data() -> Dict[str, Any]:
    """Provide sample test data."""
    return {"a": 10, "b": 5, "expected_sum": 15, "expected_div": 2.0}


# ---------------------------------------------------------------------------
# Basic Tests
# ---------------------------------------------------------------------------

class TestCalculatorBasic:
    """Basic functionality tests."""

    def test_add_positive(self, calc: Calculator) -> None:
        assert calc.add(2, 3) == 5

    def test_add_negative(self, calc: Calculator) -> None:
        assert calc.add(-1, -1) == -2

    def test_add_zero(self, calc: Calculator) -> None:
        assert calc.add(0, 0) == 0

    def test_divide_normal(self, calc: Calculator) -> None:
        assert calc.divide(10, 2) == 5.0

    def test_divide_by_zero(self, calc: Calculator) -> None:
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            calc.divide(10, 0)


# ---------------------------------------------------------------------------
# Parameterized Tests
# ---------------------------------------------------------------------------

class TestCalculatorParameterized:
    """Test with multiple inputs using parametrize."""

    @pytest.mark.parametrize("a, b, expected", [
        (1, 1, 2),
        (0, 0, 0),
        (-1, 1, 0),
        (100, 200, 300),
        (0.1, 0.2, pytest.approx(0.3)),
    ])
    def test_add_various(self, calc: Calculator, a: float, b: float, expected: float) -> None:
        assert calc.add(a, b) == expected


# ---------------------------------------------------------------------------
# Tests with Mocking
# ---------------------------------------------------------------------------

class TestCalculatorWithMocks:
    """Tests that mock external dependencies."""

    @patch("requests.get")
    def test_fetch_and_compute(self, mock_get: MagicMock, calc: Calculator) -> None:
        mock_get.return_value.json.return_value = {"a": 3, "b": 7}
        result = calc.fetch_and_compute("http://example.com/data")
        assert result == 10
        mock_get.assert_called_once_with("http://example.com/data")


# ---------------------------------------------------------------------------
# Fixture-based Tests
# ---------------------------------------------------------------------------

class TestWithFixtures:
    """Tests using shared fixtures."""

    def test_with_sample_data(self, calc: Calculator, sample_data: Dict) -> None:
        result = calc.add(sample_data["a"], sample_data["b"])
        assert result == sample_data["expected_sum"]

    def test_divide_with_sample_data(self, calc: Calculator, sample_data: Dict) -> None:
        result = calc.divide(sample_data["a"], sample_data["b"])
        assert result == sample_data["expected_div"]
''',
    "db_migration": '''#!/usr/bin/env python3
"""Database Migration Template — with versioning, rollback support, and safety checks."""

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """A single database migration."""
    version: int
    name: str
    up_sql: str
    down_sql: str


# ---------------------------------------------------------------------------
# Define migrations
# ---------------------------------------------------------------------------

MIGRATIONS: List[Migration] = [
    Migration(
        version=1,
        name="create_users_table",
        up_sql="""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX idx_users_email ON users(email);
        """,
        down_sql="""
            DROP TABLE IF EXISTS users;
        """,
    ),
    Migration(
        version=2,
        name="create_items_table",
        up_sql="""
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(200) NOT NULL,
                value NUMERIC(10, 2) DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX idx_items_user ON items(user_id);
        """,
        down_sql="""
            DROP TABLE IF EXISTS items;
        """,
    ),
    Migration(
        version=3,
        name="add_user_status",
        up_sql="""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
        """,
        down_sql="""
            ALTER TABLE users DROP COLUMN IF EXISTS status;
            ALTER TABLE users DROP COLUMN IF EXISTS updated_at;
        """,
    ),
]


# ---------------------------------------------------------------------------
# Migration runner (database-agnostic interface)
# ---------------------------------------------------------------------------

class MigrationRunner:
    """Run migrations against a database connection."""

    def __init__(self, connection) -> None:
        self.conn = connection
        self._ensure_migration_table()

    def _ensure_migration_table(self) -> None:
        """Create the migration tracking table if it doesn't exist."""
        self._execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                applied_at TIMESTAMP DEFAULT NOW()
            );
        """)

    def _execute(self, sql: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(sql)
        self.conn.commit()

    def get_current_version(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(version) FROM schema_migrations")
        result = cursor.fetchone()
        return result[0] or 0

    def get_applied(self) -> List[int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        return [row[0] for row in cursor.fetchall()]

    def migrate_up(self, target: Optional[int] = None) -> List[str]:
        """Apply pending migrations up to target version."""
        applied = set(self.get_applied())
        target = target or max(m.version for m in MIGRATIONS)
        results = []

        for migration in sorted(MIGRATIONS, key=lambda m: m.version):
            if migration.version in applied:
                continue
            if migration.version > target:
                break

            logger.info("Applying migration %d: %s", migration.version, migration.name)
            try:
                self._execute(migration.up_sql)
                self._execute(
                    f"INSERT INTO schema_migrations (version, name) VALUES ({migration.version}, '{migration.name}')"
                )
                results.append(f"Applied: {migration.version} - {migration.name}")
            except Exception as exc:
                logger.error("Migration %d failed: %s", migration.version, exc)
                raise

        return results or ["No pending migrations"]

    def migrate_down(self, target: int = 0) -> List[str]:
        """Rollback migrations down to target version."""
        applied = set(self.get_applied())
        results = []

        for migration in sorted(MIGRATIONS, key=lambda m: m.version, reverse=True):
            if migration.version not in applied:
                continue
            if migration.version <= target:
                break

            logger.info("Rolling back migration %d: %s", migration.version, migration.name)
            try:
                self._execute(migration.down_sql)
                self._execute(f"DELETE FROM schema_migrations WHERE version = {migration.version}")
                results.append(f"Rolled back: {migration.version} - {migration.name}")
            except Exception as exc:
                logger.error("Rollback %d failed: %s", migration.version, exc)
                raise

        return results or ["Nothing to rollback"]

    def status(self) -> str:
        """Show migration status."""
        applied = set(self.get_applied())
        lines = ["Migration Status:", "=" * 50]
        for m in MIGRATIONS:
            status = "APPLIED" if m.version in applied else "PENDING"
            lines.append(f"  [{status:7s}] {m.version:3d} - {m.name}")
        lines.append(f"\\nCurrent version: {self.get_current_version()}")
        return "\\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Usage: python db_migration.py [up|down|status] [version]
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    logger.info("Migration action: %s", action)
    # TODO: Replace with your actual database connection
    # runner = MigrationRunner(connection)
    # if action == "up": runner.migrate_up()
    # elif action == "down": runner.migrate_down()
    # else: print(runner.status())
''',
    "log_analyzer": r'''#!/usr/bin/env python3
"""Log Analyzer Template — Parse, filter, and aggregate log files."""

import re
import sys
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LogEntry:
    """Parsed log entry."""
    timestamp: Optional[datetime] = None
    level: str = ""
    source: str = ""
    message: str = ""
    raw: str = ""


@dataclass
class AnalysisResult:
    """Log analysis summary."""
    total_lines: int = 0
    parsed_lines: int = 0
    error_count: int = 0
    warning_count: int = 0
    level_distribution: Dict[str, int] = field(default_factory=dict)
    top_errors: List[tuple] = field(default_factory=list)
    hourly_distribution: Dict[str, int] = field(default_factory=dict)
    sources: Dict[str, int] = field(default_factory=dict)


# Common log format patterns
LOG_PATTERNS = [
    # Syslog: Mar  5 12:00:00 host process[pid]: message
    re.compile(r'(?P<timestamp>\w{3}\s+\d+\s+[\d:]+)\s+(?P<source>\S+)\s+\S+:\s+(?P<message>.+)'),
    # ISO format: 2024-01-01 12:00:00 [LEVEL] source: message
    re.compile(r'(?P<timestamp>\d{4}-\d{2}-\d{2}\s+[\d:]+)\s+\[(?P<level>\w+)\]\s+(?P<source>\S+?):\s+(?P<message>.+)'),
    # Apache/Nginx combined log
    re.compile(r'(?P<source>\S+)\s+-\s+-\s+\[(?P<timestamp>[^\]]+)\]\s+"(?P<message>[^"]+)"'),
    # Simple: [LEVEL] message
    re.compile(r'\[(?P<level>\w+)\]\s+(?P<message>.+)'),
]


class LogAnalyzer:
    """Analyze log files for patterns and anomalies."""

    def __init__(self, level_filter: Optional[str] = None, pattern_filter: Optional[str] = None):
        self.level_filter = level_filter.upper() if level_filter else None
        self.pattern_filter = re.compile(pattern_filter) if pattern_filter else None

    def parse_line(self, line: str) -> Optional[LogEntry]:
        """Parse a single log line."""
        for pattern in LOG_PATTERNS:
            match = pattern.match(line.strip())
            if match:
                groups = match.groupdict()
                entry = LogEntry(
                    level=groups.get("level", "INFO").upper(),
                    source=groups.get("source", ""),
                    message=groups.get("message", ""),
                    raw=line.strip(),
                )
                ts_str = groups.get("timestamp", "")
                if ts_str:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%b %d %H:%M:%S", "%d/%b/%Y:%H:%M:%S %z"):
                        try:
                            entry.timestamp = datetime.strptime(ts_str, fmt)
                            break
                        except ValueError:
                            continue
                return entry
        return None

    def read_file(self, path: Path) -> Generator[LogEntry, None, None]:
        """Read and parse a log file."""
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                entry = self.parse_line(line)
                if entry:
                    if self.level_filter and entry.level != self.level_filter:
                        continue
                    if self.pattern_filter and not self.pattern_filter.search(entry.message):
                        continue
                    yield entry

    def analyze(self, path: Path) -> AnalysisResult:
        """Perform full analysis on a log file."""
        result = AnalysisResult()
        error_messages: Counter = Counter()
        hourly: Counter = Counter()
        sources: Counter = Counter()
        levels: Counter = Counter()

        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                result.total_lines += 1
                entry = self.parse_line(line)
                if not entry:
                    continue

                result.parsed_lines += 1
                levels[entry.level] += 1
                sources[entry.source] += 1

                if entry.level in ("ERROR", "FATAL", "CRITICAL"):
                    result.error_count += 1
                    error_messages[entry.message[:100]] += 1
                elif entry.level == "WARNING":
                    result.warning_count += 1

                if entry.timestamp:
                    hour = entry.timestamp.strftime("%H:00")
                    hourly[hour] += 1

        result.level_distribution = dict(levels.most_common())
        result.top_errors = error_messages.most_common(10)
        result.hourly_distribution = dict(sorted(hourly.items()))
        result.sources = dict(sources.most_common(10))
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/var/log/syslog")

    analyzer = LogAnalyzer()
    result = analyzer.analyze(log_path)

    print(f"Total lines: {result.total_lines}")
    print(f"Parsed: {result.parsed_lines}")
    print(f"Errors: {result.error_count} | Warnings: {result.warning_count}")
    print(f"\\nLevel distribution: {result.level_distribution}")
    print(f"\\nTop errors:")
    for msg, count in result.top_errors[:5]:
        print(f"  [{count:4d}] {msg}")
''',
}


# ---------------------------------------------------------------------------
# Python Analysis Checks
# ---------------------------------------------------------------------------

PYTHON_CHECKS = [
    {"pattern": r'except\s*:', "id": "bare_except", "severity": "error", "message": "Bare except clause — catches all exceptions including SystemExit and KeyboardInterrupt", "fix": "Use 'except Exception:' or specific exception types"},
    {"pattern": r'def\s+\w+\([^)]*=\s*(\[\]|\{\}|\bset\(\))', "id": "mutable_default", "severity": "error", "message": "Mutable default argument — shared across all calls", "fix": "Use None as default, create mutable in function body"},
    {"pattern": r'\beval\s*\(', "id": "eval_usage", "severity": "error", "message": "eval() usage — potential code injection vulnerability", "fix": "Use ast.literal_eval() for safe parsing or avoid eval entirely"},
    {"pattern": r'\bexec\s*\(', "id": "exec_usage", "severity": "error", "message": "exec() usage — potential code injection vulnerability", "fix": "Avoid exec(); use importlib or structured approach instead"},
    {"pattern": r'subprocess\..*shell\s*=\s*True', "id": "subprocess_shell", "severity": "warning", "message": "subprocess with shell=True — potential command injection", "fix": "Use shell=False with argument list: subprocess.run(['cmd', 'arg'])"},
    {"pattern": r'import\s+pickle', "id": "pickle_usage", "severity": "warning", "message": "pickle usage — deserialization of untrusted data can execute arbitrary code", "fix": "Use json for data serialization; if pickle needed, validate source"},
    {"pattern": r'logging\.\w+\(f["\']', "id": "fstring_logging", "severity": "info", "message": "f-string in logging call — string formatted even if log level filtered", "fix": "Use % formatting: logging.info('value: %s', val)"},
    {"pattern": r'global\s+\w+', "id": "global_state", "severity": "warning", "message": "Global variable modification — makes code harder to test and reason about", "fix": "Pass state as function arguments or use a class"},
    {"pattern": r'print\(', "id": "print_usage", "severity": "info", "message": "print() in production code — consider using logging instead", "fix": "Use logging.info() for proper log level control"},
    {"pattern": r'#\s*TODO|#\s*FIXME|#\s*HACK|#\s*XXX', "id": "todo_comment", "severity": "info", "message": "TODO/FIXME comment found — outstanding work item", "fix": "Track in issue tracker and resolve"},
    {"pattern": r'time\.sleep\(', "id": "sleep_usage", "severity": "info", "message": "time.sleep() — blocking call, may indicate polling pattern", "fix": "Consider async/await, events, or callbacks instead"},
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def python_analyze_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Analyze a Python script for common issues and anti-patterns."""
    script = kwargs.get("script_content", "") or kwargs.get("content", "")
    if not script:
        code_match = re.search(r'```(?:python|py)?\s*\n(.*?)```', user_input, re.DOTALL)
        script = code_match.group(1) if code_match else user_input

    if not script.strip():
        return {"success": False, "output": "No Python script found to analyze."}

    issues: List[Dict[str, str]] = []
    lines = script.split('\n')

    # Check for main guard
    if 'def main' in script and '__name__' not in script:
        issues.append({"severity": "warning", "line": 0, "message": "Has main() but missing if __name__ == '__main__' guard", "fix": "Add: if __name__ == '__main__': main()"})

    # Check for logging setup
    if 'import logging' not in script and len(lines) > 30:
        issues.append({"severity": "info", "line": 0, "message": "No logging module imported — using print for output", "fix": "Import logging and use structured logging"})

    # Check for type hints
    func_defs = re.findall(r'def\s+\w+\(([^)]*)\)', script)
    funcs_without_hints = sum(1 for f in func_defs if f and ':' not in f)
    if funcs_without_hints > 2:
        issues.append({"severity": "info", "line": 0, "message": f"{funcs_without_hints} functions without type hints", "fix": "Add type hints for better documentation and IDE support"})

    # Line-by-line checks
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        for check in PYTHON_CHECKS:
            if re.search(check["pattern"], stripped):
                issues.append({
                    "severity": check["severity"],
                    "line": i,
                    "message": check["message"],
                    "fix": check["fix"],
                })

    # Summary
    error_count = sum(1 for i in issues if i["severity"] == "error")
    warn_count = sum(1 for i in issues if i["severity"] == "warning")
    info_count = sum(1 for i in issues if i["severity"] == "info")

    output_lines = [f"## Python Script Analysis\n"]
    output_lines.append(f"**{len(lines)} lines** | {error_count} errors | {warn_count} warnings | {info_count} info\n")

    if not issues:
        output_lines.append("Script looks clean! No issues detected.")
    else:
        for issue in sorted(issues, key=lambda x: {"error": 0, "warning": 1, "info": 2}[x["severity"]]):
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}[issue["severity"]]
            line_ref = f"Line {issue['line']}: " if issue.get("line") else ""
            output_lines.append(f"- {icon} {line_ref}{issue['message']}")
            output_lines.append(f"  Fix: {issue['fix']}")

    return {"success": True, "output": "\n".join(output_lines), "issues": issues}


def _get_llm():
    """Get the LLM instance for script generation."""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))
        from llm_utils import LLM
        return LLM
    except Exception:
        return None


def _find_best_python_template(description: str) -> Optional[str]:
    """Find best matching python template by keyword."""
    lower = description.lower()
    keyword_map = {
        "cli": "cli_tool", "command line": "cli_tool", "argparse": "cli_tool",
        "api client": "api_client", "http client": "api_client", "requests": "api_client",
        "data pipeline": "data_pipeline", "etl": "data_pipeline", "csv": "data_pipeline",
        "fastapi": "fastapi_server", "rest api": "fastapi_server", "web server": "fastapi_server",
        "test": "test_suite", "pytest": "test_suite", "unittest": "test_suite",
        "migration": "db_migration", "database": "db_migration", "schema": "db_migration",
        "log analy": "log_analyzer", "parse log": "log_analyzer", "log pars": "log_analyzer",
    }
    for keyword, tpl in keyword_map.items():
        if keyword in lower:
            return tpl
    return None


def python_generate_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Generate a Python script from description using LLM, with template fallback."""
    template_name = kwargs.get("template", "")
    description = kwargs.get("description", user_input)

    if template_name and template_name != "custom" and template_name in PYTHON_TEMPLATES:
        return {"success": True, "output": PYTHON_TEMPLATES[template_name], "template_used": template_name}

    ref_tpl_name = _find_best_python_template(description)
    ref_tpl = PYTHON_TEMPLATES.get(ref_tpl_name or "cli_tool", "")

    llm = _get_llm()
    if llm is not None:
        try:
            prompt = f"""You are an expert Python developer. Generate a complete, production-ready Python script based on the user's request.

Requirements:
- Output ONLY the Python code — no markdown fences, no explanation
- Start with #!/usr/bin/env python3
- Use proper imports, type hints, and docstrings
- Include if __name__ == '__main__' guard
- Add error handling with try/except
- Use logging instead of print for operational output
- Add # <-- Change: markers for values the user should customize

Reference template for style (adapt to the user's actual request):
```python
{ref_tpl[:1500]}
```

User request: {description}

Generate the complete script now:"""
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[-1].strip() == "```":
                    lines = lines[1:-1]
                else:
                    lines = lines[1:]
                content = "\n".join(lines)
            if not content.startswith("#!"):
                content = "#!/usr/bin/env python3\n" + content
            return {
                "success": True,
                "output": content,
                "template_used": f"llm_generated (ref: {ref_tpl_name or 'none'})",
                "note": "Generated by LLM. Review and customize before use.",
            }
        except Exception as exc:
            logger.warning("LLM generation failed for python script: %s", exc)

    if ref_tpl_name:
        return {"success": True, "output": PYTHON_TEMPLATES[ref_tpl_name], "template_used": ref_tpl_name}

    return {"success": True, "output": PYTHON_TEMPLATES["cli_tool"], "template_used": "cli_tool", "note": "LLM unavailable. Returned CLI tool template."}


def python_improve_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Suggest improvements for a Python script."""
    script = kwargs.get("script_content", "") or kwargs.get("content", "")
    if not script:
        code_match = re.search(r'```(?:python|py)?\s*\n(.*?)```', user_input, re.DOTALL)
        script = code_match.group(1) if code_match else ""

    if not script.strip():
        return {"success": False, "output": "No Python script found to improve."}

    suggestions: List[str] = []

    if '__name__' not in script and 'def ' in script:
        suggestions.append("**Add main guard:** `if __name__ == '__main__': main()` to allow importing without execution")

    if 'import logging' not in script and len(script.split('\n')) > 20:
        suggestions.append("**Add logging:** Replace print() with logging for structured, configurable output")

    if 'def ' in script:
        funcs = re.findall(r'def\s+(\w+)\(([^)]*)\)', script)
        no_hints = [f for f, args in funcs if args and ':' not in args]
        if no_hints:
            suggestions.append(f"**Add type hints:** Functions without hints: {', '.join(no_hints[:5])}")

    if 'except:' in script or 'except Exception:' in script:
        suggestions.append("**Specific exceptions:** Catch specific exception types instead of broad Exception")

    if 'os.path' in script and 'pathlib' not in script:
        suggestions.append("**Use pathlib:** Replace os.path with pathlib.Path for cleaner file operations")

    if 'open(' in script and 'with ' not in script:
        suggestions.append("**Use context managers:** Wrap file operations in `with open(...) as f:` blocks")

    func_count = len(re.findall(r'^def\s+', script, re.MULTILINE))
    docstring_count = len(re.findall(r'"""', script))
    if func_count > 3 and docstring_count < func_count:
        suggestions.append(f"**Add docstrings:** {func_count} functions but only ~{docstring_count // 2} have docstrings")

    if not suggestions:
        return {"success": True, "output": "Script follows good practices. No major improvements needed."}

    output = "## Suggested Improvements\n\n" + "\n".join(f"- {s}" for s in suggestions)
    return {"success": True, "output": output}


def python_explain_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Explain a Python script's structure and logic."""
    script = kwargs.get("script_content", "") or kwargs.get("content", "")
    if not script:
        code_match = re.search(r'```(?:python|py)?\s*\n(.*?)```', user_input, re.DOTALL)
        script = code_match.group(1) if code_match else user_input

    if not script.strip():
        return {"success": False, "output": "No Python script found to explain."}

    explanations: List[str] = ["## Script Explanation\n"]

    # Imports
    imports = re.findall(r'^(?:from\s+\S+\s+)?import\s+.+', script, re.MULTILINE)
    if imports:
        explanations.append(f"### Imports ({len(imports)})")
        for imp in imports[:15]:
            explanations.append(f"- `{imp.strip()}`")
        explanations.append("")

    # Classes
    classes = re.findall(r'^class\s+(\w+)(?:\(([^)]*)\))?:', script, re.MULTILINE)
    if classes:
        explanations.append(f"### Classes ({len(classes)})")
        for name, bases in classes:
            base_str = f" (inherits from {bases})" if bases else ""
            explanations.append(f"- **{name}**{base_str}")
        explanations.append("")

    # Functions
    functions = re.findall(r'^(?:    )?def\s+(\w+)\(([^)]*)\)(?:\s*->\s*(\S+))?:', script, re.MULTILINE)
    if functions:
        explanations.append(f"### Functions ({len(functions)})")
        for name, params, return_type in functions:
            ret = f" -> {return_type}" if return_type else ""
            explanations.append(f"- **{name}**({params[:50]}){ret}")
        explanations.append("")

    # Global variables
    globals_found = re.findall(r'^([A-Z][A-Z_0-9]+)\s*=', script, re.MULTILINE)
    if globals_found:
        explanations.append(f"### Constants ({len(globals_found)})")
        for g in globals_found[:10]:
            explanations.append(f"- `{g}`")
        explanations.append("")

    # Entry point
    if '__name__' in script:
        explanations.append("### Entry Point")
        explanations.append("Has `if __name__ == '__main__':` guard — can be imported as module or run directly.")

    return {"success": True, "output": "\n".join(explanations)}
