"""Pipeline Data Models — structured types for message handler results.

Replaces raw tuple returns with named, documented dataclasses:
- RetrievalResult: Output of the retrieval phase (was 7-tuple)
- LLMContextResult: Output of build_llm_context (was 8-tuple)
- BuildLLMContextRequest: Input for build_llm_context (was 15 parameters)

These models live in a separate file to avoid import dependencies on
heavy modules like langchain_chroma or chainlit.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalResult:
    """Result of the retrieval phase (replaces 7-tuple return).

    Fields match the previous return: memory_chunks, local_spec_content,
    local_spec_refs, detected_profile, chroma_source, has_conf_context, conf_files.
    """
    memory_chunks: List[Any] = field(default_factory=list)
    local_spec_content: List[str] = field(default_factory=list)
    local_spec_refs: List[str] = field(default_factory=list)
    detected_profile: Optional[str] = None
    chroma_source: str = ""
    has_conf_context: bool = False
    conf_files: Optional[List[str]] = None


@dataclass
class LLMContextResult:
    """Result of build_llm_context (replaces 8-tuple return).

    Fields match the previous return: formatted_context, system_prompt,
    feedback_match, all_refs, opt_result, plan, scored_chunks, doc_snippets.
    """
    formatted_context: str = ""
    system_prompt: str = ""
    feedback_match: Any = None
    all_refs: List[str] = field(default_factory=list)
    opt_result: Any = None
    plan: Any = None
    scored_chunks: List[Any] = field(default_factory=list)
    doc_snippets: List[str] = field(default_factory=list)


@dataclass
class BuildLLMContextRequest:
    """Input parameters for build_llm_context (replaces 15-parameter signature).

    Groups all parameters into a single request object for cleaner API.
    """
    user_input: str = ""
    memory_chunks: List[Any] = field(default_factory=list)
    local_spec_content: List[str] = field(default_factory=list)
    local_spec_refs: List[str] = field(default_factory=list)
    user_settings: Dict[str, Any] = field(default_factory=dict)
    engine: Any = None
    username: str = ""
    system_prompt: str = ""
    profiles_available: bool = False
    detected_profile: Optional[str] = None
    feedback_guardrails_available: bool = False
    map_source_to_url: Any = None
    load_static_context: Any = None
    plan: Any = None
    conf_files: Optional[List[str]] = None
