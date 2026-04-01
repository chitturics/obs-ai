"""
Knowledge Gap Detection — Identifies when the KB is insufficient.

Detects topics the user asks about that aren't covered in the
knowledge base, and suggests ingestion actions.
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeGap:
    """A detected gap in the knowledge base."""
    topic: str
    gap_type: str  # missing_entirely, sparse, outdated
    severity: str  # high, medium, low
    suggestion: str = ""
    ingest_url: Optional[str] = None


def detect_knowledge_gaps(
    user_query: str,
    retrieved_chunks: List[dict],
    chunk_threshold: int = 2,
) -> List[KnowledgeGap]:
    """
    Detect knowledge gaps by analyzing query topics vs retrieved content.

    Args:
        user_query: The user's question.
        retrieved_chunks: Chunks retrieved from vector search.
        chunk_threshold: Minimum chunks to consider a topic "covered".

    Returns:
        List of detected knowledge gaps.
    """
    gaps = []
    lower = user_query.lower()
    chunk_count = len(retrieved_chunks)
    chunk_text = " ".join(c.get("text", "")[:300] for c in retrieved_chunks[:10]).lower()

    # 1. Check for explicit Splunk product references not in context
    product_checks = [
        (r'\b(itsi|it service intelligence)\b', "ITSI",
         "Splunk ITSI documentation not found in knowledge base",
         "https://docs.splunk.com/Documentation/ITSI"),
        (r'\b(soar|phantom|playbook)\b', "SOAR/Phantom",
         "Splunk SOAR documentation not found",
         "https://docs.splunk.com/Documentation/SOARonprem"),
        (r'\b(enterprise security|es\b|notable event)', "Enterprise Security",
         "Enterprise Security content not found",
         "https://docs.splunk.com/Documentation/ES"),
        (r'\b(uba|user behavior analytics)\b', "UBA",
         "Splunk UBA documentation not found",
         "https://docs.splunk.com/Documentation/UBA"),
        (r'\b(mint|mobile intelligence)\b', "MINT",
         "Splunk MINT documentation not found", None),
        (r'\b(signal ?fx|o11y|observability cloud)\b', "Observability Cloud",
         "Splunk Observability Cloud docs not found",
         "https://docs.splunk.com/observability"),
        # Cribl products
        (r'\bcribl\s*stream\b', "Cribl Stream",
         "Cribl Stream documentation not found",
         "https://docs.cribl.io/stream"),
        (r'\bcribl\s*edge\b', "Cribl Edge",
         "Cribl Edge documentation not found",
         "https://docs.cribl.io/edge"),
        (r'\bcribl\s*search\b', "Cribl Search",
         "Cribl Search documentation not found",
         "https://docs.cribl.io/search"),
        (r'\bcribl\s*lake\b', "Cribl Lake",
         "Cribl Lake documentation not found",
         "https://docs.cribl.io/lake"),
        # Observability tools
        (r'\bopentelemetry\b|\botel\b|\botlp\b', "OpenTelemetry",
         "OpenTelemetry documentation not found",
         "https://opentelemetry.io/docs/"),
        (r'\bprometheus\b', "Prometheus",
         "Prometheus documentation not found",
         "https://prometheus.io/docs/"),
    ]

    for pattern, name, suggestion, url in product_checks:
        if re.search(pattern, lower) and not re.search(pattern, chunk_text):
            gaps.append(KnowledgeGap(
                topic=name,
                gap_type="missing_entirely",
                severity="high",
                suggestion=suggestion,
                ingest_url=url,
            ))

    # 2. Check for .conf files referenced but not in context
    # Use word-boundary matching in chunk_text to avoid false negatives
    conf_refs = re.findall(r'([a-z_]+\.conf(?:\.spec)?)', lower)
    for conf in conf_refs:
        # Check both the exact filename and the base name (e.g., "inputs" for "inputs.conf")
        base_name = conf.replace('.conf.spec', '').replace('.conf', '')
        if conf not in chunk_text and base_name not in chunk_text:
            gaps.append(KnowledgeGap(
                topic=conf,
                gap_type="sparse",
                severity="medium",
                suggestion=f"'{conf}' not found in knowledge base. Consider ingesting the spec file.",
            ))

    # 3. Check for Splunk commands referenced but not in context
    # Only look for pipe-commands in actual SPL code, not natural language
    spl_commands = re.findall(r'\|\s*(\w+)', user_query)  # Use original case to avoid NL false positives
    # Known SPL commands to validate against (avoid flagging natural language words)
    _KNOWN_SPL_COMMANDS = {
        'stats', 'eval', 'where', 'table', 'fields', 'search', 'rex', 'timechart',
        'tstats', 'join', 'lookup', 'sort', 'head', 'tail', 'dedup', 'transaction',
        'chart', 'top', 'rare', 'rename', 'fillnull', 'replace', 'convert', 'bin',
        'streamstats', 'eventstats', 'append', 'appendcols', 'multisearch', 'map',
        'foreach', 'mvexpand', 'mvcombine', 'makemv', 'spath', 'xmlkv', 'collect',
        'outputlookup', 'inputlookup', 'rest', 'metadata', 'datamodel', 'pivot',
        'predict', 'anomalydetection', 'cluster', 'kmeans', 'geostats', 'iplocation',
        'mcatalog', 'mstats', 'union', 'format', 'return', 'abstract', 'addinfo',
        'addtotals', 'bucket', 'contingency', 'delta', 'diff', 'erex', 'fieldformat',
        'fieldsummary', 'filldown', 'gentimes', 'highlight', 'makecontinuous',
        'makeresults', 'multikv', 'nomv', 'regex', 'reltime', 'overlap', 'set',
        'strcat', 'trendline', 'untable', 'xyseries', 'transpose',
    }
    for cmd in spl_commands:
        cmd_lower = cmd.lower()
        if cmd_lower in _KNOWN_SPL_COMMANDS and cmd_lower not in chunk_text and len(cmd_lower) > 2:
            gaps.append(KnowledgeGap(
                topic=f"SPL command: {cmd_lower}",
                gap_type="sparse",
                severity="low",
                suggestion=f"Command '{cmd_lower}' documentation may be missing.",
            ))

    # 4. Overall sparsity check
    if chunk_count < chunk_threshold and chunk_count > 0:
        gaps.append(KnowledgeGap(
            topic="general",
            gap_type="sparse",
            severity="medium",
            suggestion=f"Only {chunk_count} relevant chunks found. Consider ingesting more documentation on this topic.",
        ))
    elif chunk_count == 0:
        gaps.append(KnowledgeGap(
            topic="general",
            gap_type="missing_entirely",
            severity="high",
            suggestion="No relevant content found in any collection. This topic may not be covered.",
        ))

    # Deduplicate gaps by topic
    seen_topics = set()
    unique_gaps = []
    for gap in gaps:
        if gap.topic not in seen_topics:
            seen_topics.add(gap.topic)
            unique_gaps.append(gap)

    return unique_gaps


def format_gap_suggestions(gaps: List[KnowledgeGap]) -> Optional[str]:
    """Format knowledge gap suggestions for the user in a conversational tone."""
    if not gaps:
        return None

    high_gaps = [g for g in gaps if g.severity == "high"]
    medium_gaps = [g for g in gaps if g.severity == "medium" and g.gap_type == "missing_entirely"]

    actionable_gaps = high_gaps + medium_gaps
    if not actionable_gaps:
        return None

    lines = [
        "\n---\n"
        "**A note on coverage:** I noticed some gaps in my knowledge base "
        "that may have affected this answer:"
    ]
    for gap in actionable_gaps[:3]:
        line = f"- {gap.suggestion}"
        if gap.ingest_url:
            line += f"\n  I can learn more if you feed me this: `read_url: {gap.ingest_url}`"
        lines.append(line)

    lines.append(
        "\nYou can enrich my knowledge anytime with `/upload` or `read_url:`."
    )

    return "\n".join(lines)


def should_suggest_ingestion(gaps: List[KnowledgeGap]) -> bool:
    """Check if any gaps warrant an ingestion suggestion."""
    return any(g.severity in ("high", "medium") and g.gap_type == "missing_entirely" for g in gaps)
