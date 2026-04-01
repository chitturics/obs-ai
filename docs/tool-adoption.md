# ObsAI Tool Adoption Registry

> Version: 3.5.0 | Last updated: 2026-03 | Maintainer: ObsAI Core Team

This document records every major open-source tool adopted by the ObsAI project,
the alternatives that were evaluated, and the rationale behind each decision.
It serves as a living reference for future reviews and onboarding.

---

## Table of Contents

1. [LLM Runtime](#1-llm-runtime)
2. [Vector Database](#2-vector-database)
3. [Embedding Model](#3-embedding-model)
4. [Chat Framework](#4-chat-framework)
5. [Web Framework](#5-web-framework)
6. [Frontend](#6-frontend)
7. [Database](#7-database)
8. [Cache](#8-cache)
9. [Monitoring](#9-monitoring)
10. [Tracing](#10-tracing)
11. [Knowledge Graph](#11-knowledge-graph)
12. [Container Runtime](#12-container-runtime)
13. [Reranking](#13-reranking)

---

## 1. LLM Runtime

### Category: LLM Runtime — Local inference server for chat and embedding models

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 | Alternative 4 |
|---|---|---|---|---|---|
| **Name** | [Ollama](https://ollama.com/) | [vLLM](https://github.com/vllm-project/vllm) | [LocalAI](https://localai.io/) | [LM Studio](https://lmstudio.ai/) | [llama.cpp](https://github.com/ggerganov/llama.cpp) |
| **Stars/Community** | 120k+ GitHub stars, very active | 55k+ stars, production-grade | 28k+ stars, growing | Proprietary desktop app | 80k+ stars, foundational |
| **License** | MIT | Apache 2.0 | MIT | Proprietary (free) | MIT |
| **GPU requirement** | Optional (CPU fallback) | Requires GPU for practical use | Optional | Optional | Optional |
| **Model management** | Built-in pull/create/list CLI | Manual weight download | OpenAI-compat API, multi-backend | GUI-based model browser | Manual GGUF management |
| **Embedding support** | Native (`/api/embeddings`) | Separate deployment needed | Yes | Limited | Via server mode |
| **Container-friendly** | Official OCI image, single binary | Yes, but heavy CUDA deps | Yes | No (desktop app) | Yes, but manual setup |
| **Fine-tuning** | Modelfile + GGUF import | LoRA serving built-in | Adapter support | No | LoRA merge only |
| **Why chosen** | Single binary, trivial container deployment, built-in model registry (`ollama pull`), native embedding endpoint, Modelfile-based fine-tuning workflow, excellent LangChain integration via `langchain-ollama`. CPU fallback critical for WSL2/rootless Podman environments without GPU passthrough. | | | | |
| **Why rejected** | | Requires dedicated GPU; CUDA container setup is complex in rootless Podman on WSL2. Overkill for single-user assistant workloads. | Fewer models available out-of-box; community smaller; embedding quality inconsistent across backends. | Not containerizable; proprietary; cannot run headless in production. | No model management CLI; requires manual GGUF file handling; no built-in embedding endpoint without server wrapper. |

**Decision date**: 2024-06 | **Next review**: 2026-09

---

## 2. Vector Database

### Category: Vector Database — Persistent store for document embeddings and similarity search

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 | Alternative 4 |
|---|---|---|---|---|---|
| **Name** | [ChromaDB](https://www.trychroma.com/) | [Qdrant](https://qdrant.tech/) | [FAISS](https://github.com/facebookresearch/faiss) | [Weaviate](https://weaviate.io/) | [Milvus](https://milvus.io/) |
| **Stars/Community** | 18k+ stars, AI-native community | 22k+ stars, production-focused | 32k+ stars (Meta) | 12k+ stars | 32k+ stars |
| **License** | Apache 2.0 | Apache 2.0 | MIT | BSD 3-Clause | Apache 2.0 |
| **Deployment** | Single container, ~200MB | Single container, ~300MB | In-process library | Single container, ~500MB+ | Multi-container (etcd, MinIO) |
| **LangChain integration** | `langchain-chroma` (first-class) | `langchain-qdrant` | `langchain-community` | `langchain-weaviate` | `langchain-milvus` |
| **Multi-collection** | Native, simple API | Native, rich filtering | Manual index management | Native, schema-based | Native |
| **Persistence** | SQLite-backed, volume mount | RocksDB, snapshots | Serialize to disk (manual) | Built-in | Distributed storage |
| **Memory footprint** | Low (~100MB idle) | Low-medium | Depends on index size | Medium (~500MB+) | High (1GB+ with deps) |
| **Why chosen** | Lightest operational footprint of any persistent vector DB. Single container, simple REST API, native LangChain support. Multi-collection design maps directly to our 6+ document collections (spl_docs, specs, metadata, org_config, self_learned_qa, etc.). SQLite persistence is trivially backed up via volume. v2 API (`/api/v2/heartbeat`) is stable. | | | | |
| **Why rejected** | | Strong alternative; heavier filtering API is not needed for our retrieval patterns. Would consider for multi-tenant scale-out. | Not a server; in-process only. Cannot share index across containers. No built-in persistence server. | Resource-heavy; schema-first design adds complexity for our simple doc-chunk model. GraphQL API is overkill. | Requires etcd + MinIO sidecars; massively over-provisioned for single-node deployment with 8 containers already. |

**Decision date**: 2024-06 | **Next review**: 2026-09

---

## 3. Embedding Model

### Category: Embedding Model — Dense vector encoder for document chunks and queries

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [mxbai-embed-large](https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1) | [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | [nomic-embed-text](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) | [bge-large-en-v1.5](https://huggingface.co/BAAI/bge-large-en-v1.5) |
| **Dimensions** | 1024 | 384 | 768 | 1024 |
| **Context window** | 512 tokens | 256 tokens | 8192 tokens | 512 tokens |
| **MTEB rank** | Top-10 at release | Mid-tier | Top-15 | Top-10 |
| **Size (params)** | 335M | 22M | 137M | 335M |
| **Ollama native** | Yes (`ollama pull`) | No (needs manual GGUF) | Yes | No (needs manual GGUF) |
| **Inference speed** | ~15ms/chunk (CPU) | ~3ms/chunk (CPU) | ~8ms/chunk (CPU) | ~15ms/chunk (CPU) |
| **Why chosen** | Best MTEB quality among Ollama-native embedding models at 512-token context. 1024-dim vectors capture fine-grained SPL syntax distinctions (e.g., `stats` vs `eventstats` vs `streamstats`). Our chunk size (250 tokens) fits well within the 512-token window. Direct `ollama pull mxbai-embed-large` with zero conversion steps. | | | |
| **Why rejected** | | 384 dimensions too low for distinguishing similar SPL commands; 256-token context clips our 250-token chunks with no room for overlap. Quality gap noticeable on technical retrieval. | Excellent long-context model, but our chunks are 250 tokens; the 8K context is wasted overhead. Not available via Ollama at time of adoption. Would reconsider if chunk strategy changes. | Comparable quality to mxbai-embed-large but not natively available in Ollama model library; requires manual GGUF conversion and Modelfile creation. |

**Decision date**: 2024-07 | **Next review**: 2026-06

---

## 4. Chat Framework

### Category: Chat Framework — Conversational UI with streaming, auth, and plugin support

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [Chainlit](https://chainlit.io/) | [Streamlit](https://streamlit.io/) | [Gradio](https://gradio.app/) | [Open WebUI](https://openwebui.com/) |
| **Stars/Community** | 8k+ stars | 38k+ stars | 35k+ stars | 55k+ stars |
| **License** | Apache 2.0 | Apache 2.0 | Apache 2.0 | MIT |
| **Streaming** | Native WebSocket | `st.write_stream` (polling) | Server-sent events | Native WebSocket |
| **Auth system** | Built-in JWT + OAuth | Requires external proxy | Basic auth only | Built-in multi-user |
| **LangChain hooks** | `@cl.langchain_factory` | Manual wiring | Manual wiring | OpenAI-compat only |
| **Custom actions** | `@cl.action_callback` | Button callbacks | `gr.Button` | Limited |
| **Slash commands** | Built-in support | Not native | Not native | Not native |
| **Multi-step chat** | Steps, tool calls, elements | Hacky session state | Chatbot component | Conversation history |
| **FastAPI mount** | Native (`cl.mount_app`) | Separate process | Separate process | Separate process |
| **Why chosen** | Purpose-built for LLM chat applications. Native WebSocket streaming, built-in JWT authentication (used for RBAC), `@cl.on_message`/`@cl.action_callback` decorators, ability to mount a full FastAPI app alongside the chat (powers our 109+ admin API endpoints). Slash command support maps directly to our 10 custom commands. Step/element system enables rich tool-call visualization. | | | |
| **Why rejected** | | Reruns entire script on interaction; no true WebSocket streaming; session state is fragile. Not designed for production chat. Would require external auth proxy for multi-user. | Designed for ML demos, not production chat assistants. No JWT auth, no slash commands, no persistent conversation threads. | Excellent Ollama frontend but opinionated UI; cannot mount custom FastAPI routes; limited extensibility for our 119-skill execution layer. We do provide OpenAI-compat API (`openai_compat.py`) for Open WebUI as an alternative frontend. |

**Decision date**: 2024-06 | **Next review**: 2026-09

---

## 5. Web Framework

### Category: Web Framework — Backend API for admin console, health checks, and integrations

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [FastAPI](https://fastapi.tiangolo.com/) | [Flask](https://flask.palletsprojects.com/) | [Django](https://www.djangoproject.com/) | [Starlette](https://www.starlette.io/) |
| **Stars/Community** | 82k+ stars | 70k+ stars | 82k+ stars | 10k+ stars |
| **License** | MIT | BSD 3-Clause | BSD 3-Clause | BSD 3-Clause |
| **Async support** | Native async/await | Requires Quart or extensions | Django 4.1+ (partial) | Native async/await |
| **Auto-docs** | OpenAPI + Swagger UI built-in | Requires flask-restx | Django REST framework | Manual |
| **Pydantic** | Native integration | Manual | Serializers (different) | Manual |
| **Dependency injection** | `Depends()` system | Flask-Injector | Django DI (limited) | None built-in |
| **WebSocket** | Built-in | Flask-SocketIO | Django Channels | Built-in |
| **Why chosen** | Native async (critical for concurrent LLM calls), Pydantic integration (matches our `settings.py` models), `Depends()` system powers RBAC (`require_admin`, `require_role`), auto-generated OpenAPI docs for the 109+ admin endpoints. Chainlit mounts FastAPI directly via `cl.mount_app()` -- zero-config integration. Type hints provide self-documenting API contracts. | | | |
| **Why rejected** | | Synchronous by default; would need Quart for async. No native Pydantic support. Dependency injection requires third-party library. | Massive framework; ORM, template engine, admin panel are all unnecessary -- we use SQLAlchemy + React. Async support still catching up. | FastAPI is built on Starlette; using Starlette directly loses auto-docs, Pydantic integration, and `Depends()`. No reason to drop down a layer. |

**Decision date**: 2024-06 | **Next review**: 2026-12

---

## 6. Frontend

### Category: Frontend — Admin console single-page application

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [React](https://react.dev/) + [Vite](https://vitejs.dev/) + [Tailwind CSS](https://tailwindcss.com/) | [Next.js](https://nextjs.org/) | [Vue 3](https://vuejs.org/) + Vite | [Svelte](https://svelte.dev/) + SvelteKit |
| **Stars/Community** | React 235k+, Vite 72k+, Tailwind 85k+ | 130k+ stars | Vue 48k+, Vite shared | Svelte 82k+ |
| **License** | MIT (all) | MIT | MIT | MIT |
| **Bundle size** | ~180KB gzipped (lazy-loaded routes) | Larger (SSR runtime) | Comparable | Smaller |
| **SSR needed** | No (admin SPA, served by nginx) | SSR is the point | Optional | Optional |
| **Component ecosystem** | Massive (Monaco, ECharts, Lucide, TanStack Query) | Same React ecosystem | Growing, fewer niche libs | Smallest ecosystem |
| **Type safety** | TypeScript 5.6 | TypeScript | TypeScript | TypeScript |
| **Key libraries** | `@tanstack/react-query`, `echarts-for-react`, `@monaco-editor/react`, `lucide-react`, `react-router-dom` | Same available | Different chart/editor libs | Limited editor options |
| **Why chosen** | React has the largest component ecosystem, critical for our admin console needs: Monaco editor (config editing), ECharts (dashboard charts), TanStack Query (API state management), Lucide (icon library). Vite provides sub-second HMR and optimized production builds. Tailwind CSS eliminates CSS file management. No SSR needed -- the admin console is a pure SPA served as static files through nginx. | | | |
| **Why rejected** | | SSR adds unnecessary complexity; we serve the admin SPA as static files from nginx. Node.js server runtime would be another container to manage. React ecosystem is identical -- no benefit, only overhead. | Smaller component ecosystem; no equivalent to `@monaco-editor/react` (critical for config editing). Team more experienced with React/JSX. | Smallest ecosystem of all options. No mature Monaco editor wrapper. Compiler-based approach is elegant but hiring/onboarding pool is smaller. |

**Decision date**: 2024-08 | **Next review**: 2026-12

---

## 7. Database

### Category: Database — Persistent storage for users, sessions, feedback, audit logs

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [PostgreSQL 16](https://www.postgresql.org/) | [SQLite](https://sqlite.org/) | [MySQL 8](https://www.mysql.com/) | [MongoDB](https://www.mongodb.com/) |
| **Stars/Community** | Industry standard, 40+ years | Ubiquitous embedded DB | Widely deployed | 27k+ stars |
| **License** | PostgreSQL License (permissive) | Public Domain | GPL v2 (server) | SSPL (server) |
| **Image size** | `postgres:16-alpine` ~80MB | N/A (embedded) | ~150MB | ~300MB |
| **JSONB support** | Native, indexed | JSON1 extension (limited) | JSON type (no GIN index) | Native (document store) |
| **Async drivers** | `asyncpg` (fastest Python PG driver) | `aiosqlite` | `aiomysql` | `motor` |
| **SQLAlchemy support** | First-class | First-class | First-class | Requires MongoEngine |
| **Concurrent writes** | MVCC, excellent | WAL mode (limited) | Row-level locking | Document-level |
| **Why chosen** | JSONB columns store user metadata and RBAC roles (queried by `require_role()`). `asyncpg` driver is the fastest async PostgreSQL driver for Python. Native Chainlit data persistence layer support. Alpine image is only 80MB. Handles concurrent feedback writes, audit logs, and session data without contention. SQLAlchemy 2.0 async support is first-class with PostgreSQL. | | | |
| **Why rejected** | | Single-writer limitation; cannot handle concurrent feedback writes from multiple chat sessions. No server process means no connection pooling. Fine for prototyping, not for multi-container production. | GPL license is more restrictive. JSONB support weaker (no GIN indexes). `aiomysql` driver less mature than `asyncpg`. No meaningful advantage over PostgreSQL for our workload. | SSPL license is problematic. Document model unnecessary -- our data is relational (users, sessions, feedback with foreign keys). Would require MongoEngine instead of SQLAlchemy, breaking Chainlit's built-in persistence. |

**Decision date**: 2024-06 | **Next review**: 2027-01

---

## 8. Cache

### Category: Cache — In-memory key-value store for session data, rate limiting, and retrieval boost scores

| Criteria | Adopted | Alternative 1 | Alternative 2 |
|---|---|---|---|
| **Name** | [Redis](https://redis.io/) (with hiredis) | [Memcached](https://memcached.org/) | [KeyDB](https://docs.keydb.dev/) |
| **Stars/Community** | 68k+ stars, de facto standard | Mature, widely deployed | 11k+ stars |
| **License** | RSALv2 + SSPLv1 (since 7.4) / BSD (<=7.2) | BSD 3-Clause | BSD 3-Clause |
| **Data structures** | Strings, hashes, lists, sets, sorted sets, streams | Key-value only | Redis-compatible superset |
| **Persistence** | RDB + AOF | None | RDB + AOF |
| **Pub/Sub** | Native | Not supported | Native |
| **Python driver** | `redis[hiredis]` (C-accelerated parser) | `pymemcache` | `redis[hiredis]` (compatible) |
| **TTL support** | Per-key, millisecond precision | Per-key, second precision | Per-key |
| **Why chosen** | Rich data structures needed for: retrieval boost scores (sorted sets), collection success rates (hashes), session cache (strings with TTL), job overlap locks (`acquire_job`/`release_job`). `hiredis` C parser gives ~3x throughput over pure Python. Pub/Sub reserved for future multi-instance coordination. Ubiquitous tooling and monitoring support. | | |
| **Why rejected** | | Key-value only; cannot store our boost score sorted sets or hash-based collection stats without serialization overhead. No persistence -- cache cold-starts after restart lose learned boost scores. No pub/sub for future scaling. | Technically superior (multi-threaded), but Redis wire-compatible -- could be a drop-in replacement later. Smaller community and fewer container images. License (BSD) is actually better, making this our top candidate if Redis licensing becomes a concern. |

**Decision date**: 2024-06 | **Next review**: 2026-06

---

## 9. Monitoring

### Category: Monitoring — Metrics collection, alerting, and visualization

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [Prometheus](https://prometheus.io/) + [Grafana](https://grafana.com/) | [Datadog](https://www.datadoghq.com/) | [ELK Stack](https://www.elastic.co/elastic-stack) | [VictoriaMetrics](https://victoriametrics.com/) |
| **Stars/Community** | Prometheus 57k+, Grafana 66k+ | Commercial SaaS | Elasticsearch 72k+ | 13k+ stars |
| **License** | Apache 2.0 (both) | Commercial | Elastic License 2.0 / SSPL | Apache 2.0 |
| **Cost** | Free, self-hosted | Per-host/metric pricing | Free self-hosted (heavy resources) | Free, self-hosted |
| **Scrape model** | Pull-based (15s interval) | Agent push | Beats/Logstash push | Prometheus-compatible pull |
| **Python client** | `prometheus-client` (official) | `ddtrace` | Custom | `prometheus-client` (compatible) |
| **Resource usage** | ~100MB (Prometheus) + ~150MB (Grafana) | N/A (SaaS) | 2GB+ (Elasticsearch alone) | ~50MB (single binary) |
| **Alert rules** | PromQL-based, YAML config | GUI-based | Watcher/ElastAlert | PromQL-compatible |
| **Why chosen** | Industry-standard pull-based monitoring. `prometheus-client` library already used for custom metrics (`chainlit_llm_calls_total`, `chainlit_llm_latency_seconds`). 15s scrape interval configured for both app and search_optimizer. Grafana provides dashboards for health_monitor.py metrics. Both run as lightweight containers on the existing bridge network. Combined footprint under 250MB. | | | |
| **Why rejected** | | Commercial SaaS; violates self-hosted requirement. Per-metric pricing would be expensive given our 50+ custom metrics. Adds external dependency and data egress. | Elasticsearch alone needs 2GB+ RAM; we already have 8 containers. ELK is designed for log aggregation, not metrics. Overkill for our time-series monitoring needs. | Excellent Prometheus-compatible alternative with lower resource usage. Would consider as a drop-in replacement if Prometheus memory becomes a concern at scale. Currently no compelling reason to switch. |

**Decision date**: 2024-07 | **Next review**: 2026-09

---

## 10. Tracing

### Category: Tracing — Distributed request tracing and LLM observability

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [OpenTelemetry](https://opentelemetry.io/) + [Langfuse](https://langfuse.com/) | [Jaeger](https://www.jaegertracing.io/) | [Zipkin](https://zipkin.io/) | Langfuse only |
| **Stars/Community** | OTel SDK 2k+ (CNCF graduated), Langfuse 7k+ | 21k+ stars (CNCF) | 17k+ stars | 7k+ stars |
| **License** | Apache 2.0 (both) | Apache 2.0 | Apache 2.0 | MIT (self-hosted) |
| **LLM-specific traces** | Langfuse: token counts, costs, prompt versions | No LLM awareness | No LLM awareness | Yes (core feature) |
| **Protocol** | OTLP (gRPC + HTTP) | OTLP or Jaeger native | Zipkin format | HTTP REST |
| **Python SDK** | `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc` | OTel SDK (same) | OTel SDK or native | `langfuse` Python SDK |
| **Backend flexibility** | Any OTLP-compatible collector | Jaeger only | Zipkin only | Langfuse only |
| **Why chosen** | Two-layer approach: OpenTelemetry for infrastructure-level distributed tracing (request correlation across containers via `otel_tracer.py`), Langfuse for LLM-specific observability (token usage, prompt versioning, cost tracking via `langfuse_integration.py`). OTel is CNCF-graduated and vendor-neutral -- traces can be exported to any OTLP backend. Langfuse adds LLM-native features that generic tracing tools lack. | | | |
| **Why rejected** | | Jaeger is an OTel-compatible backend, not a replacement for the SDK. Could be added as an OTLP export target alongside Langfuse. Not rejected per se -- just not needed as a separate tool when OTel SDK + Langfuse covers both infrastructure and LLM tracing. | Older wire format; OTel/OTLP has superseded Zipkin protocol as the standard. Smaller feature set than Jaeger. No LLM awareness. | Langfuse alone covers LLM observability but not infrastructure tracing. Missing: request correlation across containers, latency breakdown by service, error propagation tracking. OTel fills that gap. |

**Decision date**: 2024-09 | **Next review**: 2026-09

---

## 11. Knowledge Graph

### Category: Knowledge Graph — Entity-relationship graph for SPL command structures

| Criteria | Adopted | Alternative 1 | Alternative 2 | Alternative 3 |
|---|---|---|---|---|
| **Name** | [NetworkX](https://networkx.org/) | [Neo4j](https://neo4j.com/) | [ArangoDB](https://arangodb.com/) | [TigerGraph](https://www.tigergraph.com/) |
| **Stars/Community** | 15k+ stars, NumPy/SciPy ecosystem | 14k+ stars | 14k+ stars | 2k+ stars |
| **License** | BSD 3-Clause | GPL v3 (Community) | Apache 2.0 | Commercial (free tier) |
| **Deployment** | In-process (pip install) | Separate container (1GB+ RAM) | Separate container (500MB+) | Separate container (1GB+) |
| **Query language** | Python API (native) | Cypher | AQL | GSQL |
| **Persistence** | JSON serialization to file | Built-in | Built-in | Built-in |
| **Scale limit** | ~100K nodes (in-memory) | Millions of nodes | Millions of nodes | Billions of edges |
| **Graph algorithms** | 500+ built-in (shortest path, centrality, etc.) | APOC library | Built-in | Built-in |
| **Why chosen** | Our knowledge graph has ~2,000 entities (9 types: Command, Function, Field, Index, Lookup, Datamodel, Argument, Operator, ConfigStanza) with ~10,000 relationships. This fits entirely in memory. NetworkX requires zero additional containers (already at 8), zero additional ports, zero query language to learn. JSON serialization to `/app/data/knowledge_graph.json` provides persistence. 500+ graph algorithms available for future entity-ranking features. Pure Python -- no driver compatibility concerns. | | | |
| **Why rejected** | | Would add a 9th container consuming 1GB+ RAM for a graph that fits in <50MB of Python memory. GPL v3 license is restrictive. Cypher is powerful but unnecessary for our simple traversal patterns (`generate_context_for_query()`). Operational overhead unjustified. | Multi-model (document + graph) is interesting but we already have PostgreSQL for documents and NetworkX for graph. Another container, another port, another backup strategy. | Commercial product; free tier has limitations. Designed for massive-scale graph analytics (billions of edges). Our 10K-edge graph would be like using a freight train to carry a backpack. |

**Decision date**: 2024-10 | **Next review**: 2026-12

---

## 12. Container Runtime

### Category: Container Runtime — OCI container management on WSL2/Linux

| Criteria | Adopted | Alternative 1 | Alternative 2 |
|---|---|---|---|
| **Name** | [Podman](https://podman.io/) | [Docker](https://www.docker.com/) | [containerd](https://containerd.io/) + nerdctl |
| **Stars/Community** | 25k+ stars, Red Hat backed | 70k+ stars, industry default | 18k+ stars (CNCF graduated) |
| **License** | Apache 2.0 | Apache 2.0 (engine) | Apache 2.0 |
| **Daemonless** | Yes (fork/exec model) | No (dockerd daemon required) | containerd daemon required |
| **Rootless** | First-class support | Experimental | Experimental |
| **Docker CLI compat** | `alias docker=podman` works | Native | nerdctl (partial compat) |
| **Compose** | `podman-compose` or `podman compose` | `docker compose` | nerdctl compose |
| **Systemd integration** | `podman generate systemd` | Requires third-party | Manual |
| **Pod support** | Native (Kubernetes pod concept) | No | No |
| **Why chosen** | Daemonless architecture eliminates the Docker daemon as a single point of failure. Rootless mode is critical for WSL2 environments where running a privileged daemon is undesirable. Docker CLI compatibility means existing scripts (`start_all.sh`) work with minor adjustments. Bridge networking (`chainlit_net`) with aardvark-dns provides container-name resolution. Systemd unit generation simplifies production deployment. | | |
| **Why rejected** | | Requires a running daemon (`dockerd`), which is a privileged process. On WSL2, Docker Desktop is the typical path, adding a proprietary layer. Docker's licensing changed (Docker Desktop requires subscription for enterprises). Engine itself is Apache 2.0 but the ecosystem pushes toward paid products. | Low-level runtime; `nerdctl` CLI is less mature than Podman's Docker compat. Compose support is basic. No rootless-first design. Better suited as a Kubernetes CRI than a standalone container manager. |

**Decision date**: 2024-06 | **Next review**: 2027-01

---

## 13. Reranking

### Category: Reranking — Second-stage retrieval scoring for improved RAG precision

| Criteria | Adopted | Alternative 1 | Alternative 2 |
|---|---|---|---|
| **Name** | [cross-encoder/ms-marco-MiniLM-L-6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2) | [Cohere Rerank](https://cohere.com/rerank) | [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| **Stars/Community** | 5M+ downloads on HuggingFace | Commercial API | 1M+ downloads on HuggingFace |
| **License** | Apache 2.0 | Commercial API | MIT |
| **Deployment** | Local (sentence-transformers) | API call | Local (sentence-transformers) |
| **Latency** | ~20ms for 10 candidates (CPU) | ~200ms (network round-trip) | ~50ms for 10 candidates (CPU) |
| **Model size** | 22M params (~90MB) | N/A (API) | 568M params (~2.2GB) |
| **Accuracy (MS MARCO)** | MRR@10: 0.39 | MRR@10: 0.42+ | MRR@10: 0.41 |
| **Multilingual** | English only | 100+ languages | Multilingual |
| **Status in project** | Implemented but **disabled by feature flag** | N/A | N/A |
| **Why chosen** | Smallest cross-encoder with acceptable reranking quality. At 22M params / 90MB, it runs on CPU without impacting Ollama's memory budget. Implemented in `confidence_scorer.py` via sentence-transformers. Currently disabled by feature flag pending production benchmarks -- embedding-only retrieval with boost scores provides sufficient quality for now. Ready to enable when retrieval precision needs improvement. | | |
| **Why rejected** | | External API dependency violates self-hosted requirement. Network latency (200ms+) would double our retrieval time. Per-query pricing at scale. Higher accuracy, but the delta does not justify the operational cost. | 2.2GB model would compete with Ollama for RAM on resource-constrained deployments. ~2.5x slower than MiniLM-L-6. Higher accuracy, but the memory/latency tradeoff is unfavorable given our CPU-first deployment model. Would reconsider if GPU is available. |

**Decision date**: 2024-10 | **Next review**: 2026-06

---

## Review Process

1. **Quarterly scan**: Check for major version releases, security advisories, and license changes for all adopted tools.
2. **Trigger-based review**: Any adopted tool is re-evaluated when:
   - A critical CVE is published
   - The license changes (e.g., Redis RSALv2 shift)
   - Resource requirements exceed current allocation
   - A clearly superior alternative emerges
3. **Decision authority**: Core maintainer team. Document the outcome in this file regardless of whether a switch is made.
4. **Migration cost**: Always weigh the cost of switching (data migration, API changes, testing) against the benefit. Prefer stability unless the case is compelling.
