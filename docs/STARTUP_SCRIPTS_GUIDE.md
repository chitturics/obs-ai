# Startup Scripts Guide

This guide explains when to use each startup script for the Chainlit Splunk Assistant.

## Available Startup Scripts

### 1. `start_all_optimized.sh` - **RECOMMENDED FOR DEV/TEST**

**Location:** `docker_files/start_all_optimized.sh`

**When to use:**
- Local development environment
- Testing and iterating on code changes
- When you need quick startup times (30-50% faster)
- When you want fine-grained control (flags for skipping ingestion, force recreate)

**Features:**
- ✅ Parallel model pulling (downloads both models simultaneously)
- ✅ Parallel health checks (faster service readiness detection)
- ✅ Auto-detection of dev vs production environment
- ✅ Container reuse (starts existing containers if available)
- ✅ Optional flags: `--no-ingest`, `--force-recreate`
- ✅ GPU auto-detection (NVIDIA/AMD/Intel)
- ✅ Reduced redundant docker ps calls
- ✅ Better error handling with cleanup on failure

**Directory structure:**
- Auto-detects `/opt/obsai/chatapp` for production
- Falls back to current directory for dev
- Uses `$DOCUMENTS_ROOT` for documents (default: `/opt/obsai/documents` or `$PROJECT_ROOT/documents`)

**Example usage:**
```bash
# Standard startup
bash docker_files/start_all_optimized.sh

# Skip document ingestion (faster startup)
bash docker_files/start_all_optimized.sh --no-ingest

# Force recreate all containers
bash docker_files/start_all_optimized.sh --force-recreate

# Both flags
bash docker_files/start_all_optimized.sh --force-recreate --no-ingest
```

**Typical startup time:** 60-90 seconds (without ingestion), 3-5 minutes (with ingestion)

---

### 2. `start_production_final.sh` - **RECOMMENDED FOR PRODUCTION**

**Location:** `docker_files/start_production_final.sh`

**When to use:**
- Production deployments on `/opt/obsai/chatbot`
- When you need strict permission controls (SELinux environments)
- When you want all writable data in named volumes (no bind mount permission issues)
- Initial setup or after major updates

**Features:**
- ✅ Strict directory structure validation
- ✅ All writable data in named volumes (no bind mount issues)
- ✅ Read-only mounts for documents (security hardening)
- ✅ SELinux-compatible (`:ro,z` flags for read-only, volumes for writable)
- ✅ PostgreSQL init script validation
- ✅ Ollama uses internal volume (no bind mount for models)
- ✅ Detailed logging and error messages

**Directory structure (STRICT):**
```
/opt/obsai/chatbot/
├── app/                      # Application code
│   └── postgres/
│       └── init_chainlit_schema.sql  # REQUIRED
├── documents/                # All documents (READ-ONLY)
│   ├── specs/
│   ├── commands/
│   ├── pdfs/
│   ├── repo/
│   └── feedback/
└── logs/                     # For ingestion logs
```

**Volumes created (writable):**
- `postgres_data` - Database
- `chroma_data` - Vector store
- `chainlit_runtime` - Chainlit .chainlit directory
- `user_feedback` - User feedback files
- `ollama_models` - LLM models (internal, not mounted)

**Example usage:**
```bash
# Standard production startup
bash docker_files/start_production_final.sh

# Skip ingestion (restart without re-ingesting)
bash docker_files/start_production_final.sh --no-ingest

# Force recreate (nuclear option)
bash docker_files/start_production_final.sh --force-recreate
```

**Typical startup time:** 90-120 seconds (without ingestion), 5-10 minutes (with initial model downloads)

**Important notes:**
- First run will download models into internal volume (10-15 minutes)
- Models persist in `ollama_models` volume between restarts
- All documents must be under `/opt/obsai/chatbot/documents/`
- PostgreSQL init script must exist at `/opt/obsai/chatbot/app/postgres/init_chainlit_schema.sql`

---

### 3. `start_all.sh` - **LEGACY (Deprecated)**

**Location:** `docker_files/start_all.sh`

**Status:** Deprecated - use `start_all_optimized.sh` instead

**Why deprecated:**
- No parallel health checks (slower startup)
- No container reuse (always creates new containers)
- No optimization flags
- Less flexible directory handling

**Migration:**
```bash
# Old:
bash docker_files/start_all.sh

# New:
bash docker_files/start_all_optimized.sh
```

---

### 4. `start_all_production.sh` - **LEGACY (Deprecated)**

**Location:** `docker_files/start_all_production.sh`

**Status:** Deprecated - use `start_production_final.sh` instead

**Why deprecated:**
- Less strict directory validation
- Mixed bind mounts and volumes (permission issues)
- Ollama bind mount causes permission errors in some environments

**Migration:**
```bash
# Old:
bash docker_files/start_all_production.sh

# New:
bash docker_files/start_production_final.sh
```

---

## Decision Tree

```
Do you have /opt/obsai/chatbot directory structure?
│
├─ YES → Production environment
│   │
│   ├─ First time setup? → start_production_final.sh
│   ├─ Regular restart? → start_production_final.sh --no-ingest
│   └─ Fixing issues? → start_production_final.sh --force-recreate
│
└─ NO → Development/Test environment
    │
    ├─ Quick iteration? → start_all_optimized.sh --no-ingest
    ├─ Full test? → start_all_optimized.sh
    └─ Clean slate? → start_all_optimized.sh --force-recreate
```

---

## Comparison Table

| Feature | start_all_optimized.sh | start_production_final.sh |
|---------|------------------------|---------------------------|
| **Environment** | Dev/Test | Production |
| **Startup Speed** | Fast (60-90s) | Moderate (90-120s) |
| **Directory Structure** | Flexible | Strict (/opt/obsai/chatbot) |
| **Writable Mounts** | Bind mounts OK | Named volumes only |
| **SELinux Compatibility** | Basic | Full (`:ro,z` flags) |
| **Container Reuse** | Yes | Yes |
| **Parallel Operations** | Yes | No |
| **GPU Detection** | Yes | Yes |
| **Flags** | --no-ingest, --force-recreate | --no-ingest, --force-recreate |
| **Validation** | Minimal | Strict (checks all dirs) |
| **Ollama Models** | Bind mount | Internal volume |

---

## Environment Variables

Both scripts support these environment variables:

```bash
# LLM Configuration
export APP_OLLAMA_MODEL="qwen2.5:3b"          # or deepseek-r1:14b
export APP_OLLAMA_EMBED="mxbai-embed-large"  # or nomic-embed-text

# Profile Selection
export ACTIVE_PROFILE="LLM_LITE"  # LLM_LITE, LLM_FAST, LLM_FULL

# Directory Overrides (for testing)
export PROJECT_ROOT_OVERRIDE="/custom/path"
export DOCUMENTS_ROOT_OVERRIDE="/custom/docs"
```

---

## Troubleshooting

### "Permission denied" errors in production
- **Solution:** Use `start_production_final.sh` (volumes instead of bind mounts)
- **Why:** SELinux blocks writes to bind-mounted directories

### Slow startup
- **Solution:** Use `start_all_optimized.sh` with `--no-ingest` flag
- **Why:** Document ingestion can take 3-5 minutes

### "Directory not found" errors
- **Solution:** Check directory structure matches script requirements
- **Why:** Production script requires strict `/opt/obsai/chatbot` structure

### Containers not starting
- **Solution:** Use `--force-recreate` flag
- **Why:** Orphaned containers may conflict with names

### Models downloading every restart
- **If using start_production_final.sh:** Models persist in `ollama_models` volume (check: `docker volume ls`)
- **If using start_all_optimized.sh:** Check `$PROJECT_ROOT/llms` directory exists

---

## Best Practices

### Development
1. Use `start_all_optimized.sh --no-ingest` for quick iterations
2. Run full ingestion periodically: `start_all_optimized.sh`
3. Force recreate when debugging: `start_all_optimized.sh --force-recreate`

### Production
1. Initial setup: `start_production_final.sh` (allow 10-15 minutes for model downloads)
2. Regular restarts: `start_production_final.sh --no-ingest` (90 seconds)
3. After code updates: `start_production_final.sh --force-recreate`
4. Monitor logs: `tail -f /opt/obsai/chatbot/logs/ingest_background.log`

### Verification
```bash
# Check all containers running
docker ps | grep chat

# Check volumes
docker volume ls | grep -E "postgres|chroma|chainlit|ollama"

# Check logs
docker logs chat_ui_app
docker logs llm_api_service

# Test health
curl http://localhost:8000
curl http://localhost:8001/api/v1/heartbeat
curl http://localhost:11430/api/tags
```

---

## Summary

**Use `start_all_optimized.sh` for:**
- Development and testing
- Quick iterations
- Flexible directory structures

**Use `start_production_final.sh` for:**
- Production deployments
- SELinux environments
- Maximum security (read-only mounts, volumes for writable data)
- Strict directory structure enforcement
