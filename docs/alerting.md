# Alerting Rules & Escalation

## Alert Thresholds

| Metric | Warning | Critical | Source |
|--------|---------|----------|--------|
| LLM response time | > 15s | > 30s | Prometheus `llm_latency_seconds` |
| Vector search time | > 3s | > 10s | Prometheus `vector_search_seconds` |
| Error rate (5min) | > 5% | > 15% | Prometheus `http_errors_total / http_requests_total` |
| Memory usage | > 80% | > 95% | Prometheus `container_memory_usage_bytes` |
| CPU usage | > 80% | > 95% | Prometheus `container_cpu_usage_seconds` |
| Disk usage | > 80% | > 95% | Prometheus `node_filesystem_avail_bytes` |
| ChromaDB latency | > 2s | > 8s | Health check `/ready` |
| Ollama availability | 1 failure | 3 consecutive | Health check `/ready` |
| PostgreSQL connections | > 80% pool | > 95% pool | Prometheus `pg_stat_activity` |
| Redis memory | > 80% maxmemory | > 95% | Redis INFO memory |
| Pipeline quality score | < 0.5 avg | < 0.3 avg | Execution journal |
| Rate limit hits | > 50/min | > 200/min | Prometheus `rate_limit_429_total` |

## Escalation Path

1. **Auto-heal** (0-5 min): Circuit breakers activate, fallback responses serve
2. **Log alert** (5 min): Structured log entry with `level=ERROR` and alert tag
3. **Dashboard alert** (real-time): Grafana panel turns red, admin UI health badge
4. **Manual investigation**: Check admin UI Observability page, container logs

## Response Procedures

### LLM Unresponsive
1. Check Ollama container: `podman logs llm_api_service --tail 50`
2. Check GPU/CPU usage: Admin UI > Containers
3. Restart Ollama: Admin UI > Containers > Restart `llm_api_service`
4. If persists: check model size vs available memory

### ChromaDB Slow/Down
1. Check container: `podman logs chat_chroma_db --tail 50`
2. Check disk space: `podman exec chat_chroma_db df -h /chroma`
3. Restart: Admin UI > Containers > Restart `chat_chroma_db`
4. If persists: check collection sizes, consider reindexing

### High Error Rate
1. Check admin UI > Observability > Pipeline Traces
2. Identify failing stage (intent, retrieval, LLM, orchestration)
3. Check specific service health
4. Review recent config changes in Admin UI > Config Versions
