# Obs AI — AI-Powered Observability Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An open-source, self-hosted AI assistant for Splunk and observability administration. Runs entirely on your infrastructure with support for **local LLMs (Ollama)** or **cloud providers (OpenAI, Anthropic, Google, Azure, or any OpenAI-compatible endpoint)**.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/obsai-project/obs-ai.git
cd obs-ai

# 2. Configure
cp .env.example .env
# Edit .env — set passwords and choose your LLM provider (see below)

# 3. Build
bash docker_files/build_all.sh

# 4. Start
bash docker_files/start_all.sh --no-ingest

# 5. Open
#    Chat UI:     http://localhost:8000/
#    Admin Panel: http://localhost:8000/api/admin/v2/
```

Default credentials: `admin` / (whatever you set in `.env` as `ADMIN_PASSWORD`)

---

## Choose Your LLM

Set `LLM_PROVIDER` in `.env`. Default is `ollama` (local, no API key needed).

| Provider | Env Variable | Default Model | Notes |
|----------|-------------|---------------|-------|
| `ollama` | `OLLAMA_BASE_URL` | qwen2.5:3b | Local, free, no data leaves your machine |
| `openai` | `OPENAI_API_KEY` | gpt-4o-mini | OpenAI API |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-sonnet-4-20250514 | Anthropic Claude API |
| `google` | `GOOGLE_API_KEY` | gemini-2.0-flash | Google Gemini API |
| `azure_openai` | `AZURE_OPENAI_API_KEY` + `_ENDPOINT` | gpt-4o-mini | Azure-hosted OpenAI |
| `openai_compatible` | `OPENAI_COMPATIBLE_BASE_URL` | — | vLLM, LMStudio, LocalAI, etc. |
| `mcp_llm` | `MCP_LLM_ENDPOINT` | — | Route inference through any MCP server |

**Example — switch to Anthropic:**
```bash
# In .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**Example — use a local vLLM server:**
```bash
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=http://localhost:8080
OPENAI_COMPATIBLE_MODEL=meta-llama/Llama-3-8B-Instruct
```

**Ollama profiles** (in `config/llm.yaml`):

| Profile | Model | RAM | GPU | Use Case |
|---------|-------|-----|-----|----------|
| `LLM_LITE` | qwen2.5:3b | 8 GB | No | Fast, CPU-only |
| `LLM_MED` | qwen2.5-coder:7b | 12 GB | No | Balanced |
| `LLM_MAX` | codellama:13b | 16 GB | Yes (8 GB VRAM) | Best quality |

---

## Architecture

```
Browser → Nginx (:8000) → Chainlit App (:8090)
                            ├── Intent Classifier (27 intents)
                            ├── Vector Search (ChromaDB, 10 collections)
                            ├── Knowledge Graph (NetworkX)
                            ├── Orchestration (22 strategies, 54 agents, 133 skills)
                            ├── LLM (Ollama / Cloud / MCP)
                            └── Streaming Response
```

### Containers

| Container | Port | Purpose |
|-----------|------|---------|
| **nginx** | 8000 (published) | Reverse proxy — only exposed port |
| **chat_ui_app** | 8090 | Chainlit + FastAPI admin |
| **llm_api_service** | 11430 | Ollama local LLM |
| **chat_chroma_db** | 8001 | ChromaDB vector store |
| **chat_db_app** | 5432 | PostgreSQL (history, users, config) |
| **chat_redis** | 6379 | Cache, rate limiting |
| **search_opt_service** | 8080 | SPL analysis |
| **chat_prometheus** | 9090 | Metrics |
| **chat_grafana** | 3000 | Dashboards |

All containers communicate over an internal bridge network. Only port 8000 is published.

---

## Features

| Category | Details |
|----------|---------|
| **Multi-LLM** | Ollama, OpenAI, Anthropic, Google, Azure, MCP-as-LLM, OpenAI-compatible |
| **RAG** | 10 ChromaDB collections, mxbai-embed-large embeddings, reranking |
| **Agents** | 54 agents across 10 departments, expertise-based routing |
| **Skills** | 133 skills across 8 families, 4-tier execution |
| **Orchestration** | 22 strategies (adaptive, parallel, hierarchical, democratic, meritocratic) |
| **MCP Server** | 36 MCP tools for external AI clients |
| **Knowledge Graph** | Entity graph (9 types, 20 relationships) |
| **Security** | RBAC (4 roles), MFA (TOTP), hash-chained audit log, policy engine |
| **Admin Console** | React SPA (~30 pages) at `/api/admin/v2/` |
| **Observability** | OpenTelemetry, Prometheus, Grafana, structured JSON logging |
| **Slash Commands** | 23 commands (`/spec`, `/explain`, `/run`, `/kg`, `/skill`, `/tutorial`, ...) |

---

## Admin Console

URL: `http://localhost:8000/api/admin/v2/`

| Group | Pages |
|-------|-------|
| **System** | Dashboard, Containers, Version, Audit |
| **Configuration** | Settings, LLM, Profiles, Features, Organization |
| **Knowledge** | Collections, Ingestion, Documents, Knowledge Graph |
| **Intelligence** | Skills, Agents, Orchestration, Workflows |
| **Observability** | Monitoring, Traces, SLOs, Evolution, Analytics |
| **Security** | Users, Roles, RBAC, MFA, Policies, Approvals |

---

## Configuration

All config lives in `config/` (YAML files). Most sections support hot-reload via the admin UI.

| Behavior | Config Sections |
|----------|----------------|
| **Hot reload** | ingestion, retrieval, prompts, security, features, organization |
| **App restart** | profiles, ui, mcp_gateway |
| **Full restart** | database |

Key files:
- `config/llm.yaml` — LLM provider, model profiles, prompt settings
- `config/security.yaml` — Auth, RBAC, rate limiting
- `config/mcp_gateway.yaml` — MCP server connections
- `.env` — Secrets, API keys, passwords

---

## Ingest Your Documents

Obs AI builds its knowledge base from documents you provide:

```bash
# Place documents in the documents/ directory
cp your-docs/*.pdf documents/pdfs/
cp your-docs/*.md documents/markdown/

# Run ingestion
bash docker_files/start_all.sh
# Or trigger via admin UI: Knowledge → Ingestion → Run
```

Supported formats: PDF, Markdown, plain text, Splunk .conf specs, HTML

---

## Testing

```bash
# Full test suite (~5000 tests)
bash scripts/run_tests.sh quick

# Specific test file
python -m pytest tests/test_upgrade_readiness.py -v

# Frontend tests
cd frontend && npm test
```

---

## MCP Server

Obs AI exposes 36 tools via MCP, allowing external AI clients to use it as a tool server:

```json
// .mcp.json — connect from any MCP client
{
  "mcpServers": {
    "obsai": {
      "command": "python",
      "args": ["mcp_server.py"]
    }
  }
}
```

Tools include: health checks, search, collections, configuration, LLM settings, skills, agents, users, cache, containers, backup/restore, and more.

---

## Project Structure

```
obs-ai/
├── chat_app/           # Main application (Python)
│   ├── app.py          # Entry point
│   ├── llm_utils.py    # LLM provider factory
│   ├── llm_gateway.py  # Multi-LLM gateway with fallback
│   ├── settings.py     # Pydantic config
│   ├── admin_*.py      # Admin API routes (~29 files)
│   └── ...             # Intent classifier, skills, agents, etc.
├── config/             # YAML configuration (18 files)
├── frontend/           # React admin console
├── skills/             # 133 skills across 16 families
├── docker_files/       # Dockerfiles, build/start scripts
├── documents/          # Your knowledge base documents
├── tests/              # ~5000 tests
├── mcp_server.py       # Standalone MCP server
└── docker-compose.yml  # Container orchestration
```

---

## Contributing

1. Fork and branch: `feature/short-description` or `fix/issue-description`
2. Test: `bash scripts/run_tests.sh quick` — must pass
3. Build: `docker build -f docker_files/Dockerfile.app -t chainlit-app:latest .`
4. PR: passing CI, 1 review, no unresolved comments

Every bug fix requires a regression test.

---

## License

[MIT](LICENSE) — use it, modify it, ship it.
