# ObsAI Admin API Reference

Base URL: `/api/admin` (all endpoints below are relative to this prefix unless noted).

Authentication: JWT via `access_token` cookie. Authentication defaults to enabled (fail-closed). When disabled in development, anonymous access is granted with VIEWER role (read-only). In production/staging, authentication cannot be disabled. Role-based access control enforces ADMIN/ANALYST/USER/VIEWER per endpoint.

---

## 1. Health & Status

These routes are mounted at the **root** level (no `/api/admin` prefix).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/live` | Liveness probe. Returns `{"status":"alive","uptime_seconds":N}` |
| GET | `/ready` | Readiness probe. Returns 200 when Ollama + ChromaDB are connected, 503 otherwise |

| Method | Path | Description |
|--------|------|-------------|
| GET | `/version` | Current and latest version info |
| GET | `/version/changelog` | Recent commit history |
| GET | `/whoami` | Current user identity and role (public, no auth required) |

---

## 2. Dashboard & Activity

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Aggregated dashboard data (stats, charts, recent activity) |
| GET | `/activity` | User activity data |
| GET | `/telemetry/report` | Search telemetry report |

---

## 3. Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | All current settings grouped by section |
| PATCH | `/settings/{section}` | Update settings for a section. Body: `{"values": {...}}` |
| GET | `/settings/history` | Config change audit trail |

---

## 4. Config Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/config` | Full config.yaml content |
| GET | `/config/sections` | List all config sections with metadata |
| GET | `/config/section/{section}` | Get a specific config section |
| PATCH | `/config/section/{section}` | Update a config section (merge). Body: `{...values, auto_restart?: bool}` |
| PUT | `/config/section/{section}` | Replace a config section entirely |
| POST | `/config/backup` | Create a config backup |
| GET | `/config/backups` | List config backups |
| POST | `/config/restore` | Restore config from backup. Body: `{"filename": "..."}` |
| GET | `/config/versions` | List config change history |
| GET | `/config/versions/{commit_id}` | Get a specific config commit |
| POST | `/config/rollback/{commit_id}` | Rollback config to a specific commit |

### Config Sub-Sections (GET only)

| Path | Description |
|------|-------------|
| `/config/profiles` | List deployment profiles |
| `/config/profiles/{name}` | Get a specific profile |
| `/config/directories` | Directory configuration |
| `/config/database` | Database configuration |
| `/config/ingestion` | Ingestion configuration |
| `/config/retrieval` | Retrieval configuration |
| `/config/prompts-config` | Prompt configuration |
| `/config/ui` | UI configuration |
| `/config/security` | Security configuration |
| `/config/features` | Feature flags from config.yaml |
| `/config/mcp-gateway` | MCP gateway configuration |
| `/config/sharepoint` | SharePoint ingestion config |
| `/config/github` | GitHub ingestion config |
| `/config/organization` | Organization-specific config |

### Config Profiles

| Method | Path | Description |
|--------|------|-------------|
| POST | `/config/profiles/switch` | Switch active deployment profile. Body: `{"name": "..."}` |
| PATCH | `/config/profiles/{name}` | Update a profile |

### Organization Mappings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/config/organization/index-mappings` | Get index mappings |
| PATCH | `/config/organization/index-mappings` | Update index mappings |
| GET | `/config/organization/field-mappings` | Get field mappings |
| PATCH | `/config/organization/field-mappings` | Update field mappings |

### MCP Servers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/config/mcp-gateway/servers` | List MCP servers from config |
| GET | `/mcp/servers` | List MCP servers (compatibility alias) |
| POST | `/config/mcp-gateway/servers` | Add MCP server. Body: `{"name":"...","url":"..."}` |
| DELETE | `/config/mcp-gateway/servers/{name}` | Remove MCP server |

---

## 5. Users & Auth

| Method | Path | Description |
|--------|------|-------------|
| GET | `/users` | List all users |
| POST | `/users` | Create a user |
| PUT | `/users/{username}` | Update a user |
| DELETE | `/users/{username}` | Delete a user |
| GET | `/users/{username}/activity` | User activity log |
| GET | `/roles` | List all roles |
| POST | `/roles` | Create a custom role |
| DELETE | `/roles/{role_name}` | Delete a custom role |
| GET | `/tokens` | List active API tokens |
| POST | `/tokens` | Create a new API token |
| DELETE | `/tokens/{token_id}` | Revoke an API token |
| GET | `/auth/providers` | List configured auth providers |
| GET | `/auth/oidc/login-url` | Get OIDC login URL |
| POST | `/auth/oidc/callback` | Handle OIDC callback (public) |

---

## 6. LLM

| Method | Path | Description |
|--------|------|-------------|
| GET | `/llm` | LLM configuration and available models |
| PATCH | `/llm` | Update LLM configuration. Body: flat fields (`{"model":"...","temperature":0.7}`) |
| GET | `/llm/providers` | List LLM providers |
| GET | `/llm/recommend` | Get model recommendation for a task. Query: `?task=...` |

---

## 7. Features

| Method | Path | Description |
|--------|------|-------------|
| GET | `/features` | List all feature flags with current state |
| PUT | `/features/{feature}` | Toggle a feature flag. Body: `{"enabled": true}` |
| POST | `/features/reload` | Reload feature flags from config.yaml |

---

## 8. Containers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/containers` | List container/service status |
| POST | `/containers/action` | Manage a container. Body: `{"service":"...","action":"start|stop|restart"}` |
| POST | `/containers/rebuild-all` | Rebuild and restart all services |
| POST | `/containers/build` | Build container images |
| GET | `/containers/{service}/health` | Per-service health probe |
| GET | `/containers/runtime` | Container runtime info (podman/docker, version) |

---

## 9. Collections (Vector Store)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/collections` | List vector store collections with stats |
| POST | `/collections/action` | Manage a collection. Body: `{"name":"...","action":"delete|optimize"}` |
| POST | `/collections/reindex` | Delete all collections and re-ingest |
| GET | `/collections/reindex/status` | Check reindex progress |
| POST | `/collections/search` | Search chunks across collections. Body: `{"query":"...","collection?":"...","limit?":10}` |
| GET | `/collections/{name}/chunks` | Browse chunks in a collection. Query: `?limit=&offset=` |
| GET | `/collections/{name}/facets` | Get distinct metadata values for filtering |
| DELETE | `/collections/chunks` | Delete specific chunks. Body: `{"collection":"...","ids":[...]}` |
| POST | `/collections/backup` | Backup all ChromaDB collections |
| GET | `/collections/backups` | List collection backups |
| POST | `/collections/restore` | Restore collections from backup |

---

## 10. Knowledge Graph

| Method | Path | Description |
|--------|------|-------------|
| GET | `/knowledge-graph/stats` | Graph statistics (node/edge counts by type) |
| GET | `/knowledge-graph/entities` | Browse entities by type. Query: `?type=Command&limit=50` |
| GET | `/knowledge-graph/entity/{entity_id}` | Get entity details and relationships |
| GET | `/knowledge-graph/graph` | Graph visualization data (nodes + edges) |
| GET | `/knowledge-graph/query` | Query the knowledge graph. Query: `?q=...` |
| POST | `/knowledge-graph/rebuild` | Rebuild the knowledge graph from sources |

---

## 11. Orchestration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/orchestration/strategies` | List available orchestration strategies |
| GET | `/orchestration/stats` | Orchestration execution statistics |
| POST | `/orchestration/strategy` | Change default strategy. Body: `{"strategy":"adaptive"}` |
| GET | `/orchestration/quality` | Strategy quality metrics |
| POST | `/orchestration/reset-stats` | Reset orchestration quality stats |
| POST | `/orchestration/test` | Run a test orchestration query |

---

## 12. Skills & Agents

### Skills

| Method | Path | Description |
|--------|------|-------------|
| GET | `/skills` | List all installed skills |
| GET | `/skills/discover` | Discover available skills |
| POST | `/skills/{name}/install` | Install a skill |
| POST | `/skills/{name}/uninstall` | Uninstall a skill |
| PUT | `/skills/{name}/toggle` | Enable or disable a skill |
| GET | `/skills/metrics` | Skill execution metrics |
| GET | `/skills/execution-metrics` | Skill executor performance metrics |
| GET | `/marketplace` | Browse skill marketplace |
| GET | `/api-catalog` | All available API operations (133 skills) |

### Agent Catalog

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agent-catalog` | Full agent catalog |
| GET | `/agent-catalog/roles` | List agent roles |
| GET | `/agent-catalog/role/{role}` | Get agent by role |
| GET | `/agent-catalog/department/{department}` | Get agents by department |
| GET | `/agent-catalog/search` | Search agents. Query: `?q=...` |
| GET | `/agent-catalog/intent/{intent}` | Get agents for an intent |
| GET | `/agent-catalog/best/{intent}` | Get best agent for an intent |

### Agentic Execution

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agentic/status` | Agentic execution layer status |
| GET | `/agentic/available-skills` | Available skills for execution |
| GET | `/agentic/skills-for-intent/{intent}` | Skills matching an intent |
| GET | `/agentic/execution-log` | Execution log. Query: `?limit=50` |
| GET | `/agentic/dispatch-log` | Dispatch log. Query: `?limit=50` |
| GET | `/agentic/agent-metrics` | Per-agent metrics |
| GET | `/agentic/workflows` | Workflow status |
| GET | `/agentic/resolve-handler/{handler_key}` | Resolve a handler key to execution path |
| GET | `/agentic/select-agent/{intent}` | Select agent for intent. Query: `?query=...` |
| POST | `/agentic/dispatch` | Dispatch a query to the best agent. Body: `{"query":"..."}` |
| POST | `/agentic/execute-skill` | Execute a single skill |
| GET | `/agents/metrics` | Per-agent performance metrics |
| GET | `/agents/metrics/{agent_name}` | Detailed metrics for one agent |

---

## 13. Ingestion

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingestion/trigger` | Trigger document ingestion |
| GET | `/ingestion/status` | Ingestion pipeline status |
| GET | `/ingestion/stats` | Incremental ingestion statistics |
| GET | `/uploads` | List configured upload directories and recent uploads |
| POST | `/uploads/ingest` | Trigger ingestion from a directory. Body: `{"directory":"..."}` |

---

## 14. Observability & Monitoring

### Observability

| Method | Path | Description |
|--------|------|-------------|
| GET | `/observability` | Aggregated observability data |
| GET | `/observability-summary` | Quick observability summary |
| GET | `/observability/dashboard` | Unified observability dashboard |
| GET | `/observability/alerts/active` | Active alerts within time window |
| GET | `/observability/slos/status` | All SLO statuses |

### Monitoring

| Method | Path | Description |
|--------|------|-------------|
| GET | `/monitoring/realtime` | Real-time monitoring dashboard data |
| POST | `/monitoring/log-level` | Change runtime log level. Body: `{"level":"DEBUG"}` |
| GET | `/monitoring/pipeline-traces` | Pipeline trace history |
| GET | `/monitoring/pipeline-traces/{request_id}` | Specific pipeline trace |

### OTel Traces

| Method | Path | Description |
|--------|------|-------------|
| GET | `/otel/traces` | List recent OTel traces |
| GET | `/otel/traces/{trace_id}` | All spans for a specific trace |
| GET | `/otel/spans` | List raw spans (most recent first) |
| GET | `/otel/status` | OpenTelemetry tracing status |

### Execution Journal

| Method | Path | Description |
|--------|------|-------------|
| GET | `/execution-journal/files` | List journal files |
| GET | `/execution-journal/query` | Query journal entries |
| GET | `/execution-journal/stats` | Journal statistics |

### Pipeline Lineage

| Method | Path | Description |
|--------|------|-------------|
| GET | `/pipeline-lineage/{request_id}` | Get lineage trace for a request |

---

## 15. Backup & Audit

| Method | Path | Description |
|--------|------|-------------|
| POST | `/backup/unified` | Create unified backup (config + collections + state) |
| GET | `/backup/all` | List all backups |
| POST | `/backup/restore-state` | Restore application state |
| GET | `/export/audit-trail` | Export audit trail as JSON or CSV. Query: `?format=json|csv` |
| GET | `/export/metrics` | Export observability metrics as JSON |
| GET | `/export/agent-assessment` | Export agent skill resolution report |

---

## 16. Prompts

| Method | Path | Description |
|--------|------|-------------|
| GET | `/prompts` | List all prompt templates with metadata |
| PUT | `/prompts/{name}` | Update a prompt template. Body: `{"content":"..."}` |
| GET | `/prompt-templates` | List all prompt templates (versioned) |
| GET | `/prompt-templates/{template_id}` | Get prompt template by ID |
| POST | `/prompt-templates` | Create a new prompt template |
| PUT | `/prompt-templates/{template_id}` | Update prompt template |
| GET | `/prompt-templates/{template_id}/versions` | Version history for a template |

---

## 17. Learning & Evolution

### Learning

| Method | Path | Description |
|--------|------|-------------|
| GET | `/learning/dashboard` | Learning process visibility (cycle stats, quality trends) |
| POST | `/learn/trigger` | Trigger a learning cycle |

### Evolution Engine

| Method | Path | Description |
|--------|------|-------------|
| GET | `/evolution/status` | Evolution engine status |
| GET | `/evolution/targets` | Adaptive quality targets |
| GET | `/evolution/staleness` | Component staleness report |
| GET | `/evolution/diagnosis` | Root cause diagnosis |
| GET | `/evolution/strategy-matrix` | Strategy payoff matrix |
| GET | `/evolution/agent-rankings` | Agent competition rankings |
| GET | `/evolution/improvements` | Improvement action queue |
| POST | `/evolution/assess` | Trigger evolution assessment |

### GCI (Global Continuous Improvement)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/gci/status` | GCI agent status |
| GET | `/gci/agent-trends` | Per-agent quality trends |
| GET | `/gci/directives` | Improvement directives |
| GET | `/gci/trend-reports` | GCI trend reports |
| GET | `/gci/interactions` | Recent interactions with quality scores |

---

## 18. Cache

| Method | Path | Description |
|--------|------|-------------|
| GET | `/cache/stats` | Cache statistics |
| POST | `/cache/search` | Search cache keys. Body: `{"pattern":"..."}` |
| POST | `/cache/invalidate` | Invalidate cache keys by pattern. Body: `{"pattern":"..."}` |
| POST | `/cache/clear` | Clear all cache |

---

## 19. SSL & Networking

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ssl/status` | Current SSL configuration and certificate status |
| POST | `/ssl/upload-cert` | Upload SSL certificate or key file |
| POST | `/ssl/generate-self-signed` | Generate self-signed SSL certificate |
| PATCH | `/ssl/toggle` | Enable or disable SSL |
| GET | `/ports` | Get port configuration |
| PATCH | `/ports` | Save port configuration |
| POST | `/network/test` | Run connectivity test to a host/port |
| GET | `/network/dns` | DNS lookup for a hostname |

---

## 37. Upgrade Readiness

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upgrade/analyze` | Analyze upgrade path. Body: `{"current_version":"9.1.0","target_version":"9.3.0"}` |
| GET | `/upgrade/analyze/{job_id}` | Get analysis job status and results |
| POST | `/upgrade/test` | Run container-based upgrade test. Body: `{"test_type":"container","target_version":"9.3.0"}` |
| GET | `/upgrade/test/{job_id}` | Get container test status and results |
| GET | `/upgrade/report/{job_id}` | Download upgrade readiness report (HTML or Markdown) |
| POST | `/upgrade/baseline` | Capture current Splunk configuration baseline |
| GET | `/upgrade/baseline` | Get most recent baseline snapshot |
| GET | `/upgrade/cim` | Run CIM data model compatibility check |
| POST | `/upgrade/uf-analyze` | Analyze Universal Forwarder upgrade path |
| GET | `/upgrade/history` | List previous upgrade analyses |
| DELETE | `/upgrade/history/{job_id}` | Delete a completed upgrade analysis |

---

## 20. Feedback

| Method | Path | Description |
|--------|------|-------------|
| GET | `/feedback` | User feedback and feature requests |
| POST | `/feedback/feature-request` | Submit a feature request |
| GET | `/feedback/feature-requests` | List feature requests |

---

## 21. Workflows

| Method | Path | Description |
|--------|------|-------------|
| GET | `/workflows/history` | Persisted workflow history |
| POST | `/workflows/recover` | Recover interrupted workflows |
| POST | `/workflows/{workflow_id}/pause` | Pause a running workflow |
| POST | `/workflows/{workflow_id}/resume` | Resume a paused workflow |
| GET | `/workflows/templates` | List workflow templates |
| POST | `/workflows/templates` | Save new workflow template |
| PUT | `/workflows/templates/{template_id}` | Update workflow template |
| DELETE | `/workflows/templates/{template_id}` | Delete workflow template |
| POST | `/workflows/execute` | Execute a workflow from canvas |
| GET | `/workflows/arcs` | List workflow arcs for a user |
| GET | `/workflows/suggestions` | Get pickup suggestions for a user |

---

## 22. Action Engine & Director Graph

| Method | Path | Description |
|--------|------|-------------|
| GET | `/action-engine/status` | Action engine status and action types |
| GET | `/action-engine/history` | Recent action engine executions |
| GET | `/director-graph/templates` | List director graph templates |
| GET | `/director-graph/visualize/{template_name}` | Get graph structure for visualization |

---

## 23. Approvals

| Method | Path | Description |
|--------|------|-------------|
| GET | `/approvals` | Get pending action approvals |
| POST | `/approvals/{approval_id}/approve` | Approve a pending action |
| POST | `/approvals/{approval_id}/deny` | Deny a pending action |

---

## 24. Idle Worker

| Method | Path | Description |
|--------|------|-------------|
| GET | `/idle-worker` | Idle worker status |
| GET | `/idle-worker/status` | Idle worker status (alias) |
| PATCH | `/idle-worker` | Configure idle worker |
| POST | `/idle-worker/trigger` | Trigger idle worker cycle manually |

---

## 25. API Services

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api-services/catalog` | API services catalog |
| POST | `/api-services/manage/{service_id}` | Enable/disable an API service |
| POST | `/api-services/manage-bulk` | Bulk enable/disable API services |
| GET | `/api-services/usage` | API services usage stats |

---

## 26. Splunkbase

| Method | Path | Description |
|--------|------|-------------|
| GET | `/splunkbase/catalog` | Splunkbase catalog summary |
| GET | `/splunkbase/apps` | All Splunkbase apps from catalog |
| GET | `/splunkbase/outdated` | Outdated Splunk apps |
| POST | `/splunkbase/refresh` | Trigger Splunkbase catalog refresh |
| POST | `/splunkbase/compare` | Upload CSV/Excel of installed apps and compare |

---

## 27. Tools

| Method | Path | Description |
|--------|------|-------------|
| POST | `/tools/network-test` | Run network diagnostic |
| POST | `/tools/syslog-test` | Compose and optionally send syslog events |
| POST | `/tools/regex-ai` | AI-powered regex assessment and suggestions |
| POST | `/tools/regex-generate` | Generate regex from selected text using AI |
| POST | `/tools/fs-monitor` | Monitor filesystem paths |
| POST | `/tools/ai-chat` | AI assistant for tools pages |
| POST | `/tools/transform-ai` | AI suggest data transformation chain |
| POST | `/tools/ansible-validate` | Validate an Ansible playbook |
| POST | `/tools/ansible-analyze` | Analyze an Ansible playbook |
| POST | `/tools/ansible-generate` | Generate Ansible playbook from description |
| POST | `/tools/shell-analyze` | Analyze a shell script |
| POST | `/tools/shell-generate` | Generate shell script from description |
| POST | `/tools/python-analyze` | Analyze a Python script |
| POST | `/tools/python-generate` | Generate Python script from description |
| POST | `/tools/update-saved-search` | Update an existing Splunk saved search |
| POST | `/tools/create-knowledge-object` | Create a Splunk knowledge object |
| POST | `/utilities/{operation}` | Execute a utility operation (35 operations: encoding, hashing, transforms) |

---

## 28. Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/analytics/taxonomy` | Question taxonomy breakdown |
| GET | `/analytics/gaps` | Knowledge gap detection |
| GET | `/analytics/adoption` | Adoption metrics |
| GET | `/analytics/roi` | ROI estimate |

---

## 29. Costs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/costs` | LLM cost summary |
| GET | `/costs/daily` | Daily cost trend |
| GET | `/costs/by-user` | Per-user cost breakdown |

---

## 30. Conversations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/conversations/share` | Share a conversation with another user |
| GET | `/conversations/shared` | List conversations shared with current user |
| GET | `/conversations/shared/{thread_id}` | Get a shared conversation |

---

## 31. User Profiles

| Method | Path | Description |
|--------|------|-------------|
| GET | `/user-profiles` | List all user learning profiles |
| GET | `/user-profiles/{user_id}` | Get a specific user learning profile |

---

## 32. MCP Server Mode

| Method | Path | Description |
|--------|------|-------------|
| GET | `/mcp/server/capabilities` | MCP server capability manifest |
| POST | `/mcp/server/tool-call` | Test MCP tool call |

---

## 33. A2A Protocol

| Method | Path | Description |
|--------|------|-------------|
| GET | `/a2a/agents` | List A2A agent cards |
| POST | `/a2a/task` | Execute A2A task |

---

## 34. Guardrails

| Method | Path | Description |
|--------|------|-------------|
| GET | `/guardrails/stats` | Guardrail event statistics |
| POST | `/guardrails/test` | Test guardrails on sample text |

---

## 35. Archival Memory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/memory/archival/stats` | Archival memory statistics |
| GET | `/memory/archival/search` | Search archival memory. Query: `?q=...` |
| POST | `/memory/archival/store` | Store a memory note |

---

## 36. Commands & Docs

| Method | Path | Description |
|--------|------|-------------|
| POST | `/execute-command` | Execute a slash command programmatically |
| GET | `/docs/data` | Structured documentation data for admin UI (public) |
| GET | `/commands-data` | Public commands and tools data (public) |
| GET | `/agent-tasks` | List agent task types and status |

---

## Public Routes (no auth required)

These endpoints share the `/api/admin` prefix but do not require authentication:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/whoami` | Current user identity |
| GET | `/docs` | Documentation page |
| GET | `/v2` | React admin console |
| GET | `/commands` | Interactive commands page |
| GET | `/tools/{tool_name}` | Tool-specific pages |
| GET | `/commands-data` | Commands and tools data |
| GET | `/docs/data` | Documentation data |
| POST | `/auth/oidc/callback` | OIDC callback handler |
