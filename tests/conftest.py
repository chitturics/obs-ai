"""Shared test fixtures for the Chainlit Splunk Assistant."""
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup — ensure chat_app, shared, and project root are importable
# ---------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "chat_app"))
sys.path.insert(0, os.path.join(project_root, "shared"))
sys.path.insert(0, project_root)

# ---------------------------------------------------------------------------
# Mock external dependencies not available in test environment
# ---------------------------------------------------------------------------
# Chainlit is a runtime UI dependency — mock it so modules that import it
# at the top level (agent_state, response_generator) can load in tests.
if "chainlit" not in sys.modules:
    _cl_mock = MagicMock()
    _cl_mock.user_session = MagicMock()
    sys.modules["chainlit"] = _cl_mock
    sys.modules["chainlit.types"] = MagicMock()
    sys.modules["chainlit.context"] = MagicMock()
    sys.modules["chainlit.input_widget"] = MagicMock()
    sys.modules["chainlit.auth"] = MagicMock()
    sys.modules["chainlit.server"] = MagicMock()
    sys.modules["chainlit.data"] = MagicMock()
    sys.modules["chainlit.data.sql_alchemy"] = MagicMock()
    sys.modules["chainlit.data.storage_clients"] = MagicMock()
    sys.modules["chainlit.data.storage_clients.base"] = MagicMock()

# Mock optional runtime dependencies used by response_generator and others.
# Only mock if the real module cannot be imported.
for _mod_name in ("cache", "ollama_priority", "resilience", "prometheus_metrics"):
    if _mod_name not in sys.modules:
        try:
            __import__(_mod_name)
        except ImportError:
            sys.modules[_mod_name] = MagicMock()



# ---------------------------------------------------------------------------
# Global singleton reset — prevents cross-test pollution
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_global_singletons():
    """Reset module-level singletons that leak state between test modules."""
    yield
    # After each test, reset key singletons to prevent cross-test pollution
    try:
        from chat_app.settings import get_settings
        get_settings.cache_clear()
    except (ImportError, AttributeError):
        pass

    try:
        import chat_app.skill_executor as se
        se._executor = None
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    """Path to the tests/fixtures/ directory."""
    return FIXTURES_DIR


@pytest.fixture
def spl_docs_dir():
    """Path to the spl_docs/ directory with real SPL command docs."""
    return Path(project_root) / "spl_docs"


@pytest.fixture
def project_root_dir():
    """Path to the project root directory."""
    return Path(project_root)


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_spl_queries():
    """20+ realistic SPL queries covering various intents."""
    return [
        # Raw SPL
        'index=main sourcetype=syslog | stats count by host',
        'index=security EventCode=4625 | stats count by src_ip | sort -count',
        'index=network action=blocked | timechart span=1h count by dest_ip',
        '| tstats count WHERE index=main by sourcetype',
        'index=_internal sourcetype=splunkd log_level=ERROR | head 50',
        # With pipe chains
        'index=web | stats avg(response_time) as avg_rt by uri_path | where avg_rt > 5',
        'index=main | rex field=_raw "user=(?<username>\\w+)" | stats count by username',
        'index=firewall | stats sum(bytes) as total_bytes by src_ip dest_ip | sort -total_bytes | head 10',
        # Optimization candidates
        'index=main | table _time host source | sort _time',  # table before sort
        'index=main | sort _time | stats count by host',  # sort before stats
        'index=main | join type=inner src_ip [search index=threat]',  # join
        # tstats
        '| tstats count WHERE index=security by src_ip, action | sort -count',
        '| tstats summariesonly=t count WHERE index=main by sourcetype, host',
        # Subsearch
        'index=main [search index=notable | fields src_ip] | stats count by src_ip',
        # Datamodel
        '| from datamodel:"Authentication" | stats count by user action',
        # Transaction
        'index=web | transaction session_id maxspan=30m | stats avg(duration) as avg_session',
        # Lookup
        'index=main | lookup asset_lookup ip as src_ip OUTPUT asset_name | stats count by asset_name',
        # Eval
        'index=web | eval response_class=case(status<300,"2xx",status<400,"3xx",status<500,"4xx",1=1,"5xx") | stats count by response_class',
        # Rare
        'index=security | rare limit=20 user',
        # Multisearch
        '| multisearch [search index=web] [search index=app] | stats count by index',
    ]


@pytest.fixture
def sample_user_inputs():
    """30+ realistic user questions covering all intent types."""
    return {
        "meta": [
            "who are you?",
            "what can you do?",
            "what are your capabilities?",
        ],
        "spl_optimize": [
            "optimize this: index=main | table _time host | sort _time | stats count by host",
            "can you improve this SPL: index=web | join src_ip [search index=threat]",
        ],
        "spl_explain": [
            "explain this query: index=security | tstats count by src_ip",
            "what does this do: | from datamodel:Authentication | stats count by user",
        ],
        "spl_review": [
            "review this search: index=main | stats count by host | sort -count",
        ],
        "raw_spl": [
            "index=main sourcetype=syslog | stats count by host",
            "| tstats count WHERE index=security by src_ip",
        ],
        "nlp_to_spl": [
            "show me failed login attempts in the last 24 hours",
            "find top 10 hosts by event count",
            "count errors by sourcetype over the last hour",
        ],
        "config_lookup": [
            "show me props.conf for syslog",
            "what are the inputs.conf settings?",
            "show transforms.conf stanzas",
        ],
        "troubleshoot": [
            "my search is slow, how can I fix it?",
            "getting error 'field not found' in my query",
            "search is not returning results",
        ],
        "general_qa": [
            "what is Splunk?",
            "how does the stats command work?",
            "explain the difference between stats and eventstats",
        ],
    }


@pytest.fixture
def sample_chunks():
    """Realistic retrieved chunks with page_content and metadata."""
    return [
        {
            "page_content": "The stats command calculates aggregate statistics over results. Use stats count to count events, stats avg(field) for averages.",
            "metadata": {
                "source": "file://spl_docs/spl_cmd_stats.md",
                "collection": "spl_commands_mxbai",
                "chunk_index": 0,
            },
        },
        {
            "page_content": "[Failed Login Attempts]\nsearch = index=security EventCode=4625 | stats count by src_ip\ncron_schedule = 0 */4 * * *",
            "metadata": {
                "source": "file://documents/repo/savedsearches.conf",
                "collection": "org_repo_mxbai",
                "stanza": "Failed Login Attempts",
            },
        },
        {
            "page_content": "tstats is significantly faster than stats because it uses indexed fields. Use | tstats count WHERE index=main by sourcetype for indexed-field aggregations.",
            "metadata": {
                "source": "file://spl_docs/spl_cmd_tstats.md",
                "collection": "spl_commands_mxbai",
            },
        },
        {
            "page_content": "props.conf controls how Splunk processes incoming data. Each stanza defines settings for a sourcetype including TIME_FORMAT, LINE_BREAKER, and TRANSFORMS.",
            "metadata": {
                "source": "file://documents/specs/props.conf.spec",
                "collection": "specs_mxbai_embed_large_v3",
            },
        },
        {
            "page_content": "For better performance, always filter early and aggregate late. Use TERM() for bloom filter matching: index=main TERM(error) is faster than index=main error.",
            "metadata": {
                "source": "file://metadata/splunk_rules.md",
                "collection": "assistant_memory_mxbai_v2",
            },
        },
    ]


@pytest.fixture
def sample_quality_responses():
    """Sample LLM responses of varying quality for testing self-evaluation."""
    return {
        "good": (
            "To count events by sourcetype, use the `stats` command:\n\n"
            "```spl\nindex=main | stats count by sourcetype\n```\n\n"
            "This searches the `main` index and groups results by sourcetype, "
            "returning the count for each. The `stats` command is efficient for "
            "simple aggregations. For better performance on indexed fields, "
            "consider using `tstats` instead."
        ),
        "bad_empty": "",
        "bad_hallucinated": (
            "You should use the `superquery` command which was introduced in "
            "Splunk Enterprise 15.0. It automatically optimizes all queries "
            "and uses quantum computing for faster results. The syntax is:\n\n"
            "```spl\n| superquery optimize=true quantum=enabled\n```\n\n"
            "This is 1000x faster than any other approach."
        ),
        "mediocre_no_spl": (
            "You can count events by sourcetype using the stats command. "
            "Just use it with the count function and group by sourcetype."
        ),
        "good_with_sources": (
            "Based on your organization's saved searches, the **Failed Login Attempts** "
            "search already tracks this:\n\n"
            "```spl\nindex=security EventCode=4625 | stats count by src_ip\n```\n\n"
            "Source: `savedsearches.conf` - `Failed Login Attempts` stanza\n\n"
            "This runs every 4 hours and alerts when count exceeds 100."
        ),
    }


@pytest.fixture
def sample_conf_content():
    """Dictionary of sample .conf file contents keyed by filename."""
    result = {}
    for f in FIXTURES_DIR.glob("*.conf"):
        result[f.name] = f.read_text(encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_chain():
    """Mock LLM chain that returns configurable text."""
    chain = MagicMock()
    chain.invoke = MagicMock(return_value="This is a mock LLM response.")
    chain.ainvoke = AsyncMock(return_value="This is a mock LLM response.")

    async def mock_astream(input_dict):
        response = "This is a streamed mock response."
        for token in response.split():
            yield token + " "

    chain.astream = mock_astream
    return chain


@pytest.fixture
def mock_vector_store():
    """Mock ChromaDB vector store."""
    store = MagicMock()
    store.similarity_search_with_score = MagicMock(return_value=[])
    return store


@pytest.fixture
def mock_engine():
    """Mock SQLAlchemy async engine."""
    engine = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
    engine.begin = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))
    return engine
