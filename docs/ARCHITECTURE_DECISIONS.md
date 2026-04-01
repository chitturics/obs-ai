# Architecture Decision Records (ADRs)

## ADR-001: Exception Handling Strategy

**Status**: Approved
**Date**: 2026-03-26

### Context
The codebase has 1193 `except Exception` catches. Most are catch-all patterns that mask real errors and make debugging impossible. The auditor flagged this as the #1 code quality issue.

### Decision
1. **Each exception handler must catch the NARROWEST possible type**
2. **Every caught exception must be logged** (at minimum DEBUG level)
3. **CI enforces BLE001 (blind exception)** — new broad catches require explicit `# noqa: BLE001` with justification
4. **Three approved catch-all patterns** (the ONLY cases where `except Exception` is acceptable):
   - Top-level pipeline entry point (message_handler `on_message`)
   - Module initialization guards (optional dependency imports)
   - Background task runners (idle_worker, scheduler)

### Consequences
- Debugging in production becomes possible
- Error rates become measurable per exception type
- CI prevents regression

---

## ADR-002: Pipeline Architecture

**Status**: Approved
**Date**: 2026-03-26

### Context
`message_handler.py` is 1976 lines with a single `on_message()` function spanning ~1200 lines. This makes it impossible to test individual pipeline stages, understand the flow, or modify one stage without risking regression in another.

### Decision
Split the pipeline into discrete, independently testable stages:

```
message_handler.py (orchestrator, ~500 lines)
  ├── pipeline_retrieval.py (vector search + KG, ~300 lines)
  ├── pipeline_response.py (LLM generation + formatting, ~400 lines)
  └── pipeline_telemetry.py (post-response metrics, ~300 lines)
```

Each stage:
- Has a clear input/output contract (dataclass)
- Is independently unit-testable
- Records to the workflow engine with step-level tracing
- Has its own latency budget enforced

### Consequences
- Each pipeline stage is testable in isolation
- Latency can be attributed to specific stages
- New stages can be added without modifying the monolith

---

## ADR-003: Agent Clarification Protocol

**Status**: Approved
**Date**: 2026-03-26

### Context
When an agent is uncertain, it sets `clarification_needed=True` with questions, but the pipeline ignores this and passes it through to the LLM context where the questions get lost.

### Decision
The clarification protocol is:
1. Agent self-assessment detects low confidence → sets `clarification_needed`
2. Orchestration strategy checks the flag BEFORE formatting context
3. If clarification needed: pipeline PAUSES, surfaces questions to user
4. User responds → pipeline RESUMES with enriched context
5. Full flow is audited (who asked, what, when, response)

### Consequences
- Users get better answers (agent asks before guessing)
- Audit trail shows the clarification decision
- Workflow state machine supports WAITING_INPUT state

---

## ADR-004: Config Persistence Model

**Status**: Approved
**Date**: 2026-03-26

### Context
Config writes go to `/app/config.yaml` (baked into container image). When the container is rebuilt, changes are lost. The project source mount is read-only.

### Decision
1. Config writes go to `/app/data/config.yaml` (persistent volume)
2. On startup, if `/app/data/config.yaml` doesn't exist, copy from baked-in default
3. Docker compose maps `app_data` volume to `/app/data`
4. All persistent state (config, audit logs, traces, workflow runs) lives in `/app/data/`
5. Backups include the `/app/data/` volume

### Consequences
- Config survives container rebuilds
- Single backup target for all persistent state
- Clear separation: code in image, state in volume

---

## ADR-005: OIDC Trust Model

**Status**: Approved
**Date**: 2026-03-26

### Context
The auditor flags that `_decode_jwt()` does not verify JWT signatures. Full JWKS-based verification requires PyJWT or jwcrypto (external dependency).

### Decision
The OIDC trust model has three layers:
1. **Transport trust**: Tokens obtained via HTTPS from the provider's token endpoint
2. **Claim verification**: issuer, audience, expiry, nonce, at_hash all validated
3. **Algorithm safety**: `none` and `HS256` algorithms rejected (prevents confusion attacks)

Compensating controls when signature verification is unavailable:
- `validate_token()` uses the userinfo endpoint (server-side verification)
- `authenticate()` gets tokens directly from the provider (transport trust)
- Nonce prevents replay attacks
- at_hash binds id_token to access_token

Full JWKS verification will be added when PyJWT is available in the container.

### Consequences
- Clear documentation of the trust model
- No false sense of security from partial verification
- Upgrade path defined

---

## ADR-006: Learning Governance

**Status**: Approved
**Date**: 2026-03-26

### Context
Self-learning can update retrieval weights, prompt overlays, and even create custom LLM models. Without governance, a bad learning cycle can degrade answer quality system-wide.

### Decision
All learning goes through `LearningGovernor`:
1. **Pre-learning snapshot**: Record baseline quality
2. **Post-learning evaluation**: Compare against baseline
3. **Auto-rollback**: If quality degrades beyond threshold (-5%), revert
4. **Approval gate**: Model customization requires explicit admin approval
5. **Audit trail**: Every learning session recorded with quality delta

### Consequences
- Learning cannot silently degrade quality
- Admin has visibility into what learning changed
- Rollback is automatic and immediate

---

## ADR-007: Workflow State Machine

**Status**: Approved
**Date**: 2026-03-26

### Context
Workflow status is tracked with string values ("running", "completed") with no transition validation. Invalid state transitions (e.g., completed → running) are not caught.

### Decision
Implement a formal state machine with:
- Enum-based states: CREATED, RUNNING, PAUSED, WAITING_INPUT, WAITING_APPROVAL, COMPLETED, FAILED
- Explicit transition map (only allowed transitions succeed)
- Transition history log for debugging
- InvalidTransitionError on illegal moves

### Consequences
- Workflow state is always valid
- Debugging state issues becomes deterministic
- Supports the clarification protocol (RUNNING → WAITING_INPUT → RUNNING)
