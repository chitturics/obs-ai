"""
SPL query optimization: tstats conversion, TERM/PREFIX wrapping, suggestions.

Combines hardcoded optimization rules with official Splunk documentation
and learned patterns from user feedback for more accurate and comprehensive suggestions.
"""
import re
import logging
from typing import Any, Dict, List

from shared.spl_query_optimizer import SPLQueryOptimizer, ConversionStatus
from shared.spl_knowledge_base import get_knowledge_base
from .learning import apply_learned_patterns

logger = logging.getLogger(__name__)


def _optimize_query(query: str) -> Dict[str, Any]:
    """Optimize a query using tstats conversion, or provide improvement suggestions."""
    result = SPLQueryOptimizer.optimize(query)
    suggestions = _generate_optimization_suggestions(query)

    if result.status == ConversionStatus.IMPOSSIBLE:
        improved = _apply_simple_optimizations(query)
        return {
            "optimized": improved != query,
            "reason": result.explanation,
            "blockers": result.blockers,
            "suggestions": suggestions,
            "optimized_query": improved if improved != query else None,
        }

    return {
        "optimized": True,
        "strategy": result.strategy.value,
        "original": result.original,
        "optimized_query": result.optimized,
        "performance_notes": result.performance_notes,
        "assumptions": result.assumptions,
        "suggestions": suggestions,
    }


def _generate_optimization_suggestions(query: str) -> List[str]:
    """Generate optimization suggestions for any query."""
    suggestions = []
    ql = query.lower()

    if "index=*" in ql:
        suggestions.append("Replace index=* with specific index(es) - searching all indexes is very slow")
    if "| join " in ql:
        suggestions.append("Consider replacing 'join' with 'lookup' for enrichment, or 'stats' for aggregation-based joins")
    if "| transaction " in ql:
        suggestions.append("Consider replacing 'transaction' with 'stats earliest(_time) latest(_time) values() by session_id' for session grouping")
    if ql.count("| eval ") > 2:
        suggestions.append("Combine multiple eval commands into one: | eval field1=expr1, field2=expr2")
    if "| table " in ql and ql.index("| table ") < len(ql) - 50:
        suggestions.append("Move 'table' to the end of the pipeline - it should be the final formatting step")
    if "| search " in ql and ql.count("| search ") > 0:
        suggestions.append("Consider moving search filters before the first pipe for better performance")
    if re.search(r'"[^"]+\.[^"]+"', query) and "term(" not in ql:
        suggestions.append("Wrap literal strings containing dots in TERM() for exact matching: TERM(field=value)")
    if re.search(r'\w+=\w+\*(?!\*)', query) and "prefix(" not in ql:
        suggestions.append("Use PREFIX() for prefix wildcard matching: PREFIX(field=value) instead of field=value*")
    if "| stats count" in ql and "| tstats" not in ql:
        has_blocking_wildcard = bool(re.search(r'\*\w|\w\*\w', query))
        if "index=" in ql and "| rex " not in ql and "| eval " not in ql.split("| stats")[0] and not has_blocking_wildcard:
            suggestions.append("This query may be convertible to tstats for 10-100x speedup if aggregating by indexed fields only")
    if "| dedup " in ql:
        suggestions.append("Consider using '| stats count by field' instead of '| dedup field' if you don't need to preserve event data")

    # Add official doc-based suggestions for commands in the query
    try:
        kb = get_knowledge_base()
        if kb and kb.docs:
            commands_in_query = set(re.findall(r'\|\s*(\w+)\b', ql))
            for cmd in commands_in_query:
                if len(suggestions) >= 10:
                    break  # Cap total suggestions to keep output focused
                limitations = kb.docs.get_command_limitations(cmd)
                for limit in limitations[:1]:
                    suggestions.append(f"[{cmd}] {limit}")

                if cmd in ("stats", "tstats", "join", "transaction", "sort"):
                    limits_info = kb.docs.get_limits_info(cmd)
                    for setting, desc in list(limits_info.items())[:1]:
                        if "default" in desc.lower():
                            suggestions.append(f"[{cmd}] limits.conf: {setting} - {desc[:150]}")
    except Exception:
        pass  # Docs enrichment is optional; don't break suggestions

    # Add suggestions from learned feedback patterns
    try:
        learned = apply_learned_patterns(query)
        for pattern in learned:
            if len(suggestions) >= 12:
                break
            desc = pattern.get("description", "")
            source = pattern.get("learned_from", "feedback")
            suggestions.append(f"[learned from {source}] {desc}")
    except Exception:
        pass  # Learning is optional; don't break suggestions

    return suggestions


def _apply_simple_optimizations(query: str) -> str:
    """Apply simple, safe optimizations that don't require tstats conversion."""
    improved = query
    ql = query.lower()

    def add_term_wrapper(match):
        field = match.group(1)
        value = match.group(2).strip('"\'')
        if '.' in value or ':' in value:
            return f'TERM({field}={value})'
        return match.group(0)

    if "term(" not in ql:
        improved = re.sub(
            r'\b(\w+)\s*=\s*["\']?([^"\'\s]+\.[^"\'\s]+)["\']?(?!\))',
            add_term_wrapper,
            improved
        )

    if "prefix(" not in ql:
        def add_prefix_wrapper(match):
            field = match.group(1)
            value = match.group(2).rstrip('*')
            return f'PREFIX({field}={value})'

        improved = re.sub(
            r'\b(\w+)\s*=\s*([^\s*]+)\*(?!\*)',
            add_prefix_wrapper,
            improved
        )

    return improved


def _apply_time_bounds(query: str, earliest: str = "-24h", latest: str = "now") -> str:
    """Add earliest/latest if missing."""
    if "earliest=" in query and "latest=" in query:
        return query

    q = query.strip()
    if q.startswith("|"):
        rest = q[1:].lstrip()
        parts = rest.split("|", 1)
        tstats_stage = parts[0].strip()
        if "earliest=" not in tstats_stage:
            tstats_stage += f" earliest={earliest}"
        if "latest=" not in tstats_stage:
            tstats_stage += f" latest={latest}"
        if len(parts) == 2:
            return f"| {tstats_stage} |{parts[1]}"
        return f"| {tstats_stage}"

    base, *rest = q.split("|", 1)
    base = base.strip()
    if "earliest=" not in base:
        base += f" earliest={earliest}"
    if "latest=" not in base:
        base += f" latest={latest}"
    if rest:
        return f"{base} |{rest[0]}"
    return base


def _simple_improvement(query: str, validation) -> Dict[str, Any] | None:
    """Comprehensive improvements for SPL queries."""
    improved = query
    notes = []
    ql = query.lower()

    has_macros = bool(re.search(r'(?<!`)(?<!``)`[^`]+`(?!`)(?!``)', query))

    if validation and getattr(validation, "parsed_components", None):
        components = validation.parsed_components
        if not components.get("has_time_constraint"):
            notes.append("TIP: Consider time bounds (earliest/latest) if not set in time picker.")
        if components.get("indexes") == []:
            if has_macros:
                notes.append("INFO: No explicit index= found. Check if your macros define the index.")
            else:
                notes.append("CRITICAL: No index specified - add index=... to avoid scanning all indexes.")
        if components.get("sourcetypes") == [] and not has_macros:
            notes.append("TIP: Adding sourcetype=... can improve performance.")

    improved = _apply_simple_optimizations(improved)

    if "index=*" in ql:
        notes.append("CRITICAL: index=* scans ALL indexes - specify the actual index(es) needed.")
    if "| join " in ql:
        notes.append("'join' is expensive (50k result limit in subsearch). Consider using 'lookup' for enrichment.")
    if "| transaction " in ql:
        notes.append("'transaction' is very memory-intensive. Consider 'stats' with earliest(_time)/latest(_time) instead.")
    if ql.count("| eval ") > 2:
        notes.append("Multiple eval commands detected. Combine into one: | eval a=1, b=2, c=3")
    if "| append [" in ql or "| append[" in ql:
        notes.append("'append' with subsearch has result limits. Consider 'multisearch' or 'union' for combining searches.")
    if "| sort " in ql and "| head " not in ql and "| tail " not in ql:
        notes.append("'sort' on large datasets is memory-intensive. Consider adding '| head N' to limit results.")

    if improved != query or notes:
        return {
            "improved_query": improved if improved != query else None,
            "notes": notes
        }
    return None
