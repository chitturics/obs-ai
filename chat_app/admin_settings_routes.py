"""Admin sub-router: Settings, feature flags, LLM, and prompts endpoints.

Handles these endpoint groups:
- GET  /api/admin/settings                  — All settings grouped by section
- PATCH /api/admin/settings/{section}       — Update a settings section
- GET  /api/admin/settings/history          — Config change audit trail
- GET  /api/admin/features                  — Feature flags
- POST /api/admin/features/reload           — Reload feature flags
- PUT  /api/admin/features/{feature}        — Toggle a feature
- GET  /api/admin/llm                       — LLM configuration and models
- PATCH /api/admin/llm                      — Update LLM configuration
- GET  /api/admin/prompts                   — List all prompt templates
- PUT  /api/admin/prompts/{name}            — Update a prompt template

Mount with:
    from chat_app.admin_settings_routes import settings_router
    router.include_router(settings_router)
"""

import logging

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _append_audit,
    _config_audit_trail,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

settings_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-settings"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map of section name -> Pydantic sub-model class used for validation.
_SECTION_MODEL_MAP: Dict[str, type] = {}


def _build_section_model_map() -> Dict[str, type]:
    """Build a mapping of section names to their Pydantic model classes."""
    if _SECTION_MODEL_MAP:
        return _SECTION_MODEL_MAP

    from chat_app.settings import (
        AppSettings,
        UISettings,
        DatabaseSettings,
        OllamaSettings,
        ChromaSettings,
        CacheSettings,
        ChunkingSettings,
        PathSettings,
        SplunkSettings,
        SearchOptimizerSettings,
        AuthSettings,
        RateLimitSettings,
        SPLValidationSettings,
        RetrievalSettings,
        LearningSettings,
    )
    _SECTION_MODEL_MAP.update({
        "app": AppSettings,
        "ui": UISettings,
        "database": DatabaseSettings,
        "ollama": OllamaSettings,
        "chroma": ChromaSettings,
        "cache": CacheSettings,
        "chunking": ChunkingSettings,
        "paths": PathSettings,
        "splunk": SplunkSettings,
        "search_optimizer": SearchOptimizerSettings,
        "auth": AuthSettings,
        "rate_limit": RateLimitSettings,
        "spl_validation": SPLValidationSettings,
        "retrieval": RetrievalSettings,
        "learning": LearningSettings,
    })
    for name, cls_name in [
        ("knowledge_graph", "KnowledgeGraphSettings"),
        ("orchestration", "OrchestrationSettings"),
        ("docling", "DoclingSettings"),
        ("splunkbase_catalog", "SplunkbaseCatalogSettings"),
        ("mcp_gateway", "MCPGatewaySettings"),
    ]:
        try:
            from chat_app import settings as _s
            _SECTION_MODEL_MAP[name] = getattr(_s, cls_name)
        except (ImportError, AttributeError):
            pass
    return _SECTION_MODEL_MAP


_SECRET_FIELD_NAMES = frozenset({
    "password", "token", "secret", "api_key", "admin_password",
    "auth_secret", "salt", "validator_pass", "splunk_token",
})

_NON_SECRET_ALLOWLIST = frozenset({
    "smart_chunk_tokens", "smart_chunk_overlap_tokens",
    "chunk_tokens", "overlap_tokens",
})


def _mask_secrets(data: dict) -> dict:
    """Recursively mask sensitive fields in settings dictionaries."""
    masked = {}
    for k, v in data.items():
        if isinstance(v, dict):
            masked[k] = _mask_secrets(v)
        elif k.lower() in _NON_SECRET_ALLOWLIST:
            masked[k] = v
        elif any(s in k.lower() for s in _SECRET_FIELD_NAMES):
            masked[k] = "****" if v else ""
        else:
            masked[k] = v
    return masked


# Feature flags with runtime overrides.
_feature_flags: Optional[Dict[str, bool]] = None


def _get_feature_flags() -> Dict[str, bool]:
    """Return the current feature flags, initialising from config.yaml on first call."""
    global _feature_flags
    if _feature_flags is None:
        cfg = {}
        try:
            from chat_app.settings import _load_yaml_config
            cfg = _load_yaml_config()
            raw = cfg.get("features", {})
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug(f"[ADMIN] Feature flags load failed: {exc}")
            raw = {}
        settings = get_settings()
        _feature_flags = {
            "hybrid_search": raw.get("hybrid_search", False),
            "query_caching": raw.get("query_caching", True),
            "response_streaming": raw.get("response_streaming", False),
            "auto_feedback_collection": raw.get("auto_feedback_collection", True),
            "reranking": raw.get("reranking", False),
            "query_expansion": raw.get("query_expansion", True),
            "compound_query_detection": raw.get("compound_query_detection", True),
            "prometheus_metrics": raw.get("prometheus_metrics", False),
            "health_checks": raw.get("health_checks", True),
            "circuit_breakers": raw.get("circuit_breakers", True),
            "retry_with_backoff": raw.get("retry_with_backoff", True),
            "fallback_responses": raw.get("fallback_responses", True),
            "learning": settings.learning.enabled,
            "streaming": raw.get("response_streaming", False),
            "knowledge_graph": cfg.get("knowledge_graph", {}).get("enabled", True),
            "orchestration": cfg.get("orchestration", {}).get("default_strategy", "adaptive") != "disabled",
            "docling_processing": cfg.get("docling", {}).get("enabled", False),
            "splunkbase_catalog": cfg.get("splunkbase_catalog", {}).get("enabled", False),
        }
    return _feature_flags


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SettingsUpdateRequest(BaseModel):
    """Partial update payload for a settings section."""
    values: Dict[str, Any] = Field(
        ...,
        description="Key-value pairs to update within the section.",
    )


class FeatureToggleRequest(BaseModel):
    """Request body to toggle a feature flag."""
    enabled: bool


class LLMUpdateRequest(BaseModel):
    """Update LLM configuration."""
    model: Optional[str] = None
    embed_model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    num_ctx: Optional[int] = Field(default=None, ge=512, le=131072)
    num_predict: Optional[int] = Field(default=None, ge=64, le=4096)
    timeout: Optional[int] = Field(default=None, ge=10, le=600)
    base_url: Optional[str] = None


class PromptUpdateRequest(BaseModel):
    """Update a prompt template."""
    content: str = Field(..., min_length=10, description="New prompt content")


# ---------------------------------------------------------------------------
# Settings Endpoints
# ---------------------------------------------------------------------------


@settings_router.get("/settings", summary="Get all current settings grouped by section")
async def get_all_settings():
    """Return all configuration settings, grouped by section name. Secrets are masked."""
    settings = get_settings()
    sections = {}
    for field_name in type(settings).model_fields:
        section = getattr(settings, field_name)
        sections[field_name] = _mask_secrets(section.model_dump())
    return {
        "sections": sections,
        "active_profile": settings.app.active_profile,
        "version": settings.app.version,
        "timestamp": _now_iso(),
    }


@settings_router.patch(
    "/settings/{section}",
    summary="Update a settings section",
)
async def update_settings_section(section: str, body: SettingsUpdateRequest):
    """Partially update a named settings section."""
    model_map = _build_section_model_map()
    if section not in model_map:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown settings section: '{section}'. "
                   f"Valid sections: {sorted(model_map.keys())}",
        )

    settings = get_settings()
    current_section = getattr(settings, section)
    previous = current_section.model_dump()

    merged = {**previous, **body.values}

    model_cls = model_map[section]
    try:
        validated = model_cls(**merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Validation failed for the settings update.",
                "errors": exc.errors(),
            },
        )

    setattr(settings, section, validated)

    audit = _append_audit(
        section=section,
        action="update",
        changes=body.values,
        previous={k: previous[k] for k in body.values if k in previous},
    )

    logger.info("Settings section '%s' updated: %s", section, list(body.values.keys()))
    return {
        "section": section,
        "updated": validated.model_dump(),
        "audit_id": audit["id"],
        "timestamp": audit["timestamp"],
    }


@settings_router.get("/settings/history", summary="Get config change audit trail")
async def get_settings_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    section: Optional[str] = Query(default=None),
):
    """Return the in-memory audit trail of configuration changes."""
    entries = _config_audit_trail
    if section:
        entries = [e for e in entries if e["section"] == section]
    all_entries = list(reversed(entries))
    total = len(all_entries)
    page = all_entries[offset:offset + limit]
    return {
        "total": total,
        "returned": len(page),
        "entries": page,
    }


# ---------------------------------------------------------------------------
# Feature Flags
# ---------------------------------------------------------------------------

@settings_router.get("/features", summary="List all feature flags with current state")
async def list_features():
    """Return all feature flags and their boolean state."""
    flags = _get_feature_flags()
    return {
        "features": {
            name: {"enabled": enabled, "name": name}
            for name, enabled in sorted(flags.items())
        },
        "total": len(flags),
        "enabled_count": sum(1 for v in flags.values() if v),
        "timestamp": _now_iso(),
    }


@settings_router.post("/features/reload", summary="Reload feature flags from config.yaml")
async def reload_feature_flags():
    """Force-reload all feature flags from config.yaml, discarding runtime overrides."""
    global _feature_flags
    previous = dict(_get_feature_flags())
    _feature_flags = None
    reloaded = _get_feature_flags()
    changes = {k: reloaded[k] for k in reloaded if reloaded.get(k) != previous.get(k)}
    _append_audit(
        section="features",
        action="reload",
        changes=changes,
        previous={k: previous.get(k) for k in changes},
    )
    logger.info("Feature flags reloaded from config.yaml, %d changed", len(changes))
    return {
        "status": "ok",
        "flags": reloaded,
        "changes": changes,
        "timestamp": _now_iso(),
    }


@settings_router.put("/features/{feature}", summary="Toggle a feature flag")
async def toggle_feature(feature: str, body: FeatureToggleRequest):
    """Enable or disable a single feature flag."""
    flags = _get_feature_flags()
    if feature not in flags:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown feature flag: '{feature}'. "
                   f"Valid flags: {sorted(flags.keys())}",
        )

    previous = flags[feature]
    flags[feature] = body.enabled

    _append_audit(
        section="features",
        action="toggle",
        changes={feature: body.enabled},
        previous={feature: previous},
    )

    logger.info("Feature flag '%s' set to %s (was %s)", feature, body.enabled, previous)
    return {
        "feature": feature,
        "enabled": body.enabled,
        "previous": previous,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------

@settings_router.get("/llm", summary="Get LLM configuration and available models")
async def get_llm_config():
    """Return current LLM configuration and list available models from Ollama."""
    settings = get_settings()
    ollama_cfg = settings.ollama

    available_models = []
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(f"{ollama_cfg.base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
            for m in data.get("models", []):
                available_models.append({
                    "name": m.get("name"),
                    "size": m.get("size"),
                    "modified_at": m.get("modified_at"),
                    "details": m.get("details", {}),
                })
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        available_models = [{"error": f"Cannot reach Ollama: {exc}"}]

    return {
        "current": {
            "model": ollama_cfg.model,
            "embed_model": ollama_cfg.embed_model,
            "temperature": ollama_cfg.temperature,
            "num_ctx": ollama_cfg.num_ctx,
            "num_predict": ollama_cfg.num_predict,
            "timeout": ollama_cfg.timeout,
            "base_url": ollama_cfg.base_url,
            "active_profile": getattr(settings, 'active_profile', None) or settings.app.active_profile if hasattr(settings.app, 'active_profile') else None,
        },
        "field_descriptions": {
            "model": "LLM model for chat responses",
            "embed_model": "Embedding model for vector search (mxbai-embed-large recommended)",
            "temperature": "Response randomness (0.0=deterministic, 1.0=creative). Low values recommended for accuracy",
            "num_ctx": "Context window in tokens. Smaller = faster inference. Must fit: system prompt + retrieved chunks + response",
            "num_predict": "Max response tokens. Caps generation time. Lower = faster responses",
            "timeout": "Max seconds to wait for LLM response before returning timeout message",
            "base_url": "Ollama API base URL",
        },
        "available_models": available_models,
        "profiles": {
            "LLM_LITE": {
                "model": "qwen2.5:3b", "num_ctx": 2048, "num_predict": 512, "timeout": 60,
                "description": "CPU-only, 8GB RAM min. Fast responses, basic quality.",
                "hardware": "Any CPU, 8GB+ RAM",
            },
            "LLM_MED": {
                "model": "qwen2.5:7b", "num_ctx": 4096, "num_predict": 1024, "timeout": 90,
                "description": "CPU/GPU, 16GB RAM. Good balance of speed and quality.",
                "hardware": "Modern CPU or entry GPU, 16GB+ RAM",
            },
            "LLM_MAX": {
                "model": "qwen2.5:14b", "num_ctx": 8192, "num_predict": 2048, "timeout": 120,
                "description": "GPU recommended, 32GB RAM. High quality, slower.",
                "hardware": "GPU with 12GB+ VRAM, or 32GB+ RAM for CPU",
            },
            "LLM_ULTRA": {
                "model": "qwen2.5:32b", "num_ctx": 16384, "num_predict": 4096, "timeout": 180,
                "description": "Dedicated GPU required. Maximum quality and context.",
                "hardware": "GPU with 24GB+ VRAM (A10G, RTX 4090, A100)",
            },
            "LLM_ENTERPRISE": {
                "model": "qwen2.5:72b", "num_ctx": 32768, "num_predict": 4096, "timeout": 300,
                "description": "Enterprise AI hardware. State-of-art quality with massive context.",
                "hardware": "Multi-GPU or AI accelerator (A100 80GB, H100, MI300X). $50K-$100K+ hardware",
            },
            "LLM_DEEPSEEK": {
                "model": "deepseek-r1:14b", "num_ctx": 8192, "num_predict": 2048, "timeout": 120,
                "description": "DeepSeek R1 reasoning model. Strong at code and analysis.",
                "hardware": "GPU with 12GB+ VRAM, or 32GB+ RAM for CPU",
            },
            "LLM_LLAMA": {
                "model": "llama3.3:70b", "num_ctx": 16384, "num_predict": 4096, "timeout": 240,
                "description": "Meta Llama 3.3 70B. Excellent general performance.",
                "hardware": "Multi-GPU (48GB+ total VRAM) or AI hardware",
            },
            "LLM_CODELLAMA": {
                "model": "codellama:34b-instruct", "num_ctx": 16384, "num_predict": 2048, "timeout": 180,
                "description": "Code-specialized model. Best for: SPL generation, config analysis, scripting",
                "hardware": "GPU with 24GB+ VRAM",
            },
        },
        "timestamp": _now_iso(),
    }


@settings_router.patch("/llm", summary="Update LLM configuration")
async def update_llm_config(body: LLMUpdateRequest):
    """Update LLM settings (model, temperature, context window, etc.)."""
    settings = get_settings()
    previous = settings.ollama.model_dump()
    updates = body.model_dump(exclude_none=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    for key, value in updates.items():
        if hasattr(settings.ollama, key):
            setattr(settings.ollama, key, value)

    audit = _append_audit(
        section="llm",
        action="update",
        changes=updates,
        previous={k: previous[k] for k in updates if k in previous},
    )

    return {
        "updated": settings.ollama.model_dump(),
        "changes": updates,
        "audit_id": audit["id"],
        "note": "Restart required for model changes to take effect.",
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Prompts Management
# ---------------------------------------------------------------------------

_PROMPT_CATALOG: Dict[str, Dict[str, str]] = {
    "system": {"category": "system", "description": "Primary system prompt defining the assistant's identity, capabilities, and behavioral rules.", "when_used": "Every LLM call.", "impact": "Changing this affects ALL responses.", "active": "always", "editable": "true"},
    "SYSTEM_PROMPT": {"category": "system", "description": "Primary system prompt (inline fallback).", "when_used": "Used when system.md template file is not found.", "impact": "Same as system.", "active": "always", "editable": "false"},
    "query_generation": {"category": "query", "description": "Guide for building Splunk SPL queries.", "when_used": "When intent is 'spl_query' or 'raw_spl'.", "impact": "Controls query construction rules.", "active": "always", "editable": "true"},
    "QUERY_GENERATION_PROMPT": {"category": "query", "description": "Query generation prompt (inline fallback).", "when_used": "Used when query_generation.md not found.", "impact": "Same as query_generation.", "active": "always", "editable": "false"},
    "query_analysis": {"category": "analysis", "description": "Framework for interpreting Splunk query results.", "when_used": "When analyzing results.", "impact": "Controls factual accuracy of result explanations.", "active": "always", "editable": "true"},
    "QUERY_ANALYSIS_PROMPT": {"category": "analysis", "description": "Query analysis prompt (inline fallback).", "when_used": "Used when query_analysis.md not found.", "impact": "Same as query_analysis.", "active": "always", "editable": "false"},
    "config_guidance": {"category": "config", "description": "Guidance for Splunk .conf file configuration questions.", "when_used": "When intent is 'config_guidance'.", "impact": "Controls conf file advice format.", "active": "always", "editable": "true"},
    "CONFIG_GUIDANCE_PROMPT": {"category": "config", "description": "Config guidance prompt (inline fallback).", "when_used": "Used when config_guidance.md not found.", "impact": "Same as config_guidance.", "active": "always", "editable": "false"},
    "conceptual": {"category": "conceptual", "description": "Framework for explaining Splunk concepts.", "when_used": "When intent is 'conceptual'.", "impact": "Controls explanation depth.", "active": "always", "editable": "true"},
    "CONCEPTUAL_PROMPT": {"category": "conceptual", "description": "Conceptual prompt (inline fallback).", "when_used": "Used when conceptual.md not found.", "impact": "Same as conceptual.", "active": "always", "editable": "false"},
    "SEARCH_OPTIMIZATION_PROMPT": {"category": "optimization", "description": "Systematic framework for analyzing and optimizing SPL queries.", "when_used": "When intent is 'search_optimization'.", "impact": "Controls optimization analysis.", "active": "always", "editable": "false"},
    "query_optimizer": {"category": "optimization", "description": "Specialized tstats converter.", "when_used": "When intent is 'optimize_query'.", "impact": "Controls tstats conversion.", "active": "always", "editable": "true"},
    "QUERY_OPTIMIZER_PROMPT": {"category": "optimization", "description": "Query optimizer prompt (inline fallback).", "when_used": "Used when query_optimizer.md not found.", "impact": "Same as query_optimizer.", "active": "always", "editable": "false"},
    "ROUTING_GUIDE": {"category": "system", "description": "Decision tree for selecting the appropriate prompt.", "when_used": "Used internally to route queries.", "impact": "Affects prompt selection.", "active": "always", "editable": "false"},
    "AGENT_RESPONSE_TEMPLATES": {"category": "agent", "description": "Response structure templates per department.", "when_used": "When an agent persona is dispatched.", "impact": "Controls response organization.", "active": "always", "editable": "false"},
    "gemini_query_generation": {"category": "query", "description": "Alternative query generation prompt tuned for Gemini API.", "when_used": "When using Gemini as the LLM backend.", "impact": "Only affects Gemini-based generation.", "active": "conditional", "editable": "true"},
    "profile:org_expert": {"category": "profile", "description": "Organization's Splunk configuration specialist.", "when_used": "When active profile is 'org_expert'.", "impact": "Replaces base system prompt.", "active": "conditional", "editable": "false"},
    "profile:troubleshooter": {"category": "profile", "description": "Splunk troubleshooting specialist.", "when_used": "When active profile is 'troubleshooter'.", "impact": "Replaces base system prompt.", "active": "conditional", "editable": "false"},
    "profile:config_helper": {"category": "profile", "description": "Splunk configuration assistant.", "when_used": "When active profile is 'config_helper'.", "impact": "Replaces base system prompt.", "active": "conditional", "editable": "false"},
    "profile:spl_expert": {"category": "profile", "description": "SPL command mastery.", "when_used": "When active profile is 'spl_expert'.", "impact": "Replaces base system prompt.", "active": "conditional", "editable": "false"},
    "profile:cribl_expert": {"category": "profile", "description": "Cribl Stream/Edge expert.", "when_used": "When active profile is 'cribl_expert'.", "impact": "Replaces base system prompt.", "active": "conditional", "editable": "false"},
    "profile:observability_expert": {"category": "profile", "description": "Senior observability & platform engineer.", "when_used": "When active profile is 'observability_expert'.", "impact": "Replaces base system prompt.", "active": "conditional", "editable": "false"},
    "dynamic_overlay": {"category": "dynamic", "description": "Learned behavioral rules from self-learning pipeline.", "when_used": "Prepended to EVERY system prompt.", "impact": "Adds learned rules.", "active": "conditional", "editable": "false"},
}

_COMPOSITION_ORDER = [
    {"step": 1, "layer": "Dynamic Overlay", "description": "Learned behavioral rules from self-learning pipeline", "position": "prepended first"},
    {"step": 2, "layer": "Agent Prompt Fragment", "description": "Agent persona (department directive + expertise style + skills)", "position": "injected if agent dispatched"},
    {"step": 3, "layer": "Profile System Prompt", "description": "Role-specific prompt (org_expert, spl_expert, etc.)", "position": "replaces base if profile active"},
    {"step": 4, "layer": "Base System Prompt", "description": "SYSTEM_PROMPT — core identity and rules", "position": "fallback if no profile"},
    {"step": 5, "layer": "Intent-Specific Prompt", "description": "query_generation, config_guidance, conceptual, etc.", "position": "appended to context"},
    {"step": 6, "layer": "RAG Context", "description": "Retrieved documents from vector store collections", "position": "injected into user context"},
    {"step": 7, "layer": "Knowledge Graph Context", "description": "Structural facts from entity/relationship graph", "position": "appended after RAG context"},
    {"step": 8, "layer": "Final LLM Input", "description": "All layers combined into the prompt sent to the LLM", "position": "assembled by message_handler.py"},
]


@settings_router.get("/prompts", summary="List all prompt templates with metadata")
async def list_prompts(
    include_content: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all available prompt templates with their content, metadata, and composition hierarchy."""
    prompts_data = {}
    template_dir = Path(__file__).resolve().parent / "prompt_templates"

    # Load from template files
    if template_dir.is_dir():
        for md_file in sorted(template_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            key = md_file.stem
            catalog = _PROMPT_CATALOG.get(key, {})
            entry = {
                "source": "file",
                "path": str(md_file),
                "length": len(content),
                "preview": content[:200] + "..." if len(content) > 200 else content,
                "category": catalog.get("category", "unknown"),
                "description": catalog.get("description", ""),
                "when_used": catalog.get("when_used", ""),
                "impact": catalog.get("impact", ""),
                "active": catalog.get("active", "always"),
                "editable": True,
            }
            if include_content:
                entry["content"] = content
            prompts_data[key] = entry

    # Load inline prompts from prompts.py
    try:
        from chat_app import prompts as prompts_mod
        for name in dir(prompts_mod):
            if name.isupper() and isinstance(getattr(prompts_mod, name), str):
                val = getattr(prompts_mod, name)
                if name not in prompts_data and len(val) > 20:
                    catalog = _PROMPT_CATALOG.get(name, {})
                    entry = {
                        "source": "inline",
                        "path": "chat_app/prompts.py",
                        "length": len(val),
                        "preview": val[:200] + "..." if len(val) > 200 else val,
                        "category": catalog.get("category", "unknown"),
                        "description": catalog.get("description", ""),
                        "when_used": catalog.get("when_used", ""),
                        "impact": catalog.get("impact", ""),
                        "active": catalog.get("active", "always"),
                        "editable": False,
                    }
                    if include_content:
                        entry["content"] = val
                    prompts_data[name] = entry
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load inline prompts: {exc}")

    # Add profile prompts
    try:
        from chat_app.profiles import PROFILE_PROMPTS
        for profile_name, prompt_text in PROFILE_PROMPTS.items():
            key = f"profile:{profile_name}"
            catalog = _PROMPT_CATALOG.get(key, {})
            entry = {
                "source": "profiles.py",
                "path": "chat_app/profiles.py",
                "length": len(prompt_text),
                "preview": prompt_text[:200] + "..." if len(prompt_text) > 200 else prompt_text,
                "category": catalog.get("category", "profile"),
                "description": catalog.get("description", f"Profile prompt for {profile_name}"),
                "when_used": catalog.get("when_used", f"When active profile is '{profile_name}'"),
                "impact": catalog.get("impact", "Replaces base system prompt"),
                "active": "conditional",
                "editable": False,
            }
            if include_content:
                entry["content"] = prompt_text
            prompts_data[key] = entry
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load profile prompts: {exc}")

    # Add dynamic overlay status
    try:
        from chat_app.self_learning import get_dynamic_prompt_overlay
        overlay = get_dynamic_prompt_overlay()
        catalog = _PROMPT_CATALOG.get("dynamic_overlay", {})
        overlay_text = overlay or "(empty -- no learned rules yet)"
        entry = {
            "source": "self_learning.py",
            "path": "chat_app/self_learning.py",
            "length": len(overlay) if overlay else 0,
            "preview": (overlay_text[:200] + "...") if len(overlay_text) > 200 else overlay_text,
            "category": "dynamic",
            "description": catalog.get("description", "Dynamically learned behavioral rules"),
            "when_used": catalog.get("when_used", "Prepended to every system prompt when available"),
            "impact": catalog.get("impact", "Adds learned behavioral rules"),
            "active": "active" if overlay else "inactive",
            "editable": False,
        }
        if include_content:
            entry["content"] = overlay_text
        prompts_data["dynamic_overlay"] = entry
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[ADMIN] Failed to load dynamic overlay: {exc}")

    active_profile = "general"
    try:
        settings = get_settings()
        active_profile = settings.app.active_profile
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("[%s] %%s", "admin_settings_routes.py", _exc)

    all_keys = list(prompts_data.keys())
    total = len(all_keys)
    page_keys = all_keys[offset:offset + limit]
    paged_prompts = {k: prompts_data[k] for k in page_keys}

    return {
        "prompts": paged_prompts,
        "total": total,
        "template_dir": str(template_dir),
        "composition_order": _COMPOSITION_ORDER,
        "active_profile": active_profile,
        "categories": ["system", "query", "analysis", "config", "conceptual", "optimization", "agent", "profile", "dynamic"],
        "timestamp": _now_iso(),
    }


@settings_router.put("/prompts/{name}", summary="Update a prompt template")
async def update_prompt(name: str, body: PromptUpdateRequest):
    """Update a prompt template file. Creates a new .md file if needed."""
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_\-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid prompt name. Only alphanumeric, underscore, and hyphen allowed.")
    template_dir = Path(__file__).resolve().parent / "prompt_templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    file_path = template_dir / f"{name}.md"
    if not file_path.resolve().parent == template_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid prompt name.")
    previous = None
    if file_path.exists():
        previous = file_path.read_text(encoding="utf-8", errors="ignore")

    file_path.write_text(body.content, encoding="utf-8")

    _append_audit(
        section="prompts",
        action="update",
        changes={"name": name, "length": len(body.content)},
        previous={"length": len(previous)} if previous else None,
    )

    try:
        from chat_app.cache import invalidate_prompt_cache
        await invalidate_prompt_cache()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to invalidate prompt cache: %s", exc)

    return {
        "name": name,
        "path": str(file_path),
        "length": len(body.content),
        "is_new": previous is None,
        "note": "Prompt will take effect on next request (caches invalidated).",
        "timestamp": _now_iso(),
    }
