"""Adaptive RAG Router -- Auto-selects optimal retrieval pipeline mode."""
import re
from typing import Dict, Tuple

class RAGMode:
    SIMPLE = "simple"
    WITH_MEMORY = "with_memory"
    HYDE = "hyde"
    CORRECTIVE = "corrective"
    GRAPH = "graph"
    ALL = [SIMPLE, WITH_MEMORY, HYDE, CORRECTIVE, GRAPH]

_ENTITY_RE = [re.compile(p) for p in [
    r'\brelat(?:ed|ionship|es)\b', r'\bdepend(?:s|ency|encies)\b', r'\bconnect(?:ed|ion|s)\b',
    r'\bpipes?\s+to\b', r'\buses?\s+function', r'\bwhat\s+(?:commands?|functions?)\s+(?:use|work with)']]

_CONCEPT_RE = [re.compile(p) for p in [
    r'^what (?:is|are)\b', r'^explain\b', r'^describe\b', r'^how does\b.*\bwork\b', r'\boverview\b', r'\bconcept\b']]


def select_rag_mode(query: str, intent="", confidence=0.0, has_history=False, chunks_found=0) -> Tuple[str, str]:
    q = query.lower()
    if any(p.search(q) for p in _ENTITY_RE):
        return RAGMode.GRAPH, "Entity-centric query detected -- using graph traversal"
    if any(p.search(q) for p in _CONCEPT_RE):
        return RAGMode.HYDE, "Conceptual query -- using hypothetical document embedding"
    if 0 < confidence < 0.4:
        return RAGMode.CORRECTIVE, f"Low confidence ({confidence:.0%}) -- using self-correcting retrieval"
    if 0 < chunks_found < 2 and len(q.split()) > 5:
        return RAGMode.CORRECTIVE, f"Sparse results ({chunks_found} chunks) -- using self-correcting retrieval"
    if has_history:
        return RAGMode.WITH_MEMORY, "Conversation context available -- including history in retrieval"
    return RAGMode.SIMPLE, "Standard query -- using simple retrieval"


def apply_rag_mode(mode: str, query: str, search_kwargs: Dict) -> Dict:
    if mode == RAGMode.HYDE:
        search_kwargs["use_hyde"] = True
    elif mode == RAGMode.GRAPH:
        search_kwargs.update(include_graph_context=True, graph_weight=0.4)
    elif mode == RAGMode.CORRECTIVE:
        search_kwargs["k"] = search_kwargs.get("k", 5) * 2
        search_kwargs["min_score_threshold"] = 0.3
    elif mode == RAGMode.WITH_MEMORY:
        search_kwargs["include_history"] = True
    return search_kwargs


def get_rag_mode_stats() -> Dict:
    return {"modes": {
        RAGMode.SIMPLE: "Default -- direct retrieval + generation",
        RAGMode.WITH_MEMORY: "Includes conversation history in retrieval context",
        RAGMode.HYDE: "Generates hypothetical document for conceptual queries",
        RAGMode.CORRECTIVE: "Self-corrects by fetching more and re-ranking",
        RAGMode.GRAPH: "Uses knowledge graph traversal for entity queries",
    }, "total_modes": len(RAGMode.ALL)}
