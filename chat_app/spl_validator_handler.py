"""
SPL validator handler for the Splunk Assistant.

Validation pipeline (in order):
  1. Local pattern-based validation (always runs, fast)
  2. Auto-correction via robust analyzer (if local validation fails)
  3. Splunk REST API validation via /services/search/parser (if validator available)
  4. Optimization hints appended to response
"""
import logging
import re
from typing import Dict, Any

import chainlit as cl
from shared.spl_validator import validate_spl_response, SPLValidator, ValidationStatus
from shared.spl_robust_analyzer import analyze_spl
from metrics import get_metrics
from chat_app.spl_optimizer_handler import append_optimization_section

logger = logging.getLogger(__name__)


def _validate_with_splunk(query: str) -> Dict[str, Any]:
    """Validate SPL against the Splunk validator instance via REST API.

    Returns dict with keys: available, valid, errors, warnings.
    Gracefully returns available=False if the validator is not reachable.
    """
    try:
        from chat_app.settings import get_settings
        cfg = get_settings().splunk
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SPL_VALIDATOR] Settings unavailable: {exc}")
        return {"available": False, "reason": "Settings unavailable"}

    if not cfg.validator_host:
        return {"available": False, "reason": "Validator host not configured"}

    try:
        import requests
        from urllib3.exceptions import InsecureRequestWarning
        import urllib3
        urllib3.disable_warnings(InsecureRequestWarning)
    except ImportError:
        return {"available": False, "reason": "requests library not installed"}

    result: Dict[str, Any] = {
        "available": False,
        "valid": None,
        "errors": [],
        "warnings": [],
    }

    try:
        url = f"https://{cfg.validator_host}:{cfg.validator_port}/services/search/parser"
        response = requests.post(
            url,
            auth=(cfg.validator_user, cfg.validator_pass),
            data={"q": query, "output_mode": "json", "parse_only": "true"},
            verify=cfg.get_ssl_verify(),
            timeout=10,
        )

        result["available"] = True

        if response.status_code == 200:
            data = response.json()
            result["valid"] = True
            if "messages" in data:
                for msg in data["messages"]:
                    msg_type = msg.get("type", "").upper()
                    msg_text = msg.get("text", "")
                    if msg_type == "ERROR":
                        result["errors"].append(msg_text)
                        result["valid"] = False
                    elif msg_type in ("WARN", "WARNING"):
                        result["warnings"].append(msg_text)
        elif response.status_code == 400:
            result["valid"] = False
            try:
                error_data = response.json()
                if "messages" in error_data:
                    for msg in error_data["messages"]:
                        result["errors"].append(msg.get("text", str(msg)))
                else:
                    result["errors"].append(error_data.get("detail", str(error_data)))
            except Exception as _exc:  # broad catch — resilience against all failures
                result["errors"].append(response.text[:500])
        else:
            result["errors"].append(f"Unexpected status: {response.status_code}")

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        err_type = type(e).__name__
        if "ConnectionError" in err_type or "ConnectTimeout" in err_type:
            result["available"] = False
            result["reason"] = f"Cannot reach Splunk validator at {cfg.validator_host}:{cfg.validator_port}"
        else:
            result["available"] = True
            result["errors"].append(f"Validation error: {e}")

    return result


async def validate_spl_in_response(user_input: str, result_text: str, chain) -> str:
    """Validate and optionally auto-correct SPL in the response."""
    user_lower = user_input.lower()
    metrics = get_metrics()
    is_query_request = (
        any(keyword in user_lower for keyword in ['tstats', 'term', 'spl']) or
        (any(verb in user_lower for verb in ['create', 'generate', 'write', 'show me', 'give me']) and
         any(noun in user_lower for noun in ['query', 'search', 'example']))
    )
    # Also validate when user input is raw SPL (index=, |stats, etc.)
    is_raw_spl = bool(re.search(r'\bindex\s*=|\|\s*stats\b|\|\s*tstats\b|\|\s*eval\b|\|\s*where\b', user_lower))
    has_code_block = '```' in result_text

    if (is_query_request or is_raw_spl) and has_code_block:
        logger.info("Validating SPL in response")
        is_valid, extracted_query, validation_errors = validate_spl_response(result_text)

        if not extracted_query:
            return result_text

        metrics.increment("splgen.generated_total")

        # Always run local validator to surface risk/perf hints
        base_validation = SPLValidator.validate(extracted_query, block_dangerous=False)

        if not is_valid and validation_errors:
            metrics.increment("splgen.initially_invalid")
            try:
                logger.info(f"Attempting robust analysis and auto-fix for: {extracted_query[:80]}")
                analysis_result = analyze_spl(extracted_query, auto_fix=True)

                if analysis_result.optimized_query and analysis_result.optimized_query != extracted_query:
                    corrected_query = analysis_result.optimized_query
                    corrected_val_result = SPLValidator.validate(corrected_query, block_dangerous=False)

                    if corrected_val_result.status in (ValidationStatus.VALID, ValidationStatus.WARNING):
                        logger.info(f"Robust analyzer corrected invalid SPL: {extracted_query[:60]}... -> {corrected_query[:60]}...")
                        result_text = result_text.replace(extracted_query, corrected_query)
                        base_validation = corrected_val_result
                        extracted_query = corrected_query
                        metrics.increment("splgen.corrected_success")
                    else:
                        logger.warning(f"Robust analyzer produced a still-invalid query: {corrected_query[:80]}")
                        metrics.increment("splgen.corrected_fail")
                        cl.user_session.set("last_spl_gen_failed", True)
                        cl.user_session.set("bad_spl_info", {"spl": extracted_query, "errors": validation_errors})
                        error_msg = "\n\n**Query Validation Failed:**\n" + "\n".join(f"- {err}" for err in validation_errors)
                        result_text += error_msg
                else:
                    metrics.increment("splgen.corrected_fail")
                    cl.user_session.set("last_spl_gen_failed", True)
                    cl.user_session.set("bad_spl_info", {"spl": extracted_query, "errors": validation_errors})
                    error_msg = "\n\n**Query Validation Failed:**\n" + "\n".join(f"- {err}" for err in validation_errors)
                    if analysis_result.issues:
                        error_msg += "\n\n**Analysis Issues Found:**\n" + "\n".join(
                            f"- **{issue.severity.value.upper()}**: {issue.message}" for issue in analysis_result.issues
                        )
                    result_text += error_msg

            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.error(f"Robust analyzer failed unexpectedly: {e}. Falling back to showing basic errors.")
                metrics.increment("splgen.corrected_fail")
                cl.user_session.set("last_spl_gen_failed", True)
                cl.user_session.set("bad_spl_info", {"spl": extracted_query, "errors": validation_errors})
                error_msg = "\n\n**Query Validation Failed:**\n" + "\n".join(f"- {err}" for err in validation_errors)
                result_text += error_msg
        else:
            if is_valid:
                metrics.increment("splgen.initially_valid")

        # ---- Splunk REST API validation (if validator container is available) ----
        try:
            splunk_result = _validate_with_splunk(extracted_query)
            if splunk_result["available"]:
                metrics.increment("splgen.splunk_validated")
                if splunk_result["valid"]:
                    logger.info(f"Splunk validator confirmed query is valid: {extracted_query[:60]}...")
                    metrics.increment("splgen.splunk_valid")
                    result_text += "\n\n**Splunk Validation:** Confirmed valid by Splunk search parser."
                    if splunk_result.get("warnings"):
                        warnings_text = "\n".join(f"- {w}" for w in splunk_result["warnings"])
                        result_text += f"\n\n**Splunk Warnings:**\n{warnings_text}"
                else:
                    logger.warning(f"Splunk validator rejected query: {splunk_result['errors']}")
                    metrics.increment("splgen.splunk_invalid")
                    errors_text = "\n".join(f"- {e}" for e in splunk_result["errors"])
                    result_text += f"\n\n**Splunk Validation Failed:**\n{errors_text}"
                    result_text += "\n\nThe query has syntax issues detected by the Splunk search parser. Please review before using."
            else:
                logger.debug(f"Splunk validator not available: {splunk_result.get('reason', 'unknown')}")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.debug(f"Splunk validation skipped: {e}")

        # Attempt local optimization and surface ranking/risk deltas
        result_text = append_optimization_section(result_text, extracted_query, base_validation)

    return result_text
