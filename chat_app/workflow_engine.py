"""Workflow Engine — every command, agent, and skill runs as an observable workflow.

This is the central nervous system of ObsAI's execution pipeline. Every action
in the system — from a simple /help command to a complex multi-agent orchestration —
is modeled as a Workflow with observable Steps.

## Core Concepts

- **Workflow**: A named sequence of steps triggered by a command, agent, or skill
- **Step**: A single unit of work within a workflow (classify, retrieve, execute, respond)
- **StepResult**: The outcome of a step (success/fail, output, latency, tokens)
- **WorkflowDefinition**: A template that describes what steps a workflow will execute
- **WorkflowRun**: A live execution of a workflow definition with real data

## How It Works

```
User: "search for errors in index=main"
  │
  └─ Workflow: "splunk_search" (triggered by intent classification)
       ├─ Step 1: CLASSIFY (intent=splunk_search, confidence=0.95) [12ms]
       ├─ Step 2: POLICY_CHECK (safety=read_only, allowed=true) [1ms]
       ├─ Step 3: RETRIEVE (collections=3, chunks=15) [120ms]
       ├─ Step 4: AGENT_SELECT (agent=spl_expert, department=engineering) [3ms]
       ├─ Step 5: SKILL_EXECUTE (skill=splunk_search, handler=run_splunk_search) [2400ms]
       ├─ Step 6: EVALUATE (confidence=0.87, grounding=high) [5ms]
       └─ Step 7: RESPOND (tokens=250, latency=180ms) [180ms]
       Total: 2721ms | Success | 7 steps
```

## Simulation Mode

Every workflow definition includes estimated timings so you can simulate
execution without actually running anything:

    sim = engine.simulate("splunk_search", {"query": "index=main errors"})
    # Returns: step-by-step breakdown with estimated latencies

## API Endpoints

- GET  /api/admin/workflows/definitions     — All workflow templates
- GET  /api/admin/workflows/definitions/{n} — Single definition with steps
- GET  /api/admin/workflows/runs            — Recent workflow executions
- GET  /api/admin/workflows/runs/{id}       — Single run with step details
- POST /api/admin/workflows/simulate        — Simulate a workflow
- GET  /api/admin/workflows/stats           — Execution statistics
"""

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step types — the atomic building blocks
# ---------------------------------------------------------------------------

class StepType(str, Enum):
    CLASSIFY = "classify"          # Intent classification
    POLICY_CHECK = "policy_check"  # Safety + RBAC + circuit breaker
    RETRIEVE = "retrieve"          # Vector search + knowledge graph
    AGENT_SELECT = "agent_select"  # Agent dispatch + persona matching
    SKILL_EXECUTE = "skill_execute"  # Skill/tool execution
    LLM_CALL = "llm_call"         # LLM generation
    EVALUATE = "evaluate"          # Self-evaluation + confidence
    RESPOND = "respond"            # Format and send response
    APPROVE = "approve"            # Human approval gate
    TRANSFORM = "transform"        # Data transformation
    CUSTOM = "custom"              # User-defined step


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Step definition (template)
# ---------------------------------------------------------------------------

@dataclass
class StepDefinition:
    """Template for a workflow step — what WILL happen."""
    name: str
    step_type: StepType
    description: str
    estimated_ms: float = 100.0    # Expected latency
    required: bool = True          # If false, failure doesn't stop workflow
    depends_on: List[str] = field(default_factory=list)  # Step names this depends on
    handler: str = ""              # Which handler/module runs this
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.step_type.value,
            "description": self.description,
            "estimated_ms": self.estimated_ms,
            "required": self.required,
            "depends_on": self.depends_on,
            "handler": self.handler,
        }


# ---------------------------------------------------------------------------
# Step result (runtime)
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Result of executing a single workflow step."""
    name: str
    step_type: str
    status: StepStatus = StepStatus.PENDING
    started_at: str = ""
    finished_at: str = ""
    latency_ms: float = 0.0
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Internal
    _start_mono: float = 0.0

    def start(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._start_mono = time.monotonic()

    def complete(self, output: Any = None, **metadata) -> None:
        self.status = StepStatus.COMPLETED
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.latency_ms = (time.monotonic() - self._start_mono) * 1000 if self._start_mono else 0
        self.output = output
        self.metadata.update(metadata)

    def fail(self, error: str, **metadata) -> None:
        self.status = StepStatus.FAILED
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.latency_ms = (time.monotonic() - self._start_mono) * 1000 if self._start_mono else 0
        self.error = error
        self.metadata.update(metadata)

    def skip(self, reason: str = "") -> None:
        self.status = StepStatus.SKIPPED
        self.error = reason

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "type": self.step_type,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 1),
        }
        if self.output is not None:
            d["output"] = str(self.output)[:500]
        if self.error:
            d["error"] = self.error
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# ---------------------------------------------------------------------------
# Workflow definition (template)
# ---------------------------------------------------------------------------

@dataclass
class WorkflowDefinition:
    """Template for a complete workflow — what steps it contains."""
    name: str
    description: str
    trigger: str  # "command:/search", "intent:splunk_search", "mcp:obsai_search"
    category: str = "general"  # command, search, admin, scripting, utility
    steps: List[StepDefinition] = field(default_factory=list)
    total_estimated_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "category": self.category,
            "steps": [s.to_dict() for s in self.steps],
            "total_estimated_ms": self.total_estimated_ms or sum(s.estimated_ms for s in self.steps),
            "step_count": len(self.steps),
        }


# ---------------------------------------------------------------------------
# Workflow run (live execution)
# ---------------------------------------------------------------------------

@dataclass
class WorkflowRun:
    """A live execution of a workflow with real step results."""
    run_id: str = ""
    workflow_name: str = ""
    trigger: str = ""
    actor: str = ""
    input_preview: str = ""
    started_at: str = ""
    finished_at: str = ""
    total_latency_ms: float = 0.0
    success: bool = False
    steps: List[StepResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Internal
    _start_mono: float = 0.0

    def start(self) -> None:
        self.run_id = self.run_id or uuid.uuid4().hex[:12]
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._start_mono = time.monotonic()

    def finish(self, success: bool = True) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.total_latency_ms = (time.monotonic() - self._start_mono) * 1000 if self._start_mono else 0
        self.success = success

    def add_step(self, name: str, step_type: str) -> StepResult:
        step = StepResult(name=name, step_type=step_type)
        self.steps.append(step)
        return step

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow_name,
            "trigger": self.trigger,
            "actor": self.actor,
            "input": self.input_preview,
            "success": self.success,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "started_at": self.started_at,
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Built-in workflow definitions
# ---------------------------------------------------------------------------

def _build_definitions() -> Dict[str, WorkflowDefinition]:
    """Build all workflow definitions for the system."""
    defs: Dict[str, WorkflowDefinition] = {}

    # --- Search workflows ---
    defs["splunk_search"] = WorkflowDefinition(
        name="splunk_search", description="Execute a Splunk search query",
        trigger="intent:splunk_search", category="search",
        steps=[
            StepDefinition("classify", StepType.CLASSIFY, "Classify query intent and extract SPL", 15, handler="intent_classifier"),
            StepDefinition("policy_check", StepType.POLICY_CHECK, "Check safety policy (read_only) and circuit breaker", 2, handler="safety_policies"),
            StepDefinition("retrieve", StepType.RETRIEVE, "Search vector store for relevant SPL docs and examples", 150, handler="vectorstore_search"),
            StepDefinition("kg_enrich", StepType.RETRIEVE, "Enrich with knowledge graph entity context", 20, required=False, handler="knowledge_graph"),
            StepDefinition("agent_select", StepType.AGENT_SELECT, "Select best agent (spl_expert) with persona matching", 5, handler="agent_dispatcher"),
            StepDefinition("execute_search", StepType.SKILL_EXECUTE, "Execute Splunk search via REST API", 3000, handler="run_splunk_search"),
            StepDefinition("evaluate", StepType.EVALUATE, "Score confidence and grounding of results", 5, required=False, handler="self_evaluation"),
            StepDefinition("respond", StepType.RESPOND, "Format results and stream response", 200, handler="response_generator"),
        ],
    )

    defs["spl_explain"] = WorkflowDefinition(
        name="spl_explain", description="Explain an SPL query step by step",
        trigger="intent:spl_explain", category="search",
        steps=[
            StepDefinition("classify", StepType.CLASSIFY, "Classify as SPL explanation request", 15, handler="intent_classifier"),
            StepDefinition("retrieve", StepType.RETRIEVE, "Fetch SPL command documentation", 120, handler="vectorstore_search"),
            StepDefinition("agent_select", StepType.AGENT_SELECT, "Select spl_expert agent", 5, handler="agent_dispatcher"),
            StepDefinition("explain", StepType.SKILL_EXECUTE, "Parse and annotate each SPL command", 50, handler="explain_spl"),
            StepDefinition("respond", StepType.LLM_CALL, "Generate explanation with LLM", 2000, handler="response_generator"),
        ],
    )

    defs["general_qa"] = WorkflowDefinition(
        name="general_qa", description="Answer a general knowledge question",
        trigger="intent:general_qa", category="search",
        steps=[
            StepDefinition("classify", StepType.CLASSIFY, "Classify intent", 15, handler="intent_classifier"),
            StepDefinition("tool_decision", StepType.POLICY_CHECK, "Decide: use tools or answer from knowledge", 3, handler="toolformer"),
            StepDefinition("retrieve", StepType.RETRIEVE, "Multi-collection vector search", 150, handler="vectorstore_search"),
            StepDefinition("respond", StepType.LLM_CALL, "Generate response with LLM", 2500, handler="response_generator"),
            StepDefinition("evaluate", StepType.EVALUATE, "Score confidence", 5, required=False, handler="self_evaluation"),
        ],
    )

    # --- Command workflows ---
    defs["cmd_doc"] = WorkflowDefinition(
        name="cmd_doc", description="/doc command — generate documentation",
        trigger="command:/doc", category="command",
        steps=[
            StepDefinition("parse_args", StepType.CLASSIFY, "Parse command arguments (text/path/format)", 2, handler="slash_commands"),
            StepDefinition("detect_mode", StepType.CLASSIFY, "Auto-detect mode: snippet, directory, or zip", 5, handler="doc_generator"),
            StepDefinition("scan_files", StepType.SKILL_EXECUTE, "Scan and analyze files (if directory/zip)", 500, required=False, handler="doc_generator"),
            StepDefinition("generate", StepType.SKILL_EXECUTE, "Generate structured documentation", 100, handler="doc_generator"),
            StepDefinition("format", StepType.TRANSFORM, "Render as Markdown or SharePoint HTML", 10, handler="doc_generator"),
            StepDefinition("respond", StepType.RESPOND, "Send documentation to user", 5, handler="chainlit"),
        ],
    )

    defs["cmd_search"] = WorkflowDefinition(
        name="cmd_search", description="/search command — search knowledge base",
        trigger="command:/search", category="command",
        steps=[
            StepDefinition("parse_args", StepType.CLASSIFY, "Parse search query from command", 2, handler="slash_commands"),
            StepDefinition("retrieve", StepType.RETRIEVE, "Multi-collection parallel vector search", 200, handler="vectorstore_search"),
            StepDefinition("rank", StepType.TRANSFORM, "Score and rank results by relevance", 10, handler="context_builder"),
            StepDefinition("respond", StepType.RESPOND, "Format results as markdown table", 5, handler="slash_commands"),
        ],
    )

    defs["cmd_health"] = WorkflowDefinition(
        name="cmd_health", description="/health command — check system health",
        trigger="command:/health", category="admin",
        steps=[
            StepDefinition("check_postgres", StepType.SKILL_EXECUTE, "Check PostgreSQL connectivity", 200, handler="health_monitor"),
            StepDefinition("check_ollama", StepType.SKILL_EXECUTE, "Check Ollama LLM service", 200, handler="health_monitor"),
            StepDefinition("check_chromadb", StepType.SKILL_EXECUTE, "Check ChromaDB vector store", 200, handler="health_monitor"),
            StepDefinition("check_redis", StepType.SKILL_EXECUTE, "Check Redis cache", 100, required=False, handler="health_monitor"),
            StepDefinition("check_slo", StepType.EVALUATE, "Evaluate SLO compliance", 5, required=False, handler="slo_tracker"),
            StepDefinition("respond", StepType.RESPOND, "Format health report", 5, handler="slash_commands"),
        ],
    )

    defs["cmd_explain"] = WorkflowDefinition(
        name="cmd_explain", description="/explain command — explain SPL query",
        trigger="command:/explain", category="command",
        steps=[
            StepDefinition("parse_spl", StepType.CLASSIFY, "Extract SPL from command arguments", 2, handler="slash_commands"),
            StepDefinition("retrieve_docs", StepType.RETRIEVE, "Fetch command documentation for each SPL command", 120, handler="vectorstore_search"),
            StepDefinition("explain", StepType.SKILL_EXECUTE, "Annotate each command with explanation", 50, handler="explain_spl"),
            StepDefinition("respond", StepType.RESPOND, "Format step-by-step explanation", 5, handler="slash_commands"),
        ],
    )

    # --- Agent workflows ---
    defs["agent_dispatch"] = WorkflowDefinition(
        name="agent_dispatch", description="Multi-agent dispatch with skill chain",
        trigger="orchestration:adaptive", category="agent",
        steps=[
            StepDefinition("select_strategy", StepType.CLASSIFY, "Select orchestration strategy based on intent + resources", 5, handler="orchestration_strategies"),
            StepDefinition("persona_match", StepType.AGENT_SELECT, "Score agents against user persona", 3, handler="persona_orchestration"),
            StepDefinition("select_agent", StepType.AGENT_SELECT, "Select best-fit agent by expertise + intent", 5, handler="agent_dispatcher"),
            StepDefinition("plan_skills", StepType.CLASSIFY, "Plan skill execution chain for selected agent", 3, handler="agent_dispatcher"),
            StepDefinition("execute_skills", StepType.SKILL_EXECUTE, "Execute skill chain (1-5 skills)", 2000, handler="skill_executor"),
            StepDefinition("reflect", StepType.EVALUATE, "Agent self-reflection on quality", 10, required=False, handler="agent_dispatcher"),
        ],
    )

    # --- MCP tool workflows ---
    defs["mcp_tool_call"] = WorkflowDefinition(
        name="mcp_tool_call", description="MCP tool invocation via external client",
        trigger="mcp:*", category="mcp",
        steps=[
            StepDefinition("auth_check", StepType.POLICY_CHECK, "Verify caller role against tool min_role", 1, handler="mcp_server_mode"),
            StepDefinition("circuit_check", StepType.POLICY_CHECK, "Check circuit breaker status", 1, handler="circuit_breaker"),
            StepDefinition("execute", StepType.SKILL_EXECUTE, "Execute tool handler", 1000, handler="mcp_server_mode"),
            StepDefinition("track", StepType.EVALUATE, "Record to execution tracker", 1, required=False, handler="execution_tracker"),
        ],
    )

    # --- Utility workflows ---
    defs["utility_operation"] = WorkflowDefinition(
        name="utility_operation", description="Encoding, hashing, text transform",
        trigger="skill:utility", category="utility",
        steps=[
            StepDefinition("validate_input", StepType.CLASSIFY, "Validate operation and input data", 1, handler="skill_executor"),
            StepDefinition("execute", StepType.SKILL_EXECUTE, "Run utility handler", 5, handler="handlers/utility_handlers"),
            StepDefinition("respond", StepType.RESPOND, "Return result", 1, handler="skill_executor"),
        ],
    )

    # --- Scripting workflows ---
    defs["scripting"] = WorkflowDefinition(
        name="scripting", description="Ansible/Shell/Python script generation or analysis",
        trigger="skill:scripting", category="scripting",
        steps=[
            StepDefinition("classify_action", StepType.CLASSIFY, "Detect: generate, analyze, explain, or improve", 5, handler="intent_classifier"),
            StepDefinition("retrieve_patterns", StepType.RETRIEVE, "Fetch relevant script patterns and examples", 100, handler="vectorstore_search"),
            StepDefinition("generate", StepType.LLM_CALL, "LLM generates/analyzes script", 3000, handler="response_generator"),
            StepDefinition("validate", StepType.EVALUATE, "Validate syntax and best practices", 50, required=False, handler="skill_executor"),
            StepDefinition("respond", StepType.RESPOND, "Format with syntax highlighting", 5, handler="slash_commands"),
        ],
    )

    # --- Admin workflows ---
    defs["config_change"] = WorkflowDefinition(
        name="config_change", description="Configuration update with safety checks",
        trigger="admin:config_update", category="admin",
        steps=[
            StepDefinition("validate", StepType.CLASSIFY, "Validate new config against Pydantic schema", 5, handler="settings"),
            StepDefinition("policy_check", StepType.POLICY_CHECK, "Check safety policy (write level)", 2, handler="safety_policies"),
            StepDefinition("approval_check", StepType.APPROVE, "Check if approval workflow required", 2, handler="approval_workflows"),
            StepDefinition("backup", StepType.SKILL_EXECUTE, "Backup current config before change", 50, handler="config_manager"),
            StepDefinition("apply", StepType.SKILL_EXECUTE, "Apply config change", 10, handler="config_manager"),
            StepDefinition("audit", StepType.EVALUATE, "Record change to immutable audit log", 2, handler="audit_log"),
            StepDefinition("reload", StepType.SKILL_EXECUTE, "Hot-reload or schedule restart", 100, handler="config_manager"),
        ],
    )

    return defs


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

@dataclass
class SimulationResult:
    """Result of simulating a workflow — predicted execution breakdown."""
    workflow_name: str
    total_estimated_ms: float
    steps: List[Dict[str, Any]] = field(default_factory=list)
    critical_path_ms: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow": self.workflow_name,
            "total_estimated_ms": round(self.total_estimated_ms, 1),
            "critical_path_ms": round(self.critical_path_ms, 1),
            "steps": self.steps,
            "step_count": len(self.steps),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Workflow Engine
# ---------------------------------------------------------------------------

_MAX_RUNS = 1000


class WorkflowEngine:
    """Central engine for workflow definitions, execution tracking, and simulation."""

    def __init__(self):
        self._definitions: Dict[str, WorkflowDefinition] = _build_definitions()
        self._runs: Deque[WorkflowRun] = deque(maxlen=_MAX_RUNS)
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._error_counters: Dict[str, int] = defaultdict(int)

    # ----- Definitions -----

    def get_definition(self, name: str) -> Optional[WorkflowDefinition]:
        return self._definitions.get(name)

    def get_all_definitions(self) -> List[WorkflowDefinition]:
        return list(self._definitions.values())

    def register_definition(self, definition: WorkflowDefinition) -> None:
        self._definitions[definition.name] = definition

    # ----- Runs -----

    def start_run(self, workflow_name: str, actor: str = "", input_preview: str = "",
                  trigger: str = "") -> WorkflowRun:
        """Start a new workflow run. Returns the run for step-by-step population."""
        defn = self._definitions.get(workflow_name)
        run = WorkflowRun(
            workflow_name=workflow_name,
            trigger=trigger or (defn.trigger if defn else ""),
            actor=actor,
            input_preview=input_preview[:200],
        )
        run.start()
        return run

    def finish_run(self, run: WorkflowRun, success: bool = True) -> None:
        """Finalize and store a completed run (in-memory + file persistence)."""
        run.finish(success)
        with self._lock:
            self._runs.append(run)
            self._counters[run.workflow_name] += 1
            if not success:
                self._error_counters[run.workflow_name] += 1
        # Persist to JSONL file
        try:
            import json
            import os
            from pathlib import Path
            persist_path = Path(os.getenv("WORKFLOW_RUNS_PATH", "/app/data/workflow_runs.jsonl"))
            persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(persist_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(run.to_dict(), default=str) + "\n")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("Failed to persist workflow run: %s", _exc)

    def get_recent_runs(self, workflow_name: Optional[str] = None,
                        limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            runs = list(self._runs)
        if workflow_name:
            runs = [r for r in runs if r.workflow_name == workflow_name]
        runs.reverse()
        return [r.to_dict() for r in runs[:limit]]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for r in self._runs:
                if r.run_id == run_id:
                    return r.to_dict()
        return None

    # ----- Simulation -----

    def simulate(self, workflow_name: str, params: Optional[Dict[str, Any]] = None) -> SimulationResult:
        """Simulate a workflow execution — predict steps, latencies, and outcomes."""
        defn = self._definitions.get(workflow_name)
        if not defn:
            return SimulationResult(workflow_name=workflow_name, total_estimated_ms=0,
                                    notes=[f"Unknown workflow: {workflow_name}"])

        steps = []
        cumulative_ms = 0
        notes = []

        for step_def in defn.steps:
            est = step_def.estimated_ms
            cumulative_ms += est
            steps.append({
                "name": step_def.name,
                "type": step_def.step_type.value,
                "description": step_def.description,
                "handler": step_def.handler,
                "estimated_ms": est,
                "cumulative_ms": round(cumulative_ms, 1),
                "required": step_def.required,
                "depends_on": step_def.depends_on,
            })

            if est > 1000:
                notes.append(f"Step '{step_def.name}' is the bottleneck ({est}ms) — consider caching or timeout")
            if not step_def.required:
                notes.append(f"Step '{step_def.name}' is optional — workflow continues on failure")

        return SimulationResult(
            workflow_name=workflow_name,
            total_estimated_ms=cumulative_ms,
            steps=steps,
            critical_path_ms=cumulative_ms,
            notes=notes,
        )

    # ----- Stats -----

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._runs)
        return {
            "definitions": len(self._definitions),
            "total_runs": total,
            "by_workflow": dict(self._counters),
            "errors_by_workflow": dict(self._error_counters),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[WorkflowEngine] = None
_instance_lock = threading.Lock()


def get_workflow_engine() -> WorkflowEngine:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WorkflowEngine()
    return _instance
