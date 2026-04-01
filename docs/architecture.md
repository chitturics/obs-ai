# ObsAI System Architecture

## 1. System Overview

ObsAI (v4.0.0) is a Chainlit-based AI assistant for Splunk, Cribl, and observability administration. It combines RAG (Retrieval-Augmented Generation) with a multi-agent orchestration framework, enterprise security, and comprehensive observability.

Key capabilities: intent-driven query routing, multi-collection vector search, knowledge graph augmentation, 54 specialized agents, 133 executable skills, 22 orchestration strategies, 36 MCP tools, enterprise security (RBAC, JWKS OIDC, MFA, audit, policy engine), self-learning pipeline, Splunk upgrade readiness testing, and a React admin console with simplified 6-group sidebar.

### System Stats
| Metric | Count |
|--------|-------|
| Python modules | 319 |
| Skills | 133 across 8 families |
| Agents | 54 across 10 departments |
| Orchestration strategies | 22 |
| MCP tools | 36 |
| API endpoints | 300+ |
| Slash commands | 23 |
| Admin sidebar groups | 6 (~30 items) |
| ChromaDB collections | 10 |
| Total tests | 5,195 (0 failures) |
| Upgrade readiness modules | 12 (233 tests) |
| SLOs | 6 |
| CIM models | 15 |
| Eval cases | 20 |

## 2. Container Architecture

Nine containers (plus an optional Docling sidecar) run on a Podman bridge network. Nginx is the only container with a published port.

```
                         Port 8000 (GATEWAY_PORT)
                              |
                        +-----+------+
                        |   Nginx    |  (reverse proxy, only published port)
                        +-----+------+
                              |  chainlit_net bridge network
       +----------+-----------+----------+-----------+----------+
       |          |           |          |           |          |
  +----+----+ +---+----+ +---+----+ +---+----+ +----+---+ +----+---+
  |   App   | | Ollama | | Chroma | | Postgre| | Redis  | |SearchOpt|
  | :8090   | | :11430 | |  DB    | |  SQL   | | :6379  | | :8080  |
  |chainlit | |  LLM   | | :8001  | | :5432  | | cache  | |optimizer|
  +---------+ +--------+ +--------+ +--------+ +--------+ +--------+
       |
  +----+----+    +----------+    +----------+
  |Prometheus|   | Grafana  |    | Docling  |  (optional sidecar)
  | :9090    |   | :3000    |    | :5001    |
  +----------+   +----------+    +----------+
```

- **Bridge network**: `chainlit_net` -- containers communicate via DNS names (e.g., `llm_api_service`, `chat_chroma_db`, `chat_db_app`)
- **Nginx**: `nginx.conf.template` + `envsubst` generates config; lazy DNS resolution via `set $var; proxy_pass $var;` handles optional containers
- **Routes**: `/` (chat UI), `/api/` (admin API), `/ws` (WebSocket), `/grafana/`, `/prometheus/`, `/search-opt/`
- **Health checks**: All use `podman exec` since no container ports are published to the host

## 3. Request Flow

```
User Query
    |
    v
[Nginx :8000] --> [Chainlit App :8090]
                        |
                   on_message()
                        |
                   message_handler.py
                        |
          +-------------+-------------+
          |             |             |
   Intent         Query          Vector
  Classifier     Expansion      Search
   (27 intents)     |          (ChromaDB)
          |         |             |
          +----+----+----+--------+
               |         |
          Knowledge    Context
           Graph       Builder
          (NetworkX)     |
               |         |
               +----+----+
                    |
              Orchestration
             (22 strategies)
                    |
              Agent Dispatch
             (54 agents, 133 skills)
                    |
              LLM Generation
               (Ollama)
                    |
              Streaming Response
                    |
                    v
               User (chat UI)
```

## 4. Core Pipeline (message_handler.py)

The message handler (~600 lines) orchestrates the full query lifecycle:

1. **Intent Classification** (`intent_classifier.py`): Classifies into one of 27 intents (22 classifier-produced + 5 phantom). Uses regex patterns for SPL actions and keyword matching. Intent enum defined in `registry.py`.

2. **Query Routing** (`query_router.py`): Routes to specialized handlers for slash commands, data transforms, or general RAG. Query expansion generates alternate phrasings for broader retrieval.

3. **Vector Search** (`vectorstore_search.py`): Searches ChromaDB across multiple collections -- `spl_commands_mxbai` (1120 docs), `specs_mxbai_embed_large_v3` (1472 docs), `self_learned_qa` (623 docs), and others. Uses `mxbai-embed-large` embeddings (512 token context, L2 distance). Retrieval parameters: k=50, k_per_collection=30.

4. **Context Building** (`context_builder.py`): Assembles LLM context from vector search results, knowledge graph facts, spec file content, feedback history, and capabilities context (23 commands, 133 skills, 54 agents).

5. **Orchestration** (`orchestration_strategies.py`): Selects from 22 strategies based on intent, resource availability, and config overrides. Default is **adaptive** (hierarchical decomposition, worker agents, critic loop). Resource-aware fallback: heavy strategies downgrade when CPU/memory > 90%.

6. **Agent Dispatch** (`agent_dispatcher.py`): Routes to the best-fit agent from 54 agents across 10 departments. Each agent has department directives, expertise styles, and skill chains. Execution via `skill_executor.py` with 4-tier resolution: ToolRegistry, SkillsManager, Internal handlers, ReAct loop.

7. **LLM Response** (`response_generator.py`): Streams response from Ollama with the assembled context. Supports comparison context, proactive insights (SPL explain, optimization suggestions), and dynamic prompt overlays from the self-learning pipeline.

## 5. Data Architecture

### PostgreSQL (chat_db_app)
- User accounts and metadata (roles stored in JSONB)
- Chat threads and message history (Chainlit's data layer)
- Feedback records (liked/disliked responses)

### ChromaDB (chat_chroma_db)
- 8+ collections with ~3200 total documents
- Primary collections: `spl_commands_mxbai` (SPL command docs), `specs_mxbai_embed_large_v3` (spec/conf files), `self_learned_qa` (generated Q&A pairs)
- Embedding model: `mxbai-embed-large` (512 token limit)
- Chunking: token-based (250 tokens, 40 overlap) + stanza-aware for .conf/.spec files (3000 chars, 100 overlap)

### Redis
- Response caching with TTL
- Rate limiting counters
- Session state for API mode
- Collection success rate scores (retrieval boost)

### NetworkX Knowledge Graph (in-memory)
- 9 entity types: Command, Function, Field, Index, Lookup, Datamodel, Argument, Operator, ConfigStanza
- 20 relationship types (has_arguments, uses_functions, pipes_to, operates_on, etc.)
- Built from 174 SPL docs, 68 spec files, and metadata files
- Serialized to JSON for fast restarts; `generate_context_for_query()` injects structural facts into LLM context

## 6. Self-Learning Pipeline

The system continuously improves through a multi-stage learning cycle managed by `self_learning.py` and scheduled via `resource_manager.py`:

1. **Q&A Generation**: Produces question-answer pairs from SPL docs, metadata, configs, saved searches, macros, indexes, and org config
2. **Vector Ingestion**: Stores generated pairs in the `self_learned_qa` ChromaDB collection
3. **Answer Reassessment**: Validates existing answers against current collection state
4. **Semantic Fact Learning**: Extracts behavioral rules from user feedback (liked/disliked responses)
5. **Dynamic Prompt Overlay**: Injects learned rules into the LLM system prompt at query time
6. **Retrieval Boost Scores**: Caches per-collection success rates to weight future searches
7. **Model Customization** (monthly): Exports 18K+ JSONL training pairs, generates an Ollama Modelfile, creates a fine-tuned model
8. **Learning Snapshots**: Records quality trends and success rates after each cycle

All jobs are resource-gated (`_guarded()` wrapper) with CPU/memory checks and job overlap prevention.

## 7. Admin Architecture

### FastAPI Admin API
- 275+ endpoints mounted on the Chainlit app at `/api/admin/`
- Key route groups: settings CRUD, LLM config, orchestration, workflows, knowledge graph, containers, skills, users, audit, backup, utilities
- Config management with hot-reload/app-restart/full-restart classification per section
- Utility API: 35 operations (encoding, hashing, data transform, text manipulation, validation)

### React Admin Console
- SPA at `/api/admin/v2/` with code-split lazy-loaded pages
- 26+ sections: Dashboard, Users, Profiles, LLM, Retrieval, Ingestion, Prompts, SSL, Features, Skills, MCP, Knowledge Graph, Containers, Version, Audit, Backup, Analytics, Guardrails, Traces, Workflow Designer, and more
- Standalone docs page at `/api/admin/docs`

### Configuration
- `config.yaml` is the primary config file, loaded via Pydantic settings (`settings.py`)
- Profile switching: multiple named config profiles with CRUD via admin API
- Config versioning with backup history
- Env var overrides supported (e.g., `ORG_NAME`, `ENABLE_AUTHENTICATION`)

## 8. Security Model

### Authentication (Fail-Closed)
- Controlled by `ENABLE_AUTHENTICATION` env var (default: **true**)
- Production/staging: authentication mandatory, cannot be disabled (returns 503)
- Development: when disabled, anonymous access with **VIEWER** role (read-only)
- When enabled: Chainlit JWT auth via `access_token` cookie
- MFA enforcement: configurable per role (admin_required by default)
- Auth providers module for extensible authentication backends

### RBAC (Role-Based Access Control)
- Four roles: **VIEWER** < **USER** < **ANALYST** < **ADMIN**
- Router-level `dependencies=[Depends(require_admin)]` protects all admin endpoints
- `require_role(*roles)` factory for fine-grained endpoint protection
- `min_role` field on skills enforces role-based execution access
- `/api/admin/whoami` for session introspection

### API Security
- Rate limiting via Redis
- CORS configuration in nginx
- API key authentication for programmatic access
- Docker socket access controlled via container group membership

## 9. Observability Stack

### OpenTelemetry
- `otel_tracing.py` and `otel_tracer.py` for distributed tracing
- Memory exporter (`otel_memory_exporter.py`) for in-process trace inspection
- Trace data exposed via admin API (`/traces`)

### Prometheus
- `prometheus_metrics.py` exposes application metrics
- Dedicated Prometheus container scrapes the app and other services
- Metrics: request latency, LLM call duration, cache hit rates, orchestration execution counts

### Grafana
- Pre-configured dashboards for health monitoring
- Proxied through nginx at `/grafana/`
- Health monitor (`health_monitor.py`) feeds service status and internal metrics

### Structured Logging
- `logging_utils.py`: JSON-formatted logs with request correlation IDs
- `LatencyTracker` for per-stage timing within the pipeline
- Audit trail auto-populated via contextvars for admin API operations
- Log level dynamically adjustable via admin API (`/set-log-level`)

---

## 10. Caching Strategy

### Redis Cache Layers

| Cache | Key Pattern | TTL | Invalidation |
|-------|------------|-----|--------------|
| Vector search results | `vr:{query_hash}:{k}` | 3600s | On collection reindex |
| Assembled prompt | `prompt:{context_hash}` | 300s | On config reload |
| Health status | `health:{service}` | 30s | Auto-expire |
| Rate limiting | `rl:{client_ip}` (sorted set) | 61s | Auto-expire (sliding window) |
| Settings cache | `settings:v{hash}` | 600s | On `reload_settings()` |
| Feedback matches | `fb:{query_hash}` | 1800s | On feedback update |

### In-Memory Caches
- `lru_cache` on `get_settings()` — cleared by `reload_settings()`
- Knowledge graph singleton — rebuilt on `/knowledge-graph/rebuild`
- Skill/agent catalog singletons — populated once at startup
- Feature flags dict — reloaded via `/features/reload`
- Container runtime detection — cached after first check

### Cache Warming
- On startup: settings loaded, KG built, catalogs populated
- On config change: `reload_settings()` clears + rebuilds in-memory cache
- On reindex: vector cache entries invalidated for affected collections

### Invalidation Rules
- Config change → clear settings LRU + Redis prompt cache
- Document ingestion → clear vector cache for affected collections
- Feedback update → clear feedback match cache
- Profile switch → clear all prompt caches (system prompt changes)

---

## 8. Enterprise Security Architecture

### Authentication Chain (checked in order)
```
Request → X-Service-Key header? → Service-to-service auth (internal)
        → access_token cookie?  → Chainlit JWT decode
        → Authorization: Bearer? → API key check → OIDC validation → JWT decode
        → X-API-Key header?     → API key lookup
        → None?                 → 401 Unauthorized
```

### Authorization Layers
```
Layer 1: Role-based (VIEWER < USER < ANALYST < ADMIN)
  └─ Router-level: dependencies=[Depends(require_admin)]
  └─ Endpoint-level: require_role("ANALYST", "ADMIN")

Layer 2: Fine-grained RBAC (rbac.py)
  └─ Permission format: resource_type:resource_id:action
  └─ Wildcards: tool:*:execute, *:*:read
  └─ Per-user overrides: grants + denials

Layer 3: Skill-level (skill_catalog.py + skill_executor.py)
  └─ min_role per skill (checked before execution)
  └─ approval_gate: AUTO, INFORM, CONFIRM, REVIEW

Layer 4: Safety policies (safety_policies.py)
  └─ 4 safety levels: read_only, write, external_write, destructive
  └─ Per-environment enforcement: dev/staging/production
  └─ Destructive in production → always requires approval

Layer 5: Policy engine (policy_engine.py)
  └─ Declarative rules (OPA-style)
  └─ Effects: deny, require_approval, warn
  └─ Change windows, weekend freeze
```

### MFA Enforcement
- TOTP-based (RFC 6238), compatible with Google Authenticator
- 4 policies: disabled, optional, admin_required, all_required
- 8 backup codes per enrollment

### Audit Trail
- Immutable hash-chained log (SHA-256, JSONL persistence)
- Tamper detection via chain verification
- Export: JSON, CSV, Splunk HEC format

---

## 9. Observability Architecture

### Execution Tracking Stack
```
User Request
  │
  ├─ Workflow Engine (workflow_engine.py)
  │   └─ start_run() → step tracking → finish_run()
  │   └─ Simulation: predict execution without running
  │
  ├─ Execution Tracker (execution_tracker.py)
  │   └─ Tracks: commands, skills, agents, MCP tools
  │   └─ WorkflowTrace with parent-child hierarchy
  │   └─ Feeds: audit_log, activity_timeline, SLO tracker
  │
  ├─ Pipeline Lineage (pipeline_lineage.py)
  │   └─ init_trace → record_stage → finalize_trace
  │   └─ Stages: routing, retrieval, orchestration, context_build, llm, post_process
  │
  ├─ OpenTelemetry (otel_tracing.py)
  │   └─ Span types: pipeline, retrieval, agent, llm
  │   └─ Memory exporter + optional OTLP collector
  │
  └─ Prometheus Metrics (prometheus_metrics.py)
      └─ System: CPU, memory, disk
      └─ Application: latency, tokens, cache hits
      └─ Agent: dispatch count, quality, success rate
```

### SLO Definitions (8 SLOs)
| SLO | Target | Window | Category |
|-----|--------|--------|----------|
| system_availability | 99.5% | 1h | system |
| api_availability | 99.9% | 1h | system |
| tool_success_rate | 95% | 1h | tool |
| tool_latency_budget | 95% | 1h | tool |
| retrieval_quality | 90% | 1h | retrieval |
| retrieval_latency | 95% | 1h | retrieval |
| response_correctness | 90% | 24h | response |
| response_latency | 90% | 1h | response |

### Circuit Breaker Pattern
```
CLOSED (normal) ──failure──→ count++
  │                            │
  │ success → reset count      │ threshold reached
  │                            ↓
  └────────────────────── OPEN (fast-fail)
                              │
                        cooldown elapsed
                              ↓
                         HALF_OPEN (test)
                          ↙         ↘
                    success       failure
                       ↓             ↓
                    CLOSED          OPEN
```

---

## 10. Agent Framework

### Agent Capabilities Model
```
AgentPersona
  ├── capabilities: AgentCapabilities
  │   ├── can_ask_clarification: bool    (ask user when uncertain)
  │   ├── can_delegate: bool             (hand off to other agents)
  │   ├── can_write: bool                (trigger write operations)
  │   └── max_concurrent_skills: int
  ├── guardrails: AgentGuardrails
  │   ├── forbidden_skills: List[str]    (hard-blocked skills)
  │   ├── read_only: bool                (write protection)
  │   ├── scope: str                     (human-readable boundary)
  │   └── max_retries: int
  └── data_sources: AgentDataSources
      ├── collections: List[str]         (authorized ChromaDB collections)
      ├── knowledge_graph: bool
      ├── feedback_access: bool
      └── mcp_tools: List[str]
```

### Self-Assessment Protocol
```
Pre-execution:  Can I handle this? → confidence score
                                   → clarification questions (if low)
                                   → delegation suggestion (if very low)

Post-execution: Did I answer well? → quality estimate
                                   → knowledge gaps identified
                                   → improvement suggestions
```

### Inter-Agent Communication
- Blackboard pattern: shared context per workflow run
- Typed messages: REQUEST, RESPONSE, INFORM, DELEGATE, CLARIFY, ESCALATE
- Clarification flow: agent → user question → enriched re-execution

---

## 11. Standalone Admin UI

### Decoupled Architecture
```
Browser → Nginx (port 8000)
           ├── /api/admin/v2/* → static files (admin UI)
           │   └── Served directly from frontend/dist/
           │   └── Survives app container restart
           │
           ├── /api/* → proxy to App (port 8090)
           │   └── REST API for admin operations
           │
           └── / → proxy to App (port 8090)
               └── Chainlit chat UI
```

The admin UI is served as static files by nginx, decoupled from the app container. This means administrators can restart, rebuild, or debug the app container without losing access to the admin console.

---

## 12. Upgrade Readiness Architecture

Tests Splunk upgrades in an isolated container before applying to production.

```
Admin Request (POST /api/admin/upgrade/analyze)
    |
    v
upgrade_readiness/
    ├── baseline_builder.py    → snapshot current .conf files and apps
    ├── conf_differ.py         → compare baseline vs target version defaults
    ├── cim_analyzer.py        → validate 15 CIM data models
    ├── dependency_tracer.py   → map app/add-on dependency graph
    ├── impact_scorer.py       → calculate risk score (0-100)
    ├── splunkbase_fetcher.py  → check app compatibility on Splunkbase
    ├── uf_analyzer.py         → Universal Forwarder upgrade analysis
    ├── container_tester.py    → run upgrade in isolated container
    └── report_builder.py      → generate HTML/Markdown report
```

### Upgrade Test Flow

```
1. baseline_builder captures current state
2. conf_differ identifies breaking .conf changes
3. cim_analyzer checks 15 CIM model compatibility
4. dependency_tracer maps what breaks downstream
5. impact_scorer assigns risk levels per component
6. container_tester spins up target Splunk version, runs validation
7. report_builder generates final readiness report
```

### SLO Definitions (6 SLOs)

| SLO | Target | Window | Category |
|-----|--------|--------|----------|
| system_availability | 99.5% | 1h | system |
| api_availability | 99.9% | 1h | system |
| tool_success_rate | 95% | 1h | tool |
| retrieval_quality | 90% | 1h | retrieval |
| response_correctness | 90% | 24h | response |
| response_latency | 90% | 1h | response |

### CMS++ Sidebar Configuration (v4.0)

Admin sidebar simplified to 6 groups (~30 items):

| Group | Items |
|-------|-------|
| System | Dashboard, Containers, Version, Audit |
| Configuration | Settings, LLM, Profiles, Features, Organization |
| Knowledge | Collections, Ingestion, Documents, Knowledge Graph |
| Intelligence | Skills, Agents, Orchestration, Workflows |
| Observability | Monitoring, Traces, SLOs, Evolution, GCI, Analytics |
| Security | Users, Roles, RBAC, MFA, Policies, Approvals |

### CMS++ Sidebar Configuration
- Server-driven: sidebar layout stored in `data/sidebar_config.json`
- API: GET/PUT/POST for config, reorder, show/hide, reset
- Defaults from `frontend/src/constants/sections.ts`
- 7 groups: Overview, AI & Retrieval, Intelligence, Developer Tools, Infrastructure, Integrations, Operations
