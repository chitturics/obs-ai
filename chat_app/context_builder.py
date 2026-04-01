"""
Context builder for the Splunk Assistant.

Handles chunk scoring/filtering, context assembly, and reference management.
Extracted from app.py for modularity.
"""
import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """Result of context building."""
    formatted_context: str = ""
    all_refs: List[str] = field(default_factory=list)
    valid_refs: List[Tuple[str, str, str]] = field(default_factory=list)
    confidence_label: str = "LOW"
    filtered_count: int = 0
    doc_snippets: List[str] = field(default_factory=list)
    top_chunks: List[tuple] = field(default_factory=list)
    context_hash: str = ""
    chroma_source: str = ""
    memory_chunk_count: int = 0
    has_conf_context: bool = False


# ------------------------------------------------------------------
# Config context detection
# ------------------------------------------------------------------

def detect_config_context(user_input: str) -> Tuple[List[str], Optional[str]]:
    """
    Detect configuration files and stanza hints from user input.
    Returns (conf_files, stanza_hint).
    """
    conf_files = re.findall(r'([a-z0-9._-]+\.conf(?:\.spec)?)', user_input.lower())
    conf_files = list(dict.fromkeys(conf_files))

    stanza_hint = None
    bracket_matches = re.findall(r'\[([^\]]+)\]', user_input)
    if bracket_matches:
        stanza_hint = bracket_matches[0]
    else:
        stanza_keywords = ['monitor', 'sourcetype', 'default', 'tcp', 'udp', 'script', 'transform']
        for keyword in stanza_keywords:
            if keyword in user_input.lower():
                stanza_hint = keyword
                break

    return conf_files, stanza_hint


def find_local_spec_file(conf_name: str, search_roots: List[str]) -> Optional[Path]:
    """Find .conf.spec file in local directories."""
    cname = conf_name.lower()
    if not cname.endswith(".spec"):
        if cname.endswith(".conf"):
            cname = f"{cname}.spec"  # inputs.conf -> inputs.conf.spec
        else:
            cname = f"{cname}.conf.spec"  # inputs -> inputs.conf.spec

    for root in search_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for spec_file in root_path.rglob(cname):
            if spec_file.is_file():
                logger.info(f"Found spec file: {spec_file}")
                return spec_file
    return None


def extract_spec_stanzas(
    spec_path: Path,
    stanza_hint: Optional[str] = None,
    limit: int = 3
) -> List[str]:
    """Extract stanza blocks from spec file with optional filtering."""
    blocks = []
    try:
        content = spec_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except (OSError, ValueError) as exc:
        logger.error(f"Failed to read spec file {spec_path}: {exc}")
        return blocks

    current_block = []
    for line in content:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
            if current_block:
                blocks.append("\n".join(current_block).strip())
            current_block = [line]
        elif current_block:
            current_block.append(line)

    if current_block:
        blocks.append("\n".join(current_block).strip())

    if stanza_hint:
        hint_lower = stanza_hint.lower()
        filtered = [b for b in blocks if hint_lower in b.lower()]
        return filtered[:limit] if filtered else blocks[:limit]

    return blocks[:limit]


# ------------------------------------------------------------------
# Compound query detection
# ------------------------------------------------------------------

def detect_compound_query(query: str) -> Tuple[bool, List[str]]:
    """Detect if query has multiple concepts and split into sub-queries."""
    compound_patterns = [r'\b(and|&|\+|with)\b', r'\b(vs|versus|or)\b', r',']
    query_lower = query.lower()
    if not any(re.search(p, query_lower) for p in compound_patterns):
        return False, [query]

    concepts = []
    for part in re.split(r'(?:\s+(?:and|&|\+|with|vs|versus|or)\s+|,\s*)', query, flags=re.IGNORECASE):
        part = part.strip()
        if (part and part.lower() not in ['and', '&', '+', 'with', 'vs', 'versus', 'or']
                and re.search(r'[A-Z]{2,}|[a-z]+\.conf|\w+\(\)', part)):
            concepts.append(part)

    if len(concepts) > 1:
        base = re.sub(
            r'(?:and|&|\+|with|vs|versus|or)\s*$', '',
            re.sub(r'\s+', ' ', query_lower).strip(),
            flags=re.IGNORECASE
        ).strip()
        for c in concepts:
            base = re.sub(re.escape(c), '', base, flags=re.IGNORECASE)
        return True, [(f"{base.strip()} {c}".strip() if base.strip() else c) for c in concepts]

    return False, [query]


def merge_subquery_chunks(
    chunks_per_query: List[List[dict]],
    k: int = 10,
    sub_queries: Optional[List[str]] = None,
) -> List[dict]:
    """Merge chunks from multiple sub-queries ensuring coverage.
    Optionally tags each chunk with its source sub-query."""
    if not chunks_per_query or len(chunks_per_query) == 1:
        result = chunks_per_query[0][:k] if chunks_per_query else []
        if sub_queries and len(sub_queries) >= 1:
            for ch in result:
                ch.setdefault('metadata', {})['_sub_query'] = sub_queries[0]
        return result

    merged, seen = [], set()
    min_per = max(1, k // len(chunks_per_query))

    for idx, clist in enumerate(chunks_per_query):
        sq = sub_queries[idx] if sub_queries and idx < len(sub_queries) else None
        for ch in clist[:min_per]:
            fp = ch.get('metadata', {}).get('fingerprint') or ch.get('page_content', '')[:100]
            if fp not in seen:
                if sq:
                    ch.setdefault('metadata', {})['_sub_query'] = sq
                merged.append(ch)
                seen.add(fp)
                if len(merged) >= k:
                    return merged

    for i in range(min_per, max(len(c) for c in chunks_per_query)):
        for idx, clist in enumerate(chunks_per_query):
            if i < len(clist):
                ch = clist[i]
                fp = ch.get('metadata', {}).get('fingerprint') or ch.get('page_content', '')[:100]
                if fp not in seen:
                    sq = sub_queries[idx] if sub_queries and idx < len(sub_queries) else None
                    if sq:
                        ch.setdefault('metadata', {})['_sub_query'] = sq
                    merged.append(ch)
                    seen.add(fp)
                    if len(merged) >= k:
                        return merged
    return merged


def build_comparison_context(
    sub_results: List[List[dict]],
    sub_queries: List[str],
) -> str:
    """Build a structured comparison context from parallel sub-query results.

    Returns a formatted markdown string with side-by-side information for each
    item being compared, suitable for injection into the LLM context.
    """
    if not sub_results or not sub_queries:
        return ""

    sections = []
    sections.append("## Comparison Context\n")
    sections.append(
        "The user is comparing the following items. "
        "Present a structured comparison highlighting similarities and differences.\n"
    )

    for idx, (query, chunks) in enumerate(zip(sub_queries, sub_results)):
        item_label = query.strip().split()[-1] if query.strip() else f"Item {idx + 1}"
        section_lines = [f"### {item_label.upper()}"]
        section_lines.append(f"*Source query: {query}*\n")

        if chunks:
            for chunk in chunks[:5]:  # Top 5 chunks per item
                content = chunk.get('page_content', '')
                if content:
                    # Trim to reasonable size
                    if len(content) > 800:
                        content = content[:800] + "..."
                    section_lines.append(content)
                    section_lines.append("")  # blank line
        else:
            section_lines.append("*No specific documentation found for this item.*\n")

        sections.append("\n".join(section_lines))

    sections.append(
        "\n### Comparison Instructions\n"
        "Compare the above items across these dimensions where applicable:\n"
        "- **Purpose**: What each is designed for\n"
        "- **Syntax**: How each is used\n"
        "- **Performance**: Relative efficiency\n"
        "- **Use Cases**: When to prefer one over the other\n"
        "- **Limitations**: Known constraints or gotchas"
    )

    return "\n\n".join(sections)


# ------------------------------------------------------------------
# Chunk scoring and filtering
# ------------------------------------------------------------------

def _calculate_token_overlap(text: str, metadata_line: str, query_tokens: set) -> int:
    """Calculates the token overlap score for a chunk."""
    content_lower = text.lower()
    content_matches = sum(1 for tok in query_tokens if tok in content_lower)
    metadata_lower = metadata_line.lower()
    metadata_matches = sum(1 for tok in query_tokens if tok in metadata_lower)
    metadata_bonus = int(0.5 * metadata_matches)
    return content_matches + metadata_bonus

def _calculate_boosts(text: str, chunk: dict, user_input: str, is_conf_match: bool) -> int:
    """Calculates the boost score for a chunk."""
    stanza_boost = 2 if "[" in text and "]" in text else 0
    conf_match_boost = 5 if is_conf_match else 0

    app_boost = 0
    app_match = re.search(
        r"""(?:(?:in|for|from)\s+)?app(?:lication)?[:\s]+['\"]?([a-zA-Z0-9_-]+)['\"]?"""
        r"""|['\"]([a-zA-Z0-9_]+-(?:es|search|itsi|mltk|ds|dma|UI[_a-zA-Z0-9]*))['\"]""",
        user_input, re.IGNORECASE
    )
    if app_match:
        app_name = (app_match.group(1) or app_match.group(2) or "").lower()
        if app_name and app_name not in {'the', 'this', 'that', 'with', 'name', 'type', 'called'}:
            chunk_app = chunk.get('app_name', '').lower()
            if app_name in chunk_app or chunk_app in app_name:
                app_boost = 15

    stanza_boost_extra = 0
    chunk_stanza = chunk.get('stanza', '').lower()
    if chunk_stanza and chunk_stanza != '__preamble__':
        stanza_patterns = re.findall(
            r'(monitor://[\w/.-]+|wineventlog://[\w/.-]+|script://[\w/.-]+|\[[\w:/ ._-]+\])',
            user_input.lower()
        )
        for pattern in stanza_patterns:
            pattern_clean = pattern.strip('[]')
            if pattern_clean in chunk_stanza or chunk_stanza in pattern_clean:
                stanza_boost_extra = 20

        if stanza_boost_extra == 0 and len(chunk_stanza) >= 4:
            input_lower = user_input.lower()
            stanza_variants = [chunk_stanza, chunk_stanza.replace('_', ' '), chunk_stanza.replace('-', ' ')]
            for variant in stanza_variants:
                if variant in input_lower:
                    stanza_boost_extra = 25
                    break

    savedsearch_boost = 0
    if chunk.get('is_savedsearch') or chunk.get('conf_type') == 'savedsearch':
        input_lower = user_input.lower()
        if any(kw in input_lower for kw in ['saved search', 'savedsearch', 'saved_search', 'alert', 'scheduled', 'report']):
            savedsearch_boost = 10

    vs_score_boost = min(chunk.get('score', 0) // 10, 20)

    return stanza_boost + conf_match_boost + app_boost + stanza_boost_extra + savedsearch_boost + vs_score_boost

def score_and_filter_chunks(
    memory_chunks: List[dict],
    user_input: str,
    conf_files: List[str],
    user_settings: dict,
    map_source_to_url=None,
    use_reranking: bool = True,
    intent: str = "",
) -> List[tuple]:
    """
    Score and filter chunks based on token overlap, metadata, and confidence.
    Optionally re-scores with a cross-encoder reranker for better semantic relevance.

    Returns list of (score, ref, text, source, chunk_dict) tuples, sorted by score descending.
    """
    from chat_app.reranker import reranker
    has_conf_context = bool(conf_files)
    query_tokens = {t for t in re.split(r'[^a-z0-9]+', user_input.lower()) if len(t) >= 3}
    scored_chunks = []

    for chunk in memory_chunks:
        text = chunk.get("text", "")
        source = chunk.get("source") or ""

        ref = chunk.get("source_url")
        if not ref and map_source_to_url:
            ref = map_source_to_url(source)
        if not ref and source:
            basename = os.path.basename(str(source))
            if basename.endswith((".spec", ".conf")):
                ref = f"/public/documents/specs/{basename}"
        if not ref and source.startswith("feedback://"):
            ref = "feedback://previous-answer"

        is_conf_match = False
        if has_conf_context and conf_files:
            for conf_file in conf_files:
                conf_name = conf_file.replace('.spec', '').replace('.conf', '')
                if conf_name in source.lower():
                    is_conf_match = True
                    break

        metadata_line = ""
        actual_content = text
        if text.startswith("# App:") or text.startswith("# Path:"):
            lines = text.split('\n', 1)
            metadata_line = lines[0] if lines else ""
            actual_content = lines[1] if len(lines) > 1 else text

        overlap = _calculate_token_overlap(actual_content, metadata_line, query_tokens)

        num_query_tokens = len(query_tokens)
        min_overlap = 1 if num_query_tokens <= 4 else 2
        if has_conf_context and ("feedback:" in source.lower() or is_conf_match):
            min_overlap = max(1, min_overlap - 1)
        if 'org_repo' in chunk.get('collection', ''):
            min_overlap = 0

        chunk_score = chunk.get('score', 0)
        min_passing_score = 25
        if overlap < min_overlap and chunk_score < min_passing_score:
            continue

        boosts = _calculate_boosts(text, chunk, user_input, is_conf_match)
        score = overlap + boosts
        scored_chunks.append((score, ref, text.strip(), source, chunk))

    logger.info(f"After filtering: {len(scored_chunks)} chunks passed (from {len(memory_chunks)} total)")

    scored_chunks.sort(key=lambda x: -x[0])
    top_candidates = scored_chunks[:15]

    # Cross-encoder reranking for better semantic relevance
    if use_reranking and len(top_candidates) > 1:
        top_candidates = reranker.rerank(user_input, top_candidates, top_k=10, intent=intent)

    return top_candidates

# ------------------------------------------------------------------
# Context assembly
# ------------------------------------------------------------------

def format_chunk_with_metadata(text: str, chunk_dict: dict) -> str:
    """Format a chunk with its metadata header.

    Strips any existing enrichment prefix (from enrich_chunk_for_search) to avoid
    duplicate metadata lines in the LLM context.
    """
    # Strip existing metadata prefix if present (added during ingestion by enrich_chunk_for_search)
    clean_text = text
    if text.startswith("# App:") or text.startswith("# Path:") or text.startswith("# Type:"):
        lines = text.split('\n', 1)
        clean_text = lines[1] if len(lines) > 1 else text

    if chunk_dict.get("stanza"):
        metadata_line = "# "
        if chunk_dict.get("full_app_path"):
            metadata_line += f"Path: {chunk_dict['full_app_path']} | "
        elif chunk_dict.get("app_name"):
            metadata_line += f"App: {chunk_dict['app_name']} | "
        if chunk_dict.get("deployment_tier"):
            metadata_line += f"Tier: {chunk_dict['deployment_tier']} | "
        if chunk_dict.get("deployment_target"):
            metadata_line += f"Deploys to: {chunk_dict['deployment_target']} | "
        if chunk_dict.get("stanza"):
            metadata_line += f"Stanza: [{chunk_dict['stanza']}] | "
        if chunk_dict.get("filename"):
            metadata_line += f"File: {chunk_dict['filename']}"
        if chunk_dict.get("conf_type"):
            metadata_line += f" | Type: {chunk_dict['conf_type']}"
        if chunk_dict.get("is_savedsearch"):
            metadata_line += " (SavedSearch)"
        return f"{metadata_line}\n{clean_text}"
    return clean_text


def scrub_lines(lines: List[str]) -> List[str]:
    """Remove noise and PII from text snippets.

    For multi-line items (conf stanzas), only remove noise LINES within the item,
    never drop the entire item.
    """
    noise_patterns = ["generated for", "not for distribution"]
    cleaned = []
    for ln in lines:
        if not ln:
            continue
        # Multi-line items (conf stanzas): scrub individual lines, keep the item
        if '\n' in ln:
            scrubbed_lines = []
            for sub_line in ln.split('\n'):
                sub_lower = sub_line.lower()
                if any(pat in sub_lower for pat in noise_patterns):
                    continue
                scrubbed_lines.append(sub_line.replace("file://", ""))
            if scrubbed_lines:
                cleaned.append('\n'.join(scrubbed_lines).strip())
        else:
            txt = ln.replace("file://", "")
            if any(pat in txt.lower() for pat in noise_patterns):
                continue
            cleaned.append(txt.strip())
    return cleaned


def format_section(header: str, items: List[str]) -> str:
    """Format a context section with header.

    Multi-line items (like conf stanzas) are separated by blank lines
    instead of bullet points to preserve structure.
    """
    if not items:
        return ""
    # Check if any item is multi-line (conf stanza data)
    has_multiline = any('\n' in item for item in items)
    if has_multiline:
        # Use blank-line separation for multi-line items (preserves stanza structure)
        return "\n".join([header, "", *[f"{item}\n" for item in items]])
    return "\n".join([header, *[f"* {item}" for item in items]])


def filter_references(all_refs: List[str], user_input: str) -> List[str]:
    """Filter references - remove .spec files unless explicitly queried."""
    has_spec_query = (
        ".spec" in user_input.lower()
        or "specification" in user_input.lower()
        or "spec file" in user_input.lower()
    )

    filtered_refs = []
    for ref in all_refs:
        if ref and ".spec" in ref and not has_spec_query:
            continue
        if ref == "feedback://previous-answer":
            continue
        filtered_refs.append(ref)

    return filtered_refs[:10]


def classify_references(refs: List[str]) -> List[Tuple[str, str, str]]:
    """Classify references into types for display."""
    valid_refs = []
    for ref in refs[:10]:
        if not ref:
            continue

        if ref == "feedback://previous-answer" or ref.startswith("feedback://"):
            valid_refs.append(("feedback", ref, "Previously validated answer"))
            continue

        if "/feedback/" in ref and ref.startswith("http"):
            filename = ref.split('/')[-1]
            if filename.endswith(".html") and filename.startswith("feedback_"):
                valid_refs.append(("feedback", ref, "Validated answer"))
                continue

        if "/documents/pdfs/" in ref or "/documents/docs/" in ref:
            filename = ref.split('/')[-1]
            if filename.endswith(('.pdf', '.html', '.md', '.txt')):
                valid_refs.append(("doc", ref, filename))
                continue

        if ref.startswith("http") and "/specs/" not in ref and ".spec" not in ref:
            if "://" in ref and "." in ref.split("/")[2]:
                display = ref.split('/')[-1] or ref.split('/')[2]
                valid_refs.append(("link", ref, display))
                continue

    return valid_refs


# ------------------------------------------------------------------
# Source citations
# ------------------------------------------------------------------

_COLLECTION_DISPLAY_NAMES: Dict[str, str] = {
    "spl_commands": "SPL Docs",
    "specs_mxbai": "Spec Files",
    "org_repo": "Org Configs",
    "assistant_memory": "Metadata",
    "self_learned_qa": "Learned Q&A",
    "local_docs": "Local Docs",
    "cribl_docs": "Cribl Docs",
    "feedback": "Feedback",
}


def _friendly_collection_name(raw_name: str) -> str:
    """Map a raw ChromaDB collection name to a friendly display label."""
    if not raw_name:
        return "Unknown"
    raw_lower = raw_name.lower()
    for fragment, label in _COLLECTION_DISPLAY_NAMES.items():
        if fragment in raw_lower:
            return label
    # Fallback: strip trailing _mxbai*, _embed*, _v\d+ suffixes
    clean = re.sub(r'[_-](?:mxbai|embed|large|v\d+).*$', '', raw_name, flags=re.IGNORECASE)
    return clean.replace("_", " ").title()


def _resolve_doc_display_name(chunk_dict: dict, ref: str, source: str) -> str:
    """Derive a human-readable document name from chunk metadata."""
    # Priority 1: filename + stanza
    filename = chunk_dict.get("filename", "")
    stanza = chunk_dict.get("stanza", "")
    if filename and stanza and stanza != "__preamble__":
        return f"{filename} [{stanza}]"
    # Priority 2: filename alone
    if filename:
        return filename
    # Priority 3: topic metadata
    topic = chunk_dict.get("topic", "")
    if topic:
        return topic
    # Priority 4: source basename
    if source:
        basename = os.path.basename(str(source))
        if basename and basename != source:
            return basename
    # Priority 5: ref basename
    if ref:
        basename = os.path.basename(str(ref))
        if basename:
            return basename
    return "document"


def build_sources_section(
    scored_chunks: List[tuple],
    show_sources: bool,
    max_docs: int = 3,
) -> str:
    """Build a Sources section showing which collections and documents contributed.

    Each scored_chunk is a (score, ref, text, source, chunk_dict) tuple.
    Returns empty string if show_sources is False or no chunks.
    """
    if not show_sources or not scored_chunks:
        return ""

    # Tally chunks per collection
    collection_counts: Dict[str, int] = {}
    doc_entries: List[Tuple[str, str]] = []  # (display_name, annotation)
    seen_docs: set = set()

    for item in scored_chunks:
        chunk_dict = item[4] if len(item) > 4 else {}
        ref = item[1] if len(item) > 1 else ""
        source = item[3] if len(item) > 3 else ""

        coll_raw = chunk_dict.get("collection", "") or ""
        coll_label = _friendly_collection_name(coll_raw)
        collection_counts[coll_label] = collection_counts.get(coll_label, 0) + 1

        # Gather top document names (deduplicated)
        if len(doc_entries) < max_docs:
            doc_name = _resolve_doc_display_name(chunk_dict, ref, source)
            if doc_name not in seen_docs:
                seen_docs.add(doc_name)
                # Annotate special source types
                source_type = chunk_dict.get("source_type", "") or chunk_dict.get("kind", "")
                if source_type == "cross_collection_insight":
                    annotation = "*(cross-collection insight)*"
                elif source_type == "self_learned_qa":
                    origin = chunk_dict.get("topic", "")
                    annotation = f"*(learned from {origin})*" if origin else "*(learned)*"
                else:
                    annotation = ""
                doc_entries.append((doc_name, annotation))

    # Build the summary line
    coll_parts = [f"{name} ({count} chunk{'s' if count != 1 else ''})"
                  for name, count in sorted(collection_counts.items(), key=lambda x: -x[1])]
    lines = [f"**Sources:** {', '.join(coll_parts)}"]

    # Optionally list top documents
    for doc_name, annotation in doc_entries:
        entry = f"  - {doc_name}"
        if annotation:
            entry += f" {annotation}"
        lines.append(entry)

    return "\n".join(lines)


def compute_confidence(
    local_spec_content: List[str],
    all_refs: List[str],
    filtered_count: int,
    doc_snippets: List[str],
) -> str:
    """Compute confidence label based on available sources."""
    has_specs = any("spec" in ref.lower() or ".conf" in ref.lower() for ref in all_refs)

    if local_spec_content or (has_specs and filtered_count >= 2):
        return "HIGH"
    elif doc_snippets or filtered_count >= 1:
        return "MEDIUM"
    else:
        return "LOW (General Knowledge)"


# ------------------------------------------------------------------
# Follow-up generation
# ------------------------------------------------------------------

async def generate_followups(user_input: str, has_conf_context: bool = False, engine=None) -> List[str]:
    """Generate contextually relevant follow-up questions."""
    dynamic_followups = []
    if engine:
        try:
            from feedback_logger import get_top_followups
            # Limit to 2 to leave space for static fallbacks
            dynamic_followups = await get_top_followups(engine, user_input, limit=2)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to get dynamic followups: {e}")

    q = user_input.lower()

    static_followups = []
    if has_conf_context or ".conf" in q or "spec" in q or "stanza" in q:
        static_followups = [
            "Show minimal stanza with required fields",
            "Explain precedence and merge rules for this configuration",
            "Common pitfalls (case sensitivity, scope, restart requirements)",
        ]
    elif any(kw in q for kw in ["search", "tstats", "cim", "datamodel"]):
        static_followups = [
            "Provide tstats example with this datamodel",
            "When to use summariesonly=true vs false",
            "Troubleshoot empty results (acceleration, permissions, mappings)",
        ]
    elif any(kw in q for kw in ["troubleshoot", "not working", "failed", "error", "issue"]):
        static_followups = [
            "Step-by-step diagnostic checklist",
            "Common root causes and solutions",
            "Relevant log files and btool commands",
        ]
    elif any(kw in q for kw in ["how to", "best practice", "recommend"]):
        static_followups = [
            "Provide concrete working example",
            "Industry best practices and gotchas",
            "Validation and testing approach",
        ]
    else:
        static_followups = [
            "Need a worked example for this scenario",
            "Common troubleshooting steps",
            "Best practices and validation checklist",
        ]

    # Merge dynamic and static, ensuring no duplicates and respecting the limit
    combined = list(dict.fromkeys(dynamic_followups + static_followups))
    return combined[:3]
