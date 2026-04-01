# ObsAI Module Reference

> Module documentation for ObsAI v4.0-dev.
> Answers: "What does this file do? When does it run? What does it depend on?"

---

## 1. Core Pipeline

Processes every user query from input to response.

**Architecture:** `User Input -> Intent Classifier -> Retrieval -> Orchestration -> Context Build -> LLM -> Response`

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `message_handler.py` | Main query pipeline — 19 stages from input to response | `on_message()`, `build_llm_context()`, `generate_llm_response()` | vectorstore_search, orchestration_strategies, settings, otel_tracing | Every user message | 1979 |
| `intent_classifier.py` | Regex-based intent detection with 27 intent types | `classify()`, `_score_patterns()` | registry (Intent enum) | Every user message | 557 |
| `response_generator.py` | LLM invocation (streaming/non-streaming), SPL template engine | `generate_response()`, `stream_response()`, `_apply_spl_template()` | llm_utils, cache, ollama_priority, settings | Every user message | 404 |
| `context_builder.py` | Chunk scoring, context assembly, reference management | `build_context()`, `score_chunks()`, `format_references()` | settings | Every user message (after retrieval) | 693 |
| `prompts.py` | System/user prompt templates loaded from markdown files | `get_system_prompt()`, `get_template()`, `render()` | prompt_templates/*.md, settings | Every user message | 1664 |
| `prompts_path_aware.py` | Path-aware system prompt with org repo structure knowledge | `SYSTEM_PROMPT` | settings (org_name) | Per-query (org intents) | 359 |
| `confidence_scorer.py` | Nuanced confidence scoring with reasoning | `score()`, `calibrate()` | settings | Every user message (post-retrieval) | 227 |
| `profiles.py` | Profile-based retrieval strategies and prompts (7 profiles) | `get_profile_config()`, `get_retrieval_weights()` | settings | Every user message (routing) | — |
| `query_router.py` | Classifies user intent and builds execution plan | `route()`, `build_plan()` | intent_classifier, profiles | Every user message | — |
| `query_router_handler.py` | Intent-to-handler routing for tool-callable intents | `route_to_handler()` | intent_classifier | Per-query (routing) | 154 |
| `query_expander.py` | Compound question splitting into sub-queries with merged results | `expand()`, `merge_results()` | vectorstore_search | Per-query (multi-concept) | 197 |
| `query_planner.py` | Sequential multi-step query decomposition planner | `plan()`, `detect_sequential()` | intent_classifier | Per-query (complex) | 231 |
| `context_compressor.py` | Conversation context compression — summarizes old turns to save tokens | `compress()`, `summarize_turns()` | llm_utils | Per-query (long conversations) | 158 |
| `intent_handler.py` | Executes tool-callable intents (run_search, create_alert) with MCP support | `handle_intent()`, `execute_action()` | mcp_utils, llm_utils, splunk_client | Per-query (action intents) | 285 |
| `obsai_context.py` | Organization-specific context for intelligent result interpretation | `get_org_context()`, `get_app_patterns()` | settings | Per-query (org-aware) | 870 |
| `message_context.py` | Dataclass holding message handler execution context | `MessageHandlerContext` | — | Per-query (passed through pipeline) | 28 |
| `message_metadata.py` | Tag extraction from user messages for tracking and routing | `extract_tags()`, `MessageMetadata` | — | Per-query | 72 |
| `lifecycle_context.py` | Dataclass for chat lifecycle handler context | `LifecycleContext` | — | Per-session | 14 |

---

## 2. Retrieval

Vector search, document ingestion, and knowledge base management.

**Architecture:** `Query -> Collection Selection -> Parallel Search -> Scoring -> Dedup -> Reranking -> Context`

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `vectorstore.py` | ChromaDB client, collection management, embedding operations | `get_chroma_client()`, `search_similar_chunks()`, `_persist()` | chromadb, settings | Per-query (search), startup (init) | 1409 |
| `vectorstore_search.py` | Parallelized vector search with scoring and dedup | `search_similar_chunks_parallel()`, `analyze_query_intent()`, `select_collections_and_weights()` | vectorstore, settings | Every user message | 1416 |
| `vectorstore_ingest.py` | Document indexing into ChromaDB (files, URLs, text, feedback) | `ingest_documents()`, `add_feedback_qa_to_memory()`, `add_feedback_note_to_memory()` | vectorstore, smart_chunker | On ingestion trigger, feedback events | 470 |
| `document_ingestor.py` | Multi-format parsing: PDF, HTML, SharePoint, Confluence, JSON, CSV, YAML | `ingest()`, `parse_pdf()`, `parse_html()`, `ingest_sharepoint()` | vectorstore_ingest, docling_client, settings | On-demand (admin trigger) | 2001 |
| `smart_chunker.py` | File-type-aware text splitting (token-based, stanza-aware) | `chunk()`, `chunk_conf()`, `chunk_markdown()` | settings (chunking config) | During ingestion | — |
| `reranker.py` | Cross-encoder reranking (ms-marco-MiniLM-L-6-v2) | `rerank()` | cross-encoder model | Per-query (if enabled) | — |
| `semantic_cache.py` | Embedding-similarity cache for similar queries | `get_cached()`, `cache_result()` | ollama embeddings | Per-query (before search) | — |
| `adaptive_rag.py` | Auto-selects optimal retrieval pipeline mode | `select_mode()`, `RAGMode` | vectorstore_search | Per-query (routing) | 56 |
| `self_adaptive_rag.py` | Feedback-driven collection weight adaptation over time | `update_weights()`, `get_adaptive_weights()` | vectorstore_search, feedback | Per-query (weight adjustment) | 450 |
| `adaptive_integration.py` | Integration hooks connecting self-adaptive RAG to retrieval pipeline | `apply_adaptive_weights()`, `record_feedback()` | self_adaptive_rag | Per-query, on feedback | 241 |
| `feedback_retriever.py` | Retrieves previously thumbs-up'd answers for matching queries | `retrieve_feedback_answer()` | settings, ollama embeddings | Per-query (pre-retrieval) | 294 |
| `negative_feedback.py` | Stores/filters thumbs-down feedback from search results | `add_negative_feedback()`, `filter_negative_results()` | chromadb | Per-query (post-retrieval) | 338 |
| `ingestion_handler.py` | File upload, URL fetch, text block indexing, inline directives | `handle_upload()`, `handle_url()`, `handle_text()` | document_ingestor, vectorstore_ingest | On user file upload | 215 |
| `file_upload_handler.py` | Large file processing — chunking before embedding | `process_upload()`, `chunk_large_file()` | document_ingestor | On file upload | 240 |
| `ingest_splunk_docs.py` | Bulk ingestion of Splunk command documentation from markdown files | `ingest_all_docs()` | vectorstore_ingest | On-demand (startup/admin) | 73 |
| `run_quick_ingest.py` | Full reindex script — deletes all collections and re-ingests everything | `main()`, `reindex_all()` | vectorstore, document_ingestor | On-demand (admin) | 738 |
| `org_data_loader.py` | Loads org-specific data: macros, saved searches, index mappings from .conf files | `load_org_data()`, `parse_conf_files()` | settings, shared.conf_parser | Startup | 271 |

---

## 3. Intelligence

Skills, agents, orchestration, and agentic execution.

**Architecture:** `Intent -> Agent Dispatcher -> Skill Executor -> Orchestration Strategy -> Multi-Agent Result`

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `skill_catalog.py` | 133 skills organized into 8 families mapped to human actions | `get_skill()`, `get_skills_for_intent()`, `search_skills()` | registry | On-demand (agent dispatch) | 1367 |
| `skill_executor.py` | Bridges handler_keys to actual execution via 4-tier resolution | `execute()`, `resolve_handler()` | tool_registry, skills_manager, react_loop | On-demand (skill invocation) | 3395 |
| `skills_manager.py` | Dynamic skill/plugin marketplace — discovery, loading, remote registries | `discover_skills()`, `load_skill()`, `get_marketplace()` | skills/ directory | Startup (discovery), on-demand | 528 |
| `agent_catalog.py` | 54 agent personas with rich prompt fragments across 10 departments | `get_agent()`, `get_agents_for_intent()`, `search_agents()` | registry | On-demand (agent dispatch) | 980 |
| `agent_dispatcher.py` | Routes queries to best-fit agent persona, executes skill chains | `dispatch()`, `select_agent()`, `execute_skills()` | agent_catalog, skill_executor | Per-query (orchestration) | 999 |
| `agent_state.py` | Multi-turn goal tracking — persistent goals and sub-goals across turns | `AgentState`, `set_goal()`, `update_progress()` | — | Per-query (goal tracking) | 216 |
| `orchestration_strategies.py` | 17 pluggable orchestration patterns (core + governance) | `execute_orchestration()`, `get_strategy()`, `register_strategy()` | agent_dispatcher, workflow_orchestrator, resource_manager | Per-query (main pipeline) | 2233 |
| `workflow_orchestrator.py` | Multi-agent coordination: decompose, assign, aggregate | `orchestrate()`, `decompose_task()`, `aggregate_results()` | agent_dispatcher, skill_executor | Complex multi-step queries | 984 |
| `react_loop.py` | ReAct reasoning loop: Think-Act-Observe for complex queries | `run_react_loop()`, `think()`, `act()`, `observe()` | tool_registry, llm_utils | Complex reasoning queries | 299 |
| `tool_registry.py` | Declarative tool system with capability requirements | `register_tool()`, `get_tools_for_query()`, `execute_tool()` | settings | Startup (registration), per-query | 857 |
| `tool_executor.py` | MCP tool binding and execution (native + prompt-based) | `execute_tool_call()`, `bind_tools()` | mcp_utils, llm_utils | Per-query (tool-calling intents) | 344 |
| `tool_effectiveness.py` | Tracks which tools work best per intent/pattern; learns from outcomes | `record_outcome()`, `get_best_tool()`, `get_effectiveness()` | — | Per-tool execution | 295 |
| `director_graph.py` | DAG-based orchestration with conditional routing (LangGraph-inspired) | `DirectorGraphExecutor.execute()`, `GraphNode`, `GRAPH_TEMPLATES` | agent_dispatcher | Complex orchestration | 429 |
| `supervisor_agent.py` | Structured task decomposition with intra-department routing | `SupervisorAgent.execute()`, `decompose()`, `synthesize()` | agent_dispatcher, schemas | Complex orchestration | 326 |
| `action_engine.py` | Typed action execution with state machine tracking (12 action types) | `ActionEngine.execute_plan()`, `ActionPlan` | skill_executor | Action-based orchestration | 346 |
| `api_services.py` | Expose ObsAI capabilities as REST API endpoints for external systems | `ServiceRegistry`, `ServiceExecutor`, `get_catalog()` | skill_executor, auth_dependencies | On-demand (API calls) | 920 |
| `priority.py` | Priority queue for agent/skill task execution with concurrency limits | `PriorityTaskQueue`, `enqueue()`, `execute()` | resource_manager | Per-task scheduling | 145 |
| `human_loop.py` | Human-in-the-loop approval gates, feedback, and oversight ("5 senses") | `request_approval()`, `wait_for_human()`, `HumanLoopGate` | chainlit | Per-query (when approval needed) | 335 |
| `human_loop_api.py` | REST endpoints for approval management (list, approve, deny) | `approval_router`, `list_pending()`, `approve()` | human_loop, auth_dependencies | On admin API request | 165 |
| `puppeteer.py` | Playwright-based web scraper — blocks heavy resources, cleans HTML | `scrape_url()`, `extract_content()` | playwright | On-demand (URL ingestion) | 298 |

---

## 4. Knowledge

Knowledge graph, self-learning, evolution, and continuous improvement.

**Architecture:** `Knowledge Graph + Self-Learning + Evolution Engine + GCI Agent -> Continuous Improvement Loop`

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `knowledge_graph.py` | In-memory NetworkX graph for SPL entity relationships (9 entity types, 20 relationship types) | `get_knowledge_graph()`, `generate_context_for_query()`, `rebuild_knowledge_graph()` | networkx, spl_docs | Startup (build), per-query (context) | 2175 |
| `self_learning.py` | Continuous Q&A generation, answer reassessment, prompt improvement | `run_learning_cycle()`, `generate_qa()`, `reassess_answers()` | vectorstore_ingest, llm_utils, resource_manager | Scheduled (hourly/daily) | 1620 |
| `evolution_engine.py` | OR/game-theory-driven self-assessment, diagnosis, adaptive targets | `assess()`, `diagnose()`, `plan()`, `StalenessDetector`, `AdaptiveTargetManager` | analytics, agent_catalog, resource_manager | Scheduled (daily) | 1232 |
| `gci_agent.py` | Governance & Continuous Improvement meta-evaluator (RAC loop) | `review()`, `analyze()`, `correct()`, `get_agent_trends()` | agent_dispatcher, schemas | Per-query (quality gate) | 722 |
| `knowledge_gap_detector.py` | Identifies topics not covered in KB, suggests ingestion actions | `detect_gaps()`, `get_uncovered_topics()` | vectorstore_search | Per-query (gap detection) | 198 |
| `self_evaluator.py` | Post-generation quality assessment (completeness, accuracy, relevance) | `evaluate()`, `check_completeness()`, `check_accuracy()` | llm_utils | Post-response | 247 |
| `qa_dataset_generator.py` | Converts Splunk docs into Q&A format for LLM fine-tuning | `generate_qa_pairs()`, `export_jsonl()` | spl_docs, spec files | On-demand (training data) | 649 |
| `qa_generator_unified.py` | Unified Q&A generator with LLM API fallback to template-based | `generate()`, `template_fallback()` | llm_utils | Scheduled (learning cycle) | 299 |
| `eval_rag_optimizer.py` | Grid search over 18 retrieval configurations for RAG tuning | `optimize()`, `evaluate_config()` | vectorstore_search, eval_test_cases | On-demand (evaluation) | — |
| `eval_test_cases.py` | 10,141 Splunk search test cases for RAG evaluation | `get_test_cases()` | — | Import-time | — |
| `eval_training_export.py` | Generates 18K+ JSONL training pairs for Ollama fine-tuning | `export()`, `generate_pairs()` | spl_docs, spec files | On-demand (admin) | — |

---

## 5. Memory

Cross-session memory, user profiles, and episodic recall.

**Architecture:** `Workflow Memory + User Profiles + Archival Memory + Episodic Memory -> Personalized Context`

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `workflow_memory.py` | Cross-session workflow arc tracking | `WorkflowStep()`, `WorkflowArc()`, `get_active_arcs()` | — | Per-query (arc tracking) | 90 |
| `user_profiles.py` | Adaptive personalization based on query patterns | `update_profile()`, `get_preferences()`, `detect_expertise()` | — | Per-query (profile update) | 120 |
| `user_model.py` | Per-user preference model built from feedback and interaction history | `UserModel`, `update_from_feedback()`, `get_style_prefs()` | — | Per-query (model update) | 233 |
| `archival_memory.py` | Long-term persistent knowledge store with keyword search | `store()`, `search()`, `get_facts()` | JSON file storage | On-demand (fact storage) | 155 |
| `episodic_memory.py` | Structured storage of past interaction episodes | `record_episode()`, `recall_similar()`, `get_patterns()` | — | Per-query (record + recall) | 316 |
| `conversation_memory.py` | In-session conversation context tracking | `add_turn()`, `get_context()` | — | Per-query | — |

---

## 6. Observability

Tracing, metrics, cost tracking, and pipeline lineage.

**Architecture:** `OTel Tracing + Prometheus + Cost Tracker + Pipeline Lineage -> Observability Dashboard`

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `otel_tracing.py` | OpenTelemetry tracing for pipeline stages | `init_otel()`, `trace_span()`, `@traced` | opentelemetry SDK | Every user message | 193 |
| `otel_tracer.py` | Backward-compatible shim re-exporting from otel_tracing | `AIAttributes`, `HAS_OTEL`, `_NoOpSpan` | otel_tracing | Import-time (legacy callers) | 16 |
| `otel_memory_exporter.py` | In-memory span exporter for admin API trace queries | `MemorySpanExporter`, `get_recent_traces()` | opentelemetry SDK | Every span export | 93 |
| `cost_tracker.py` | Per-query LLM cost attribution by model, user, purpose | `record_cost()`, `get_cost_summary()`, `set_cost_context()` | — | Every LLM call | 121 |
| `analytics.py` | Query taxonomy, knowledge gaps, adoption metrics | `record_query()`, `get_taxonomy()`, `get_gap_report()` | — | Every user message | 96 |
| `prometheus_metrics.py` | Prometheus metric definitions bridging in-memory Metrics class | `record_query()`, `record_latency()`, `expose_metrics()` | prometheus_client | Every user message | 264 |
| `logging_utils.py` | Structured JSON logging with request correlation IDs | `setup_logging()`, `LatencyTracker`, `set_request_context()` | — | Every request | 314 |
| `pipeline_lineage.py` | Per-request provenance and stage metrics via contextvars | `init_trace()`, `record_stage()`, `get_trace()` | — | Every user message | 196 |
| `execution_journal.py` | Persistent JSONL execution journal (async-buffered, non-blocking) | `get_journal()`, `journal.log()` | asyncio | Every skill/agent execution | 278 |
| `observability.py` | Tracing, SLOs, alerting, and metrics aggregation | `record_span()`, `check_slos()`, `evaluate_alerts()` | — | Every user message | 808 |
| `observability_api.py` | REST endpoints for tracing, SLOs, alerting, and metrics | `router`, `get_traces()`, `get_slo_status()` | observability | On admin API request | 135 |
| `metrics.py` | In-memory counters and timing utilities | `Metrics`, `get_stats_report()` | — | Every user message | — |
| `monitoring.py` | Proactive Splunk internal log monitoring | `check_internal_logs_for_errors()` | splunk_client | Scheduled | 58 |
| `proactive_monitor.py` | Background service health checks and actionable alerts to chat | `monitor_loop()`, `check_splunk_health()` | splunk_client, health_monitor | Scheduled (background) | 363 |
| `langfuse_integration.py` | DEPRECATED -- Langfuse stubs delegating to OTel | `observe_llm()`, `init_langfuse()` | otel_tracing | Legacy callers only | 84 |

---

## 7. Security

Authentication, authorization, and input/output guardrails.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `auth_dependencies.py` | FastAPI auth dependencies: Cookie JWT, Bearer token, API key | `require_admin()`, `require_role()`, `get_authenticated_user()` | chainlit.auth, settings | Every admin API request | 301 |
| `auth_providers.py` | Enterprise auth providers: OIDC, LDAP with config.yaml integration | `authenticate_oidc()`, `authenticate_ldap()` | settings | On login | 184 |
| `guardrails.py` | Multi-layer input/output safety (PII detection, injection blocking) | `check_input()`, `check_output()`, `redact_pii()` | — | Every user message | 115 |
| `rate_limiter.py` | Token bucket rate limiting per-user and global for LLM/external calls | `check_rate()`, `RateLimiter` | — | Every LLM/external call | 146 |

---

## 8. Configuration

Settings, config management, versioning, and unified registry.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `settings.py` | Pydantic-settings centralized configuration (env + config.yaml) | `get_settings()`, `Settings` | config.yaml, env vars | Startup, on-demand | 980 |
| `config_manager.py` | Full CRUD for config.yaml with backup, validation, profile switching | `read_section()`, `write_section()`, `switch_profile()` | settings | On admin API calls | 475 |
| `config_versioning.py` | Git-style version tracking for configuration changes | `commit()`, `get_history()`, `diff()` | — | On config write | 83 |
| `config_validator.py` | Startup configuration validation — verifies settings and connectivity | `validate_config()`, `check_services()` | settings | Startup | 166 |
| `registry.py` | Unified registry: Intent enum, RoutingTag, slash commands, admin sections | `Intent`, `get_commands()`, `get_sections()`, `validate_catalog()` | — | Startup, import-time | 747 |
| `schemas.py` | Pydantic schemas for validated results (pipeline, research findings) | `PipelineTrace`, `ResearchFinding`, `OrchestrationResult` | pydantic | Import-time | 452 |
| `prompt_manager.py` | Versioned prompt template management with quality tracking | `get_template()`, `update_template()`, `get_history()` | — | On-demand | 107 |

---

## 9. Integrations

MCP, A2A protocol, LLM gateway, and external system connectors.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `mcp_handler.py` | Chainlit MCP connect/disconnect event handlers | `on_mcp_connect()`, `on_mcp_disconnect()` | chainlit | On MCP connection | 29 |
| `mcp_server_mode.py` | Expose ObsAI as an MCP Server (resources + tools) | `MCP_RESOURCES`, `MCP_TOOLS`, `handle_tool_call()` | vectorstore_search, knowledge_graph | On external MCP call | 92 |
| `mcp_registry.py` | Admin-managed MCP server registry from config.yaml | `load_servers()`, `get_server()` | config.yaml | Startup | 99 |
| `mcp_utils.py` | HTTP-based MCP tool loading and execution (SSE + Streamable-HTTP) | `load_tools()`, `execute_tool()`, `MCPTool` | mcp_registry, settings | On-demand (tool discovery) | 302 |
| `a2a_protocol.py` | Agent-to-Agent interoperability (JSON-RPC 2.0, Agent Cards) | `AgentCard`, `handle_rpc()`, `get_agent_card()` | agent_catalog | On external A2A call | 91 |
| `llm_gateway.py` | Multi-LLM gateway with automatic fallback across providers | `call()`, `stream()`, `LLMResponse` | settings | Every LLM call (if multi-provider) | 217 |
| `llm_utils.py` | ChatOllama LLM creation with IPv6 connectivity probing | `get_llm()`, `_probe_ollama_url()` | settings | Startup, per-query | 93 |
| `ollama_priority.py` | Priority request queue ensuring user queries preempt background embeddings | `PriorityQueue`, `submit_user()`, `submit_background()` | asyncio | Every Ollama call | 237 |
| `splunk_client.py` | Splunk REST API client (searches, alerts, apps, indexes) | `SplunkClient`, `run_search()`, `get_saved_searches()` | settings | On-demand (Splunk intents) | 530 |
| `splunk_constants.py` | Canonical lists of built-in Splunk commands and .conf file types | `SEARCH_COMMANDS`, `CONF_FILES` | — | Import-time (validation) | 354 |
| `splunkbase_catalog.py` | Splunkbase app version catalog — compares installed vs latest versions | `check_outdated()`, `get_catalog()`, `SplunkbaseCatalog` | settings | On-demand (admin) | 826 |
| `search_opt_client.py` | HTTP client for the Search Optimizer sidecar container | `call_robust_analyzer()`, `optimize_query()` | search_opt container | On-demand (SPL optimization) | 425 |
| `docling_client.py` | HTTP client for docling-serve sidecar (OCR, tables, layout) | `convert()`, `extract_tables()` | docling-serve container | During document ingestion | — |
| `storage_client.py` | Local filesystem blob storage for Chainlit file attachments | `StorageClient`, `upload()`, `download()` | filesystem | On file upload/download | 75 |

---

## 10. Admin

Admin API endpoints, container management, and admin tools.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `admin_api.py` | Main admin router: settings, features, dashboard, users, approvals | `router`, `get_dashboard()`, `update_settings()` | admin_shared, auth_dependencies | On admin API request | — |
| `admin_shared.py` | Shared helpers: async subprocess, error handling, audit trail, CSRF | `_arun()`, `_safe_error()`, `_append_audit()`, `_container_cmd()` | — | Imported by all admin routers | — |
| `admin_containers.py` | Container management: list, restart, stop, rebuild, health probe | `containers_router`, `list_containers()`, `container_action()` | admin_shared | On admin API request | — |
| `admin_tools.py` | Utility endpoints: network test, regex AI, ansible/shell tools | `tools_router`, `network_test()`, `regex_generate()` | admin_shared, llm_utils | On admin API request | — |
| `admin_network_routes.py` | SSL and network configuration endpoints | `ssl_router`, `get_ssl_status()`, `upload_cert()`, `get_ports()` | admin_shared | On admin API request | — |
| `admin_upgrade_routes.py` | Upgrade readiness API: analyze, test, report, UF analysis | `upgrade_router`, `analyze_upgrade()`, `run_container_test()` | upgrade_readiness package | On admin API request | — |
| `admin_observability_routes.py` | Observability, monitoring, evolution, GCI endpoints | `observability_router`, `get_dashboard()`, `get_evolution_status()` | observability, evolution_engine, gci_agent | On admin API request | — |
| `admin_skills_routes.py` | Skills, agents, orchestration, workflow endpoints | `skills_router`, `get_skill_catalog()`, `dispatch_query()` | skill_catalog, agent_dispatcher, orchestration_strategies | On admin API request | — |
| `admin_config_routes.py` | Config CRUD, versioning, profiles, backup/restore | `config_router`, `get_config()`, `patch_section()` | config_manager, config_versioning | On admin API request | — |
| `admin_settings_routes.py` | Settings read/update with change history | `settings_router`, `get_settings()`, `patch_settings()` | settings | On admin API request | — |
| `admin_tools_routes.py` | Scripting, ansible, shell, python tool endpoints | `tools_router`, `ansible_validate()`, `shell_generate()` | admin_tools_impl | On admin API request | — |
| `admin_users_routes.py` | User CRUD, role management, token management | `users_router`, `list_users()`, `create_user()` | auth_dependencies | On admin API request | — |

---

## 11. Infrastructure

Application lifecycle, health, resource management, caching, and resilience.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `app.py` | Chainlit application entry point with RAG, PostgreSQL, Redis | `@cl.on_chat_start`, `@cl.on_message`, `mount_admin()` | message_handler, admin_api, settings | Startup | 907 |
| `app_api.py` | Standalone FastAPI entry point for Open WebUI mode | `app`, `chat_completions()` | openai_compat, settings | Startup (alt mode) | 473 |
| `chat_lifecycle.py` | Chainlit on_chat_start/on_chat_end event handlers | `on_chat_start()`, `on_chat_end()` | settings, profiles | Per-session | 183 |
| `health.py` | Service health checks (Ollama, ChromaDB, PostgreSQL, Redis) | `check_health()`, `check_ollama()`, `check_chroma()` | settings | On-demand, health endpoint | 243 |
| `health_routes.py` | HTTP health check routes for Kubernetes/Docker probes (/health, /ready) | `health_endpoint()`, `readiness_endpoint()` | health | Continuous (probes) | 218 |
| `health_monitor.py` | Service health checks, internal metrics, self-healing, Prometheus | `run_health_checks()`, `get_health_summary()`, `auto_heal()` | resource_manager, settings | Scheduled (5-min interval) | 721 |
| `resource_manager.py` | Resource-aware job gating, overlap prevention, auto-heal | `can_run_heavy_task()`, `acquire_job()`, `auto_heal()` | /proc/meminfo, /proc/loadavg | Every heavy task, scheduled | 520 |
| `idle_worker.py` | Background self-improvement when agent is idle | `run_idle_tasks()`, `review_feedback()`, `detect_knowledge_gaps()` | self_learning, tool_effectiveness | When no active queries | 423 |
| `cache.py` | Redis caching layer for query responses and vector results | `CacheClient`, `get_cached_query_response()`, `cache_query_response()` | redis, settings | Every user message | 263 |
| `resilience.py` | Circuit breaker, retry logic, fallback mechanisms | `CircuitBreaker`, `retry()`, `with_fallback()` | — | Every external call | 267 |
| `startup_warmup.py` | Pre-populate caches, verify pipeline health at boot | `warmup()`, `verify_chroma()`, `init_singletons()` | vectorstore, agent_dispatcher | Startup (once) | 228 |
| `init_schema.py` | Auto-create PostgreSQL schema tables on startup (idempotent) | `create_tables()`, `ensure_schema()` | postgresql | Startup (before Chainlit) | 240 |
| `session_store.py` | Framework-agnostic session state (for non-Chainlit modes) | `SessionStore`, `get_session()`, `set_session()` | — | Per-request (API mode) | — |
| `data_layer.py` | Custom SQLAlchemy data layer with graceful error handling | `LenientSQLAlchemyDataLayer` | chainlit, sqlalchemy | Startup | — |
| `openai_compat.py` | OpenAI-compatible /v1/models and /v1/chat/completions | `chat_completions()`, `list_models()` | message_handler pipeline | On API request | 311 |
| `workflow_state.py` | PostgreSQL-backed workflow state persistence | `save_workflow()`, `load_workflow()`, `list_workflows()` | postgresql | On workflow save/load | 187 |
| `failure_analyzer.py` | Error categorization, recovery strategies, failure pattern learning | `analyze_failure()`, `suggest_recovery()`, `FailureCategory` | episodic_memory | On error | 374 |

---

## 12. Feedback

Feedback collection, learning, and quality improvement.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `feedback_handler.py` | Chainlit feedback event handler (thumbs up/down) | `on_feedback()`, `process_feedback()` | vectorstore_ingest, feedback_logger | On user feedback | 288 |
| `feedback_logger.py` | PostgreSQL-backed interaction and feedback logging | `log_interaction()`, `log_feedback()`, `save_mcp_token()` | postgresql | Every interaction, on feedback | 773 |
| `feedback_analytics.py` | Feedback export to training JSONL, analytics dashboards | `export_training_data()`, `get_analytics()` | feedback_logger | On-demand (admin) | 414 |
| `feedback_guardrails.py` | Uses feedback history to guide and constrain LLM responses | `apply_guardrails()`, `get_positive_patterns()` | feedback_logger | Per-query (context injection) | 229 |
| `feedback_retriever.py` | Retrieves validated answers from feedback history | `retrieve_feedback_answer()` | settings, ollama embeddings | Per-query (pre-retrieval) | 294 |
| `negative_feedback.py` | Stores bad answers, filters them from future results | `add_negative_feedback()`, `filter_negative_results()` | chromadb | Per-query, on feedback | 338 |
| `export_feedback.py` | Export assistant_feedback rows to static HTML pages | `export_html()` | postgresql | On-demand (CLI) | 89 |
| `generate_feedback_index.py` | Generate HTML index page listing all feedback with Q&A and ratings | `generate_index()` | feedback files | On-demand (CLI) | 483 |
| `proactive_handler.py` | SPL optimization suggestions from response content | `check_for_spl()`, `suggest_optimization()` | search_opt_client | Post-response | 57 |
| `proactive_insights.py` | Proactive recommendations: query optimization, best practices | `get_insights()`, `analyze_saved_searches()` | splunk_client, search_opt_client | Post-response, on-demand | 545 |

---

## 13. Slash Commands

`chat_app/commands/` — Each file handles one `/command`. Routed by `slash_commands.py`.

| Module | Command | Purpose | Lines |
|--------|---------|---------|-------|
| `slash_commands.py` | (router) | Routes `/command` input to handler modules | 122 |
| `commands/help.py` | `/help` | Categorized command reference with tips and examples | — |
| `commands/search.py` | `/search <query>` | Direct vector search against ChromaDB | — |
| `commands/config.py` | `/config [key] [value]` | View/update settings with optional persistence | — |
| `commands/health.py` | `/health` | Comprehensive health check with learning stats | — |
| `commands/stats.py` | `/stats` | User statistics and query metrics | — |
| `commands/profile.py` | `/profile` | Show current profile, agents, and skills | — |
| `commands/spec.py` | `/spec <name>` | Look up Splunk .spec file documentation | — |
| `commands/splunk_admin.py` | `/splunk <sub>` | Splunk admin: info, license, apps, indexes, users, inputs | — |
| `commands/explain.py` | `/explain <SPL>` | Explain an SPL query in plain language | — |
| `commands/run.py` | `/run <SPL>` | Execute SPL search against Splunk and display results | — |
| `commands/ingest.py` | `/ingest <source>` | Ingest documents from files, dirs, SharePoint, Confluence | — |
| `commands/learn.py` | `/learn [run|facts|insights]` | Self-learning management and status | — |
| `commands/kg_cmd.py` | `/kg [search|analyze|related]` | Query the knowledge graph | — |
| `commands/skill_cmd.py` | `/skill [name] [args]` | Execute or browse skills from chat | — |
| `commands/mcp.py` | `/mcp [status|token]` | Manage MCP servers and per-user tokens | — |
| `commands/tutorial.py` | `/tutorial [topic]` | Interactive walkthrough of ObsAI features | — |
| `commands/build_config.py` | `/build_config` | Interactive Splunk .conf stanza builder | — |
| `commands/admin.py` | `/admin [config]` | Quick access to admin console | — |
| `commands/version.py` | `/version` | Application version and environment info | — |
| `commands/clear.py` | `/clear` | Clear chat history | — |
| `commands/create_alert.py` | `/create_alert` | Guided Splunk alert creation | — |
| `commands/analyze_searches.py` | `/analyze_searches` | Analyze all saved searches for optimizations | — |
| `commands/check_configs.py` | `/check_configs` | Validate .conf files and report issues by severity | — |

---

## 14. SPL Handlers

Specialized handlers for SPL query processing.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `spl_validator_handler.py` | SPL validation pipeline: local patterns + Splunk API + AI review | `validate_spl()`, `_local_validate()` | splunk_client, llm_utils | Per-query (SPL intents) | 200 |
| `spl_optimizer_handler.py` | SPL query optimization via search optimizer sidecar | `optimize_spl()` | search_opt_client | Per-query (optimization intents) | 51 |
| `spl_template_handler.py` | SPL template rendering from predefined patterns | `render_template()` | — | Per-query (template intents) | 33 |
| `action_handler.py` | Chainlit action button handlers (followup questions) | `on_followup()` | message_handler, feedback_logger | On user action click | 145 |
| `meta_handler.py` | Meta commands (non-domain queries like greetings, about) | `handle_meta()` | — | Per-query (meta intents) | 56 |

---

## 15. Utilities

Shared helpers, constants, and general-purpose modules.

| Module | Purpose | Key Functions | Depends On | Runs When | Lines |
|--------|---------|---------------|------------|-----------|-------|
| `utils.py` | Context truncation, text cleaning, sanitization, misc helpers | `truncate_context()`, `clean_text()`, `sanitize()` | — | Everywhere | 427 |
| `helper.py` | Session helpers: current_username, current_thread_id, URL extraction | `current_username()`, `current_thread_id()`, `extract_urls()` | chainlit | Per-query | 76 |
| `cron_parser.py` | Deterministic cron schedule parser (no LLM hallucination risk) | `parse_cron()`, `describe_schedule()` | — | Per-query (scheduling intents) | 189 |
| `__init__.py` | Package init: re-exports on_message, catalogs, executors; security warnings | `on_message`, `get_skill_catalog`, `get_agent_dispatcher` | all core modules | Import-time | — |

---

## 16. Shared Library (`shared/`)

Reusable modules shared between the main app and sidecar containers.

| Module | Purpose | Key Functions | Lines |
|--------|---------|---------------|-------|
| `shared/conf_parser.py` | Parse Splunk .conf files into structured dicts | `parse_conf()`, `get_stanzas()` | — |
| `shared/conf_loader.py` | Bulk-load .conf files from directories | `load_confs()` | — |
| `shared/config_analyzer.py` | Validate .conf files and report issues by severity | `ConfigAnalyzer`, `analyze()` | — |
| `shared/spl_analyzer.py` | SPL query static analysis (commands, fields, complexity) | `analyze_spl()` | — |
| `shared/spl_deep_analysis.py` | Deep SPL analysis with data flow and optimization hints | `deep_analyze()` | — |
| `shared/spl_robust_analyzer.py` | Robust SPL parsing tolerant of malformed queries | `robust_parse()` | — |
| `shared/spl_validator.py` | SPL syntax validation against known command grammar | `validate()` | — |
| `shared/spl_query_optimizer.py` | Rule-based SPL query optimization | `optimize()` | — |
| `shared/spl_knowledge_base.py` | Static Splunk command knowledge (args, examples) | `get_command_info()` | — |
| `shared/spl_rules.py` | SPL best-practice rules for linting | `get_rules()` | — |
| `shared/spl_intents.py` | SPL intent patterns for classification | `get_intent_patterns()` | — |
| `shared/spl_template_engine.py` | Template-based SPL generation from natural language | `generate_spl()` | — |
| `shared/nlp_to_spl.py` | Natural language to SPL conversion | `convert()` | — |
| `shared/query_cost_estimator.py` | Estimate resource cost of SPL queries | `estimate_cost()` | — |
| `shared/docs_loader.py` | Load Splunk command documentation from markdown files | `load_docs()` | — |
| `shared/constants.py` | Shared constants (paths, defaults) | — | — |
| `shared/utils.py` | Shared utility functions | — | — |

---

## 17. Search Optimizer Sidecar (`containers/search_opt/`)

Standalone Flask service for SPL analysis and optimization.

| Module | Purpose | Key Functions | Lines |
|--------|---------|---------------|-------|
| `app.py` | Flask app entry point with REST endpoints | `analyze()`, `optimize()` | — |
| `core.py` | Core SPL analysis engine | `analyze_query()` | — |
| `analyzer.py` | Rule-based query analysis (performance, correctness) | `run_analysis()` | — |
| `optimizer.py` | Query rewriting and optimization rules | `optimize_query()` | — |
| `scheduler.py` | Hourly/daily/weekly/monthly scheduled jobs (resource-gated) | `run_scheduler()` | — |
| `learning.py` | Learning from query patterns and feedback | `learn_from_feedback()` | — |
| `nlp_generation.py` | Natural language to SPL generation | `generate_spl()` | — |
| `saved_searches.py` | Saved search analysis and optimization | `analyze_saved_searches()` | — |
| `splunk_integration.py` | Splunk API integration for the sidecar | `SplunkClient` | — |
| `config_manager.py` | Sidecar configuration management | `get_config()` | — |
| `spl_query_cli.py` | CLI tool for SPL analysis | `main()` | — |

---

## 18. Skills Plugins (`skills/`)

External skill packages loaded by `skills_manager.py`.

| Package | Purpose |
|---------|---------|
| `skills/spl_expert/` | SPL query writing and optimization |
| `skills/splunk_admin/` | Splunk administration tasks |
| `skills/troubleshooter/` | Error diagnosis and resolution |
| `skills/observability/` | Observability monitoring and alerting |
| `skills/cribl_expert/` | Cribl Stream/Edge configuration |
| `skills/data_engineer/` | Data pipeline design and management |
| `skills/security_ops/` | Security operations and threat hunting |
| `skills/knowledge_base/` | Knowledge base management and search |
| `skills/performance_optimizer/` | Performance tuning and optimization |
| `skills/deployment_manager/` | Deployment automation and rollback |
| `skills/report_builder/` | Report and dashboard generation |
| `skills/self_learner/` | Self-learning and knowledge acquisition |
| `skills/ansible_ops/` | Ansible playbook generation and execution |
| `skills/shell_scripting/` | Shell script generation and validation |
| `skills/python_scripting/` | Python script generation and validation |

---

## 19. CLI (`cli/`)

| Module | Purpose |
|--------|---------|
| `cli/obsai_cli.py` | Command-line interface for ObsAI management (health, ingest, config) |

---

## 20. Upgrade Readiness (`chat_app/upgrade_readiness/`)

Container-based Splunk upgrade testing system (v4.0). 12 modules, 233 tests.

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| `models.py` | Shared data models: `UpgradeResult`, `ConfDiff`, `CIMReport` | Dataclasses used across all modules |
| `baseline_builder.py` | Capture current Splunk config baseline (.conf files, apps, indexes) | `build_baseline()`, `snapshot_confs()` |
| `conf_differ.py` | Compare .conf files between Splunk versions | `diff_confs()`, `format_diff()` |
| `cim_analyzer.py` | Validate 15 CIM data models post-upgrade | `analyze_cim()`, `check_field_aliases()` |
| `dependency_tracer.py` | Map app and add-on dependencies | `trace_dependencies()`, `get_dep_graph()` |
| `impact_scorer.py` | Score upgrade impact across components (0–100) | `score_impact()`, `get_risk_breakdown()` |
| `container_tester.py` | Run upgrade in isolated Docker/Podman container | `run_upgrade_test()`, `verify_post_upgrade()` |
| `uf_analyzer.py` | Universal Forwarder upgrade path analysis | `analyze_uf()`, `get_uf_compatibility()` |
| `splunkbase_fetcher.py` | Check Splunkbase app compatibility for target version | `fetch_compatibility()`, `check_outdated()` |
| `report_builder.py` | Generate HTML/Markdown upgrade readiness report | `build_report()`, `export_html()` |

**Tests:** `tests/test_upgrade_readiness.py`, `tests/test_upgrade_cim_deps.py`, `tests/test_upgrade_sprint34.py` (233 total)

---

## 21. New Infrastructure Modules (v4.0)

| Module | Purpose | Key Functions | Runs When |
|--------|---------|---------------|-----------|
| `daily_evolution.py` | Daily self-assessment pipeline: staleness detection, target adjustment, agent ranking | `run_daily_evolution()`, `assess_staleness()` | Scheduled (daily) |
| `lesson_store.py` | Persistent store for lessons learned from executions and feedback | `store_lesson()`, `retrieve_lessons()`, `export()` | Post-execution, on feedback |
| `workflow_contracts.py` | Typed contracts for workflow inputs/outputs with validation | `WorkflowContract`, `validate_input()`, `validate_output()` | Workflow execution |
| `slo_gate.py` | SLO-based execution gating — blocks actions when SLOs are breached | `check_gate()`, `is_allowed()`, `get_gate_status()` | Before every tool execution |
| `activity_timeline.py` | Time-ordered activity feed for dashboard display | `record_activity()`, `get_timeline()` | Every significant action |

---

## Module Dependency Graph (Simplified)

```
User Message
    |
    v
app.py --> message_handler.py
               |
               +---> intent_classifier.py --> registry.py
               |
               +---> vectorstore_search.py --> vectorstore.py --> ChromaDB
               |         |
               |         +---> feedback_retriever.py
               |         +---> negative_feedback.py
               |
               +---> orchestration_strategies.py
               |         |
               |         +---> agent_dispatcher.py --> agent_catalog.py
               |         |                                 |
               |         |                                 +--> skill_executor.py --> skill_catalog.py
               |         |
               |         +---> workflow_orchestrator.py
               |         +---> director_graph.py
               |         +---> supervisor_agent.py
               |
               +---> context_builder.py
               +---> knowledge_graph.py
               +---> response_generator.py --> llm_utils.py --> Ollama
               +---> pipeline_lineage.py
               +---> otel_tracing.py
               +---> cost_tracker.py
```

---

## Scheduled Tasks

| Task | Module | Frequency | Resource Gate |
|------|--------|-----------|---------------|
| Health checks | `health_monitor.py` | Every 5 minutes | None |
| Auto-heal | `resource_manager.py` | Every 5 minutes | None |
| Idle self-improvement | `idle_worker.py` | When idle | CPU < 80% |
| Proactive monitoring | `proactive_monitor.py` | Periodic | None |
| Q&A generation | `self_learning.py` | Hourly | `can_run_heavy_task()` |
| Answer reassessment | `self_learning.py` | Daily | `can_run_heavy_task()` |
| Evolution assessment | `evolution_engine.py` | Daily | `can_run_heavy_task()` |
| Model customization | `self_learning.py` | Monthly | `can_run_heavy_task()` |

---

## 8. Enterprise Security & Governance

Modules added in v4.0 for enterprise production readiness.

| Module | Purpose | Key Functions | Runs When | Lines |
|--------|---------|---------------|-----------|-------|
| `audit_log.py` | Immutable hash-chained audit log with JSONL persistence | `append()`, `verify_chain()`, `query()`, `export()` | Every config/security change | ~310 |
| `rbac.py` | Fine-grained RBAC — per-tool, per-collection, per-resource permissions | `check_permission()`, `require_permission()`, `set_user_overrides()` | Every API request | ~260 |
| `error_taxonomy.py` | 37 standardized error codes with message templates and remediation | `raise_error()`, `get_error_catalog()` | Every error response | ~280 |
| `circuit_breaker.py` | Auto-disable failing tools with cooldown recovery | `allow_request()`, `record_success()`, `record_failure()` | Every tool execution | ~200 |
| `safety_policies.py` | Per-tool safety levels with environment-aware enforcement | `evaluate_policy()`, `get_tool_safety_level()` | Before tool execution | ~220 |
| `idempotency.py` | Idempotency keys + dry-run framework to prevent duplicate execution | `get()`, `put()`, `mark_in_progress()`, `DryRunResult` | Write tool execution | ~200 |
| `latency_budgets.py` | Per-tool timeouts with p50/p95/p99 percentile tracking | `get_timeout()`, `record()`, `get_violations()` | Every tool execution | ~230 |
| `slo_tracker.py` | 8 SLOs across 4 categories with red/yellow/green dashboard | `record()`, `evaluate()`, `get_dashboard()` | Continuous | ~260 |
| `cost_tracker.py` | Per-user LLM token, retrieval, and tool cost tracking | `record()`, `record_retrieval()`, `get_dashboard()` | Every LLM/retrieval/tool call | ~170 |
| `runbooks.py` | 8 built-in runbooks linking alerts to diagnostic/fix steps | `get_for_alert()`, `search()` | Alert/health check failures | ~250 |
| `data_governance.py` | Retention policies, PII detection, redaction rules, compliance | `scan_for_pii()`, `redact_pii()`, `get_compliance_report()` | Data handling, compliance checks | ~280 |
| `policy_engine.py` | OPA-style declarative policy rules for RBAC, approvals, env constraints | `evaluate()`, `add_rule()`, `get_all_rules()` | Before tool execution | ~270 |
| `approval_workflows.py` | Multi-step approval chains with change windows and delegation | `create_workflow()`, `approve_step()`, `deny_step()` | High-risk actions | ~280 |
| `secrets_manager.py` | Secret registration, rotation tracking, plaintext detection | `get_rotation_report()`, `scan_for_plaintext()` | Startup, admin checks | ~240 |
| `credential_scoping.py` | Least-privilege connectors — scoped credentials per action | `get_credential()`, `get_connector_health()` | External service calls | ~230 |
| `self_evaluation.py` | Confidence scoring per response with grounding levels | `evaluate()`, `get_stats()` | Every response generation | ~250 |
| `mfa.py` | TOTP-based MFA with backup codes and enforcement policies | `enroll()`, `verify()`, `is_required()` | Admin login | ~240 |
| `tenant_quotas.py` | Per-tenant resource quotas (tokens, API calls, storage) | `record_usage()`, `check_quota()`, `get_tenant_usage()` | Every resource usage | ~200 |
| `tenant_isolation.py` | Tenant scoping for collections, config, credentials | `scope_collection()`, `get_context()`, `export_tenant()` | Multi-tenant requests | ~250 |
| `persona_orchestration.py` | Match user personas with agent personas for optimal routing | `match()`, `score_agent()`, `recommend_strategy()` | Agent dispatch | ~230 |
| `toolformer.py` | Decide when to call tools vs answer from knowledge | `should_use_tools()`, `record_outcome()` | Every query (pre-tool) | ~230 |
| `scim.py` | SCIM 2.0 user provisioning endpoints (Okta/Azure AD compatible) | `create()`, `update()`, `list_users()` | IdP sync | ~280 |
| `doc_generator.py` | Generate Markdown/SharePoint docs from text, directories, zip files | `from_snippets()`, `from_directory()`, `from_zip()` | /doc command, MCP tool | ~400 |
| `pipeline_models.py` | Dataclass models replacing tuple returns in message_handler | `RetrievalResult`, `LLMContextResult`, `BuildLLMContextRequest` | Pipeline stages | ~60 |
| `admin_security_routes.py` | 80+ API endpoints for all enterprise security features | audit, RBAC, errors, circuits, SLOs, costs, runbooks, governance, policies, approvals, secrets, MFA, tenants, docs | Admin API | ~1000 |

---

## 9. MCP Tools (36 total)

| Category | Tools | Min Role |
|----------|-------|----------|
| **Core SPL** | search, ask, validate_spl, explain_spl, generate_spl, optimize_spl, run_search | USER-ANALYST |
| **Knowledge** | kg_query, deep_search, reason, compare, spec_lookup | USER |
| **Scripting** | ansible, shell_script, python_script | USER |
| **Utilities** | encode_decode, hash, transform_data, text_tools, spl_tools, validate_conf | VIEWER |
| **Admin** | health, config_diff, config_update, container_action, manage_collection, ingest, build_config | VIEWER-ADMIN |
| **Operations** | analyze_confs, generate_docs, security_audit, manage_learning, orchestrate, agent_dispatch, inventory | USER-ANALYST |

---

## 10. Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_audit_log.py` | 21 | Hash chaining, persistence, tamper detection, export |
| `test_rbac.py` | 20 | Permissions, wildcards, role inheritance, overrides |
| `test_error_taxonomy.py` | 12 | Error codes, templates, retry policy |
| `test_circuit_breaker.py` | 15 | State transitions, cooldown, recovery |
| `test_safety_policies.py` | 22 | Safety levels, environments, dry-run |
| `test_idempotency.py` | 18 | Key store, TTL, in-progress claims |
| `test_latency_budgets.py` | 23 | Timeouts, percentiles, violations |
| `test_slo_tracker.py` | 13 | SLO evaluation, dashboard, error budgets |
| `test_cost_tracker_ext.py` | 7 | Retrieval/tool tracking, dashboard |
| `test_runbooks.py` | 15 | Runbook lookup, search, registration |
| `test_data_governance.py` | 28 | PII detection, redaction, retention |
| `test_policy_engine.py` | 15 | Policy evaluation, custom rules |
| `test_approval_workflows.py` | 16 | Multi-step approval, change windows |
| `test_secrets_manager.py` | 19 | Rotation, plaintext detection |
| `test_credential_scoping.py` | 15 | Scope mapping, fallback, tracking |
| `test_self_evaluation.py` | 14 | Confidence scoring, grounding |
| `test_mfa.py` | 22 | TOTP, backup codes, policies |
| `test_tenant_quotas.py` | 18 | Quotas, enforcement, tracking |
| `test_persona_orchestration.py` | 16 | Affinity matrix, strategy matching |
| `test_tenant_isolation.py` | 18 | Collection scoping, export/import |
| `test_chaos.py` | 20 | Circuit breaker storms, RBAC edge cases |
| `test_golden_answers.py` | 43 | Safety, RBAC, error codes, latency, runbooks |
| `test_toolformer.py` | 16 | Tool decisions, complexity, learning |
| `test_pipeline_dataclasses.py` | 7 | RetrievalResult, LLMContextResult |
| `test_scim.py` | 19 | SCIM CRUD, filtering, persistence |
| `test_persona_enhancements.py` | 12 | Skill priorities, approval bypass, versioning |
| `test_doc_generator.py` | 28 | Snippets, directory scan, zip, SharePoint |
| `test_mcp_coverage.py` | 28 | Tool registration, schemas, handler resolution |
| **Total new** | **516** | Enterprise security + governance + ops |
