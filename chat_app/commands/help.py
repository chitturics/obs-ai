"""
/help command handler.

Provides a comprehensive, categorized help page with tips,
examples, and navigation guidance for every available command.
"""
import chainlit as cl


# ---------------------------------------------------------------------------
# Help text sections (split for maintainability)
# ---------------------------------------------------------------------------

_HEADER = """# ObsAI Splunk Assistant — Command Reference

> Type any command below or just ask a question in plain English.
> The assistant understands natural language for Splunk queries,
> configuration help, and troubleshooting.
"""

_SEARCH_QUERY = """## Search & Query

| Command | Description |
|---------|-------------|
| `/run <SPL>` | Execute a Splunk search and show results |
| `/search <text>` | Search the knowledge base (specs, feedback, docs) |
| `/spec <file>` | Look up a .conf.spec reference file |
| `/analyze_searches` | Analyze all saved searches for optimization opportunities |
| `/create_alert` | Step-by-step alert creation guide |

**Tips:**
- `/run` sends queries directly to Splunk — use with caution on production.
- `/search` queries the local vector store, not Splunk. Great for finding
  documentation, prior answers, and configuration references.
- You can also just type a question like *"How do I use tstats?"* without
  any slash command — the assistant will search and respond automatically.
"""

_CONFIGURATION = """## Configuration & Profiles

| Command | Description |
|---------|-------------|
| `/config` | Show current session settings |
| `/config <key>=<value>` | Update a setting (e.g. `search_depth=10`) |
| `/admin` | Admin console links and config.yaml editing guide |
| `/admin config` | How to edit config.yaml persistently |
| `/check_configs` | Validate .conf files in your org repo |
| `/build-config` | Interactive conf stanza builder (inputs/props/transforms) |
| `/profile` | Show your current chat profile |

**Tips:**
- The **gear icon** (Settings) adjusts session-level settings only.
  For persistent **config.yaml** changes, use `/admin config` or the
  [Admin Console](/api/admin/v2/).
- Change your **chat profile** (General, SPL Expert, Config Helper, etc.)
  by clicking the profile selector in the sidebar.
- `/build-config` walks you through creating properly-formatted
  `inputs.conf`, `props.conf`, or `transforms.conf` stanzas step-by-step.
"""

_SPLUNK_ADMIN = """## Splunk Administration

| Command | Description |
|---------|-------------|
| `/splunk info` | Server version, OS, and roles |
| `/splunk license` | License usage with visual progress bar |
| `/splunk apps` | List installed apps with versions |
| `/splunk indexes` | Index sizes, event counts, and data types |
| `/splunk users` | Users with roles and email |
| `/splunk inputs [type]` | Data inputs (filter: monitor/tcp/udp/http) |
| `/splunk messages` | System warnings and error messages |
| `/splunk forwarders` | Connected forwarders (requires deployment server) |

**Tips:**
- Requires `SPLUNK_HOST` and credentials (`SPLUNK_TOKEN` or
  `SPLUNK_USERNAME`/`SPLUNK_PASSWORD`) to be configured.
- `/splunk inputs monitor` filters to just file monitor inputs.
- These commands use the Splunk REST API — they show live data.
"""

_MONITORING = """## Health & Monitoring

| Command | Description |
|---------|-------------|
| `/health` | Run health checks on all services (Ollama, ChromaDB, Redis, Splunk) |
| `/status` | Alias for `/health` |

**Tips:**
- Background health monitoring runs automatically every 5 minutes.
  It only alerts you when **new** issues are detected.
- `/health` runs checks immediately and shows full results.
- Monitored services: Ollama LLM, ChromaDB vector store, Redis cache,
  PostgreSQL database, and Splunk instance (if configured).
"""

_MCP = """## MCP (Model Context Protocol)

| Command | Description |
|---------|-------------|
| `/mcp` | Show available MCP servers and token status |
| `/mcp token <server>` | Authenticate and save a token for a server |
| `/mcp logout <server>` | Remove a saved token |

**Tips:**
- MCP servers provide external tool access (e.g. Splunk, ServiceNow).
- Tokens are stored per-user in the database and persist across sessions.
- Your admin configures available MCP servers in `mcp_servers.json`.
"""

_AI_LEARNING = """## AI Learning & Insights

| Command | Description |
|---------|-------------|
| `/explain <SPL>` | Explain an SPL query in plain language |
| `/learn` | Show self-learning system status |
| `/learn run` | Trigger a manual learning cycle |
| `/learn facts` | Show learned semantic facts |
| `/learn insights` | Show proactive optimization insights |
| `/ingest <file>` | Ingest a file (PDF, HTML, JSON, CSV, etc.) |
| `/ingest dir <path>` | Ingest all files from a directory |
| `/ingest sharepoint` | Ingest from configured SharePoint library |
| `/ingest confluence <space>` | Ingest from a Confluence space |

**Tips:**
- The assistant continuously learns from your interactions and feedback.
- Use `/explain` to understand complex SPL queries written by others.
- `/learn insights` surfaces optimization opportunities in your environment.
- `/ingest` supports PDF, HTML, JSON, CSV, YAML, Markdown, .conf, and .spec files.
"""

_UTILITY = """## Utility

| Command | Description |
|---------|-------------|
| `/clear` | Clear conversation history |
| `/stats` | View usage statistics and metrics |
| `/version` | Show version, environment, and library info |
| `/help` | Show this help page |
| `/tutorial` | Interactive guided lessons |

"""

_INLINE_FEATURES = """## Inline Features (no command needed)

You can also use these features by including keywords in your message:

| Keyword | What it does |
|---------|-------------|
| `read_url: <URL>` | Fetch and ingest a web page into the knowledge base |
| `read_file: <path>` | Ingest a local file into the knowledge base |
| `read_text: "<text>"` | Ingest inline text as a knowledge chunk |
| `optimize ...` | Automatically triggers SPL query optimization |
| `suggest a query ...` | Generates an SPL query from natural language |

"""

_EXAMPLES = """## Quick Start Examples

```
How do I configure props.conf for JSON logs?
What is the difference between stats and eventstats?
optimize this: index=main | stats count by host
/run index=_internal | head 5
/search TERM() optimization
/spec inputs.conf
/splunk license
/build-config
/health
```
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def help_command(args: str = ""):
    """Show the full help page, or a specific section.

    Args:
        args: Optional section name (e.g. "splunk", "config", "search").
              If empty, shows the full help page.
    """
    section = args.strip().lower() if args else ""

    # Allow targeted help: /help splunk, /help config, etc.
    section_map = {
        "search": _SEARCH_QUERY,
        "query": _SEARCH_QUERY,
        "config": _CONFIGURATION,
        "configuration": _CONFIGURATION,
        "splunk": _SPLUNK_ADMIN,
        "admin": _SPLUNK_ADMIN,
        "health": _MONITORING,
        "monitor": _MONITORING,
        "monitoring": _MONITORING,
        "mcp": _MCP,
        "learn": _AI_LEARNING,
        "learning": _AI_LEARNING,
        "ingest": _AI_LEARNING,
        "explain": _AI_LEARNING,
        "ai": _AI_LEARNING,
    }

    if section and section in section_map:
        await cl.Message(content=section_map[section]).send()
        return

    # Full help page
    full_help = "\n".join([
        _HEADER,
        _SEARCH_QUERY,
        _CONFIGURATION,
        _SPLUNK_ADMIN,
        _MONITORING,
        _AI_LEARNING,
        _MCP,
        _UTILITY,
        _INLINE_FEATURES,
        _EXAMPLES,
    ])

    await cl.Message(content=full_help).send()
