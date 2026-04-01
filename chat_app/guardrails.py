"""Multi-layer guardrails — input/output safety for ObsAI."""
import re
import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)

PII_PATTERNS = {
    "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "phone": r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
    "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
    "credit_card": r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
    "ip_address": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
    "api_key": r'\b(?:sk-|api[_-]?key[=:\s]+)[A-Za-z0-9_-]{20,}\b',
}

INJECTION_PATTERNS = [
    r'ignore (?:all )?(?:previous |above )?instructions',
    r'you are now', r'forget (?:everything|all|your)', r'system prompt',
    r'override (?:your|the) (?:rules|instructions)',
    r'pretend (?:you are|to be)', r'act as (?:if|though)',
    r'new instructions?:', r'jailbreak', r'DAN mode',
]

_stats = {
    "input_checked": 0, "output_checked": 0, "input_blocked": 0,
    "pii_detected": 0, "injection_detected": 0, "output_pii_redacted": 0,
    "low_groundedness": 0,
}

def get_guardrail_stats() -> dict[str, int]:
    return dict(_stats)

def reset_guardrail_stats():
    for k in _stats:
        _stats[k] = 0

def GuardrailResult(**overrides):
    defaults = dict(passed=True, blocked=False, warnings=[], pii_detected=[],
                    injection_score=0.0, groundedness_score=1.0)
    defaults.update(overrides)
    # Fresh mutable lists per call
    if "warnings" not in overrides:
        defaults["warnings"] = []
    if "pii_detected" not in overrides:
        defaults["pii_detected"] = []
    return SimpleNamespace(**defaults)

def _emit_prometheus(phase: str, blocked=False, pii=False, injection=False):
    try:
        from chat_app.prometheus_metrics import record_guardrail_event
        record_guardrail_event(phase, blocked=blocked, pii=pii, injection=injection)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass


def check_input(text: str):
    r = GuardrailResult()
    _stats["input_checked"] += 1

    if len(text) > 10000:
        r.warnings.append("Input truncated to 10000 characters")
        text = text[:10000]

    # PII detection
    for pii_type, pattern in PII_PATTERNS.items():
        if matches := re.findall(pattern, text, re.IGNORECASE):
            r.pii_detected.append(f"{pii_type}: {len(matches)} found")
            r.warnings.append(f"PII detected: {pii_type}")
            _stats["pii_detected"] += 1

    # Injection scoring
    text_lower = text.lower()
    score = min(sum(0.3 for p in INJECTION_PATTERNS if re.search(p, text_lower)), 1.0)
    r.injection_score = score
    if score > 0.5:
        r.warnings.append(f"Possible prompt injection detected (score: {score:.1f})")
        logger.warning("[GUARDRAILS] injection score=%.1f input='%s...'", score, text[:100])
        _stats["injection_detected"] += 1
    if score > 0.8:
        r.blocked, r.passed = True, False
        _stats["input_blocked"] += 1

    _emit_prometheus("input", blocked=r.blocked, pii=bool(r.pii_detected), injection=(score > 0.5))
    return r


def check_output(response: str, sources: list[str] | None = None):
    r = GuardrailResult()
    _stats["output_checked"] += 1

    for pii_type, pattern in PII_PATTERNS.items():
        if re.search(pattern, response, re.IGNORECASE):
            r.pii_detected.append(f"{pii_type} in response")
            r.warnings.append(f"PII leaked in response: {pii_type}")
            _stats["output_pii_redacted"] += 1

    if sources:
        source_tokens = set(" ".join(s[:500] for s in sources).lower().split())
        sentences = [s.strip() for s in response.split('.') if len(s.strip()) > 20][:10]
        grounded = sum(1 for s in sentences
                       if len(set(s.lower().split()) & source_tokens) / max(len(s.split()), 1) > 0.3)
        r.groundedness_score = grounded / max(len(sentences), 1)
        if r.groundedness_score < 0.3:
            r.warnings.append(f"Low groundedness: {r.groundedness_score:.0%}")
            _stats["low_groundedness"] += 1

    _emit_prometheus("output", pii=bool(r.pii_detected))
    return r


def redact_pii(text: str) -> str:
    for pii_type, pattern in PII_PATTERNS.items():
        text = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", text, flags=re.IGNORECASE)
    return text
