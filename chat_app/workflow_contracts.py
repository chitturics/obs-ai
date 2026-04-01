"""Workflow Step Contracts — formal input/output specifications for workflow steps.

Inspired by AutoResearchClaw's StageContract pattern, this module defines
frozen dataclass contracts that specify exactly what each workflow step
requires as input and what it must produce as output.

Benefits:
- Self-documenting pipeline: each step declares its contract
- Runtime validation: missing inputs caught before execution, not mid-way
- Testability: contracts can be unit-tested without running the step
- Decision support: PROCEED/REFINE/PIVOT based on contract satisfaction

Usage:
    from chat_app.workflow_contracts import (
        WorkflowStepContract, validate_step_inputs, validate_step_outputs,
        StepDecision, decide_step_outcome,
    )

    contract = get_contract("retrieval")
    errors = validate_step_inputs(contract, context)
    if errors:
        raise ContractViolation(errors)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step decision enum (PROCEED / REFINE / PIVOT)
# ---------------------------------------------------------------------------

class StepDecision(str, Enum):
    """Decision after evaluating a workflow step's output."""
    PROCEED = "proceed"    # Output meets contract — continue to next step
    REFINE = "refine"      # Output below threshold — retry with adjusted params
    PIVOT = "pivot"        # Step failed repeatedly — try alternative strategy
    ABORT = "abort"        # Unrecoverable failure — stop workflow


# ---------------------------------------------------------------------------
# Contract dataclass (frozen for immutability)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowStepContract:
    """Formal specification for a workflow step.

    Frozen to prevent runtime mutation of expectations.
    """
    step_name: str
    description: str
    required_inputs: FrozenSet[str]     # Context keys that must exist before step runs
    expected_outputs: FrozenSet[str]    # Context keys the step must produce
    definition_of_done: str            # Human-readable success criteria
    error_code: str                    # Machine-readable error identifier
    max_retries: int = 2               # Max REFINE attempts before PIVOT
    timeout_seconds: float = 30.0      # Step execution timeout
    quality_threshold: float = 0.5     # Minimum quality score to PROCEED
    optional_inputs: FrozenSet[str] = frozenset()  # Nice-to-have context keys


# ---------------------------------------------------------------------------
# Contract violation
# ---------------------------------------------------------------------------

@dataclass
class ContractViolation:
    """A specific contract violation with details."""
    contract_name: str
    violation_type: str   # "missing_input", "missing_output", "quality_below_threshold"
    details: str
    missing_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract": self.contract_name,
            "type": self.violation_type,
            "details": self.details,
            "missing_keys": self.missing_keys,
        }


# ---------------------------------------------------------------------------
# Built-in contracts for the standard pipeline steps
# ---------------------------------------------------------------------------

PIPELINE_CONTRACTS: Dict[str, WorkflowStepContract] = {
    "intent_classification": WorkflowStepContract(
        step_name="intent_classification",
        description="Classify user query into an intent category",
        required_inputs=frozenset({"user_input"}),
        expected_outputs=frozenset({"intent", "confidence"}),
        definition_of_done="Intent classified with confidence > 0.3",
        error_code="E_INTENT_CLASSIFICATION",
        max_retries=1,
        timeout_seconds=5.0,
        quality_threshold=0.3,
    ),
    "retrieval": WorkflowStepContract(
        step_name="retrieval",
        description="Retrieve relevant documents from vector store",
        required_inputs=frozenset({"user_input", "intent"}),
        expected_outputs=frozenset({"chunks", "chunk_count"}),
        definition_of_done="At least 1 relevant chunk retrieved OR conceptual intent",
        error_code="E_RETRIEVAL",
        max_retries=2,
        timeout_seconds=15.0,
        quality_threshold=0.0,  # 0 chunks OK for conceptual intents
        optional_inputs=frozenset({"search_depth", "collection_filter"}),
    ),
    "orchestration": WorkflowStepContract(
        step_name="orchestration",
        description="Route to agent and execute skills",
        required_inputs=frozenset({"user_input", "intent"}),
        expected_outputs=frozenset({"agent_context", "strategy_used"}),
        definition_of_done="Agent selected and skills executed without error",
        error_code="E_ORCHESTRATION",
        max_retries=2,
        timeout_seconds=30.0,
        quality_threshold=0.4,
        optional_inputs=frozenset({"chunks", "user_approved"}),
    ),
    "context_build": WorkflowStepContract(
        step_name="context_build",
        description="Assemble LLM context from chunks, agent output, and metadata",
        required_inputs=frozenset({"user_input", "intent", "chunks"}),
        expected_outputs=frozenset({"formatted_context", "system_prompt"}),
        definition_of_done="Context assembled with non-empty formatted content",
        error_code="E_CONTEXT_BUILD",
        max_retries=1,
        timeout_seconds=5.0,
        quality_threshold=0.0,
    ),
    "llm_generation": WorkflowStepContract(
        step_name="llm_generation",
        description="Generate response using LLM with assembled context",
        required_inputs=frozenset({"formatted_context", "system_prompt", "user_input"}),
        expected_outputs=frozenset({"result_text"}),
        definition_of_done="Non-empty response generated without error markers",
        error_code="E_LLM_GENERATION",
        max_retries=2,
        timeout_seconds=120.0,
        quality_threshold=0.3,
        optional_inputs=frozenset({"agent_context", "workflow_context"}),
    ),
    "post_processing": WorkflowStepContract(
        step_name="post_processing",
        description="Apply anti-hallucination guard, formatting, and enrichment",
        required_inputs=frozenset({"result_text", "user_input"}),
        expected_outputs=frozenset({"final_response"}),
        definition_of_done="Response passes anti-hallucination check and formatting",
        error_code="E_POST_PROCESSING",
        max_retries=1,
        timeout_seconds=10.0,
        quality_threshold=0.0,
    ),
}

# Workflow-specific contracts (multi-agent coordination)
WORKFLOW_CONTRACTS: Dict[str, WorkflowStepContract] = {
    "task_decomposition": WorkflowStepContract(
        step_name="task_decomposition",
        description="Break complex query into sub-tasks with dependencies",
        required_inputs=frozenset({"user_input", "intent"}),
        expected_outputs=frozenset({"sub_tasks", "dependency_graph"}),
        definition_of_done="At least 1 sub-task generated with clear description",
        error_code="E_TASK_DECOMPOSITION",
        max_retries=2,
        timeout_seconds=15.0,
    ),
    "agent_assignment": WorkflowStepContract(
        step_name="agent_assignment",
        description="Assign each sub-task to the best-fit agent",
        required_inputs=frozenset({"sub_tasks"}),
        expected_outputs=frozenset({"agent_assignments"}),
        definition_of_done="Every sub-task has an assigned agent",
        error_code="E_AGENT_ASSIGNMENT",
        max_retries=1,
        timeout_seconds=5.0,
    ),
    "result_aggregation": WorkflowStepContract(
        step_name="result_aggregation",
        description="Combine sub-task results into coherent final output",
        required_inputs=frozenset({"sub_task_results"}),
        expected_outputs=frozenset({"aggregated_result", "quality_score"}),
        definition_of_done="All sub-task results merged without conflicts",
        error_code="E_RESULT_AGGREGATION",
        max_retries=1,
        timeout_seconds=10.0,
        quality_threshold=0.5,
    ),
}


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

def validate_step_inputs(
    contract: WorkflowStepContract,
    context: Dict[str, Any],
) -> List[ContractViolation]:
    """Validate that all required inputs for a step exist in the context.

    Returns a list of ContractViolation objects (empty list if all inputs are present).
    """
    violations: List[ContractViolation] = []
    missing = [key for key in contract.required_inputs if key not in context or context[key] is None]
    if missing:
        violations.append(ContractViolation(
            contract_name=contract.step_name,
            violation_type="missing_input",
            details=f"Missing required inputs: {', '.join(missing)}",
            missing_keys=missing,
        ))
    return violations


def validate_step_outputs(
    contract: WorkflowStepContract,
    context: Dict[str, Any],
) -> List[ContractViolation]:
    """Validate that all expected outputs from a step are present in the context.

    Returns a list of ContractViolation objects (empty list if all outputs are present).
    """
    violations: List[ContractViolation] = []
    missing = [key for key in contract.expected_outputs if key not in context or context[key] is None]
    if missing:
        violations.append(ContractViolation(
            contract_name=contract.step_name,
            violation_type="missing_output",
            details=f"Missing expected outputs: {', '.join(missing)}",
            missing_keys=missing,
        ))
    return violations


# ---------------------------------------------------------------------------
# Decision logic (PROCEED / REFINE / PIVOT)
# ---------------------------------------------------------------------------

@dataclass
class StepOutcome:
    """Result of evaluating a step's execution against its contract."""
    decision: StepDecision
    quality_score: float = 0.0
    violations: List[ContractViolation] = field(default_factory=list)
    retry_count: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "quality_score": round(self.quality_score, 4),
            "violations": [v.to_dict() for v in self.violations],
            "retry_count": self.retry_count,
            "reason": self.reason,
        }


def decide_step_outcome(
    contract: WorkflowStepContract,
    context: Dict[str, Any],
    quality_score: float = 1.0,
    retry_count: int = 0,
) -> StepOutcome:
    """Evaluate step output and decide PROCEED/REFINE/PIVOT/ABORT.

    Decision logic:
    1. If outputs missing and retries exhausted → PIVOT
    2. If outputs missing and retries available → REFINE
    3. If quality below threshold and retries available → REFINE
    4. If quality below threshold and retries exhausted → PIVOT
    5. If all outputs present and quality above threshold → PROCEED
    """
    violations = validate_step_outputs(contract, context)

    # Missing outputs
    if violations:
        if retry_count >= contract.max_retries:
            return StepOutcome(
                decision=StepDecision.PIVOT,
                quality_score=quality_score,
                violations=violations,
                retry_count=retry_count,
                reason=f"Missing outputs after {retry_count} retries: {violations[0].details}",
            )
        return StepOutcome(
            decision=StepDecision.REFINE,
            quality_score=quality_score,
            violations=violations,
            retry_count=retry_count,
            reason=f"Missing outputs, retry {retry_count + 1}/{contract.max_retries}",
        )

    # Quality check
    if quality_score < contract.quality_threshold:
        if retry_count >= contract.max_retries:
            return StepOutcome(
                decision=StepDecision.PIVOT,
                quality_score=quality_score,
                retry_count=retry_count,
                reason=f"Quality {quality_score:.2f} below threshold {contract.quality_threshold:.2f} after {retry_count} retries",
            )
        return StepOutcome(
            decision=StepDecision.REFINE,
            quality_score=quality_score,
            retry_count=retry_count,
            reason=f"Quality {quality_score:.2f} below threshold {contract.quality_threshold:.2f}",
        )

    # All good
    return StepOutcome(
        decision=StepDecision.PROCEED,
        quality_score=quality_score,
        retry_count=retry_count,
        reason="Contract satisfied",
    )


# ---------------------------------------------------------------------------
# Contract registry
# ---------------------------------------------------------------------------

def get_contract(step_name: str) -> Optional[WorkflowStepContract]:
    """Look up a contract by step name, checking pipeline contracts then workflow contracts.

    Returns the WorkflowStepContract if found, or None if the step name is unknown.
    """
    return PIPELINE_CONTRACTS.get(step_name) or WORKFLOW_CONTRACTS.get(step_name)


def get_all_contracts() -> Dict[str, WorkflowStepContract]:
    """Return all registered contracts from both PIPELINE_CONTRACTS and WORKFLOW_CONTRACTS."""
    all_contracts = {}
    all_contracts.update(PIPELINE_CONTRACTS)
    all_contracts.update(WORKFLOW_CONTRACTS)
    return all_contracts


def get_contract_summary() -> Dict[str, Any]:
    """Return a JSON-serialisable summary of all registered contracts for admin API or dashboard display."""
    all_c = get_all_contracts()
    return {
        "total": len(all_c),
        "pipeline_steps": len(PIPELINE_CONTRACTS),
        "workflow_steps": len(WORKFLOW_CONTRACTS),
        "contracts": {
            name: {
                "description": c.description,
                "required_inputs": sorted(c.required_inputs),
                "expected_outputs": sorted(c.expected_outputs),
                "definition_of_done": c.definition_of_done,
                "max_retries": c.max_retries,
                "timeout_seconds": c.timeout_seconds,
                "quality_threshold": c.quality_threshold,
            }
            for name, c in all_c.items()
        },
    }
