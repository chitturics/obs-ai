import logging
import re
from typing import Optional, Dict, Any

import httpx

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

# Track if we've already warned about the service being unavailable
_service_unavailable_warned = False


def _detect_type(query: str, profile: Optional[str]) -> str:
    ql = query.lower()
    if profile == "spl_expert":
        return "spl"
    if any(tok in ql for tok in ["|", "index=", "sourcetype=", "tstats", "eval ", "stats "]):
        return "spl"
    if re.search(r"\bselect\b.*\bfrom\b", ql):
        return "sql"
    return "nlp"


async def call_search_optimizer(
    query: str,
    profile: Optional[str] = None,
    action: str = "optimize",
    force_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Call the external search optimization container.

    Args:
        query: The SPL query or natural language input
        profile: User profile (e.g., "spl_expert") for type detection
        action: Action to perform - optimize, review, explain, score, annotate, auto, learn
        force_type: Force input type - "spl", "nlp", or "sql" (auto-detects if None)

    Returns:
        Analysis result dict, or None if service unavailable

    Environment:
        SEARCH_OPT_URL: Service URL (default: http://127.0.0.1:9005)
        SEARCH_OPT_ENABLED: Set to "false" to disable calls entirely
    """
    cfg = get_settings().search_optimizer
    if not cfg.enabled:
        return None

    base_url = cfg.url
    url = base_url.rstrip("/") + "/analyze"
    detected_type = force_type if force_type else _detect_type(query, profile)
    payload = {
        "sql_query": query,
        "type": detected_type,
        "action": action,
    }

    global _service_unavailable_warned
    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            _service_unavailable_warned = False  # Reset if successful
            return resp.json()
    except httpx.ConnectError:
        # Service not running - warn once, then debug
        if not _service_unavailable_warned:
            logger.info(f"Search optimizer not available at {base_url} - optimization features disabled")
            _service_unavailable_warned = True
        return None
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"Search optimizer call failed: {exc}")
        return None


async def explain_spl(query: str) -> Optional[Dict[str, Any]]:
    """
    Get step-by-step explanation of an SPL query.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + "/explain"

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"query": query})
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"SPL explain call failed: {exc}")
        return None


async def score_spl(query: str) -> Optional[Dict[str, Any]]:
    """
    Score an SPL query for quality and efficiency.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + "/score"

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"query": query})
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"SPL score call failed: {exc}")
        return None


async def annotate_spl(query: str) -> Optional[Dict[str, Any]]:
    """
    Add inline comments to an SPL query.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + "/annotate"

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"query": query})
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"SPL annotate call failed: {exc}")
        return None


async def auto_analyze_spl(input_text: str, force_intent: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Auto-detect intent and analyze SPL or natural language input.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + "/auto"
    payload = {"input": input_text}
    if force_intent:
        payload["force_intent"] = force_intent

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"SPL auto-analyze call failed: {exc}")
        return None


async def call_robust_analyzer(
    query: str,
    auto_fix: bool = True,
    validate_with_splunk: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Call the robust SPL analyzer endpoint.

    Args:
        query: The SPL query to analyze.
        auto_fix: Whether to apply automatic fixes.
        validate_with_splunk: Whether to validate with a Splunk instance.

    Returns:
        The analysis result, or None if the service is unavailable.
    """
    cfg = get_settings().search_optimizer
    if not cfg.enabled:
        return None

    base_url = cfg.url
    url = base_url.rstrip("/") + "/analyze/robust"
    payload = {
        "query": query,
        "auto_fix": auto_fix,
        "validate_with_splunk": validate_with_splunk,
    }

    global _service_unavailable_warned
    try:
        timeout = httpx.Timeout(10.0)  # Longer timeout for robust analysis
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            _service_unavailable_warned = False
            return resp.json()
    except httpx.ConnectError:
        if not _service_unavailable_warned:
            logger.info(f"Search optimizer not available at {base_url} - robust analysis disabled")
            _service_unavailable_warned = True
        return None
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"Robust analyzer call failed: {exc}")
        return None


# ----------------------------
# Saved Search Management
# ----------------------------

async def analyze_all_saved_searches(force: bool = False) -> Optional[Dict[str, Any]]:
    """
    Trigger analysis of all saved searches.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + f"/savedsearches/analyze-all?force={str(force).lower()}"

    try:
        timeout = httpx.Timeout(120.0)  # Longer timeout for bulk analysis
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url)
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"Analyze all saved searches failed: {exc}")
        return None


async def get_saved_search(name: str) -> Optional[Dict[str, Any]]:
    """
    Get analysis for a specific saved search by name.
    Returns original query, optimized query, and all analysis data.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + f"/savedsearches/{name}"

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"Get saved search failed: {exc}")
        return None


async def list_saved_searches(limit: int = 100, sort_by: str = "name") -> Optional[Dict[str, Any]]:
    """
    List all analyzed saved searches.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + "/savedsearches/list"

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"limit": limit, "sort_by": sort_by})
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"List saved searches failed: {exc}")
        return None


async def submit_search_feedback(
    name: str,
    improved_query: str,
    notes: str = "",
    user: str = "anonymous",
    rank: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    Submit user feedback with an improved query.
    """
    base_url = get_settings().search_optimizer.url
    url = base_url.rstrip("/") + "/savedsearches/feedback"

    payload = {
        "name": name,
        "improved_query": improved_query,
        "notes": notes,
        "user": user,
        "rank": rank,
    }

    try:
        timeout = httpx.Timeout(6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"Submit search feedback failed: {exc}")
        return None


async def trigger_learning() -> Optional[Dict[str, Any]]:
    """
    Trigger the search optimizer's feedback learning endpoint.

    Extracts optimization patterns from high-ranked user feedback
    and persists them for future suggestion generation.

    Returns:
        Learning result dict, or None if service unavailable.
    """
    cfg = get_settings().search_optimizer
    if not cfg.enabled:
        return None

    base_url = cfg.url
    url = base_url.rstrip("/") + "/learn"

    global _service_unavailable_warned
    try:
        timeout = httpx.Timeout(15.0)  # Learning can take a moment
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url)
            resp.raise_for_status()
            _service_unavailable_warned = False
            return resp.json()
    except httpx.ConnectError:
        if not _service_unavailable_warned:
            logger.info(f"Search optimizer not available at {base_url} - learning disabled")
            _service_unavailable_warned = True
        return None
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning(f"Trigger learning call failed: {exc}")
        return None


def format_optimizer_context(result: Dict[str, Any]) -> str:
    """
    Convert optimizer JSON into a short context block.
    """
    lines = []
    lines.append(f"Action: {result.get('action')}")
    if "input_type" in result:
        lines.append(f"Type: {result.get('input_type')}")
    if generated := result.get("generated_query"):
        lines.append("Generated SPL:")
        lines.append("```spl")
        lines.append(generated)
        lines.append("```")
    if review := result.get("review"):
        lines.append(f"Validation status: {review.get('status')} (risk {review.get('risk_score')})")
        if review.get("errors"):
            lines.append("Errors: " + "; ".join(review["errors"]))
        if review.get("warnings"):
            lines.append("Warnings: " + "; ".join(review["warnings"]))
    if opt := result.get("optimization"):
        if opt.get("optimized"):
            lines.append(f"Optimization strategy: {opt.get('strategy')}")
            if opt.get("optimized_query"):
                lines.append("Optimized SPL:")
                lines.append("```spl")
                lines.append(opt["optimized_query"])
                lines.append("```")
        else:
            reason = opt.get("reason") or "Conversion not possible"
            lines.append(f"Optimization skipped: {reason}")
    if imp := result.get("improvement"):
        notes = imp.get("notes") or []
        if imp.get("improved_query"):
            lines.append("Suggested Improvement:")
            lines.append("```spl")
            lines.append(imp["improved_query"])
            lines.append("```")
        if notes:
            lines.append("Improvement notes: " + "; ".join(notes[:3]))
    if rp := result.get("remote_parse"):
        if rp.get("available"):
            lines.append(f"Splunk parser status: {rp.get('status','n/a')}")
            msgs = rp.get("messages") or []
            for m in msgs[:3]:
                lines.append(f"- {m.get('type')}: {m.get('text')}")
        else:
            lines.append(f"Splunk parser unavailable: {rp.get('reason','unknown')}")
    if bt := result.get("btool"):
        if bt.get("available"):
            lines.append("btool check: returncode {0}".format(bt.get("returncode")))
            if bt.get("stderr"):
                lines.append("btool stderr: " + bt["stderr"][:200])
        else:
            lines.append(f"btool unavailable: {bt.get('reason')}")
    if bt_repo := result.get("btool_repo_check"):
        if bt_repo.get("available"):
            lines.append("btool repo check rc: {0}".format(bt_repo.get("returncode")))
            if bt_repo.get("stderr"):
                lines.append("repo btool stderr: " + bt_repo["stderr"][:200])
        else:
            lines.append(f"repo btool unavailable: {bt_repo.get('reason')}")
    if sql := result.get("sql_lint"):
        if sql.get("ran") and sql.get("violations"):
            lines.append("SQL lint issues:")
            for v in sql["violations"][:3]:
                lines.append(f"- {v.get('code')} L{v.get('line')}C{v.get('position')}: {v.get('description')}")
        elif sql.get("error"):
            lines.append(f"SQL lint error: {sql['error']}")

    # Handle new SPL analyzer results
    if explanation := result.get("explanation"):
        if isinstance(explanation, dict) and explanation.get("explanation"):
            exp = explanation["explanation"]
            lines.append(f"Summary: {exp.get('summary', 'N/A')}")
            lines.append(f"Complexity: {exp.get('complexity', 'N/A')}")
            lines.append(f"Purpose: {exp.get('purpose', 'N/A')}")

    if score := result.get("score"):
        if isinstance(score, dict) and score.get("score"):
            sc = score["score"]
            lines.append(f"Quality Score: {sc.get('overall', 0)}/100")
            lines.append(f"  Readability: {sc.get('readability', 0)}/100")
            lines.append(f"  Efficiency: {sc.get('efficiency', 0)}/100")
            lines.append(f"  Best Practices: {sc.get('best_practices', 0)}/100")
            if sc.get("recommendations"):
                lines.append("Recommendations:")
                for rec in sc["recommendations"][:3]:
                    lines.append(f"  - {rec}")

    if annotation := result.get("annotation"):
        if isinstance(annotation, dict) and annotation.get("annotated_query"):
            lines.append("Annotated Query:")
            lines.append("```spl")
            lines.append(annotation["annotated_query"])
            lines.append("```")

    return "\n".join(lines)
