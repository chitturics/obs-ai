"""
FastAPI service that exposes SPL/NLP query review, optimization, and learning.

This service acts as an intelligent SPL agent that:
- Auto-analyzes all saved searches on startup
- Learns from user feedback to improve recommendations
- Provides expert-level query understanding and optimization
- Generates SPL from natural language (NLP)
- Performs robust analysis with anti-pattern detection and auto-fix

Endpoints:
    POST /analyze                    - General analysis (review, optimize, improve, learn)
    POST /explain                    - Explain SPL query step-by-step
    POST /score                      - Score query quality and efficiency
    POST /annotate                   - Add inline comments to query
    POST /auto                       - Auto-detect intent and analyze
    POST /savedsearches/analyze-all  - Pre-analyze all saved searches
    POST /savedsearches/get          - Get analysis for a saved search
    GET  /savedsearches/{name}       - Get analysis by name (URL path)
    POST /savedsearches/list         - List all analyzed searches
    POST /savedsearches/feedback     - Submit improved query with ranking
    GET  /savedsearches/best/{name}  - Get best query version (user-improved or optimized)
    POST /nlp/generate               - Generate SPL from natural language
    GET  /nlp/stats                  - Get NLP generator statistics
    POST /nlp/examples/reload        - Reload NLP examples from configs
    POST /analyze/robust             - Comprehensive robust analysis with auto-fix
    POST /analyze/cost               - Get query cost estimation (0-100)
    POST /analyze/fix                - Apply auto-fixes to query
    POST /analyze/pipeline           - Full pipeline: validate, analyze, fix, optimize
    POST /analyze/deep               - Next-level deep analysis (cardinality, memory, regex, distribution)
    GET  /docs/command/{name}        - Look up official Splunk command documentation
    GET  /docs/spec/{config}         - Look up Splunk configuration specification
    GET  /docs/limits/{command}      - Get limits.conf settings for a command
    GET  /health                     - Health check with readiness status
    GET  /ready                      - Readiness probe for orchestration
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator


from containers.search_opt.core import (
    handle_query,
    explain_query,
    score_query,
    annotate_query,
    auto_analyze,
    deep_analyze_query,
    analyze_all_saved_searches,
    get_analyzed_search,
    submit_search_feedback,
    list_analyzed_searches,
    preload_caches,
    get_best_query_version,
    get_service_stats,
    get_splunk_config_manager,
    validate_spl_with_splunk,
    get_splunk_validator_status,
    generate_spl_from_nlp,
    get_nlp_stats,
    # Robust analyzer functions
    robust_analyze_query,
    get_query_cost,
    apply_auto_fixes,
    validate_and_optimize_query,
)
from containers.search_opt.learning import learn_from_feedback, apply_learned_patterns
from containers.search_opt.scheduler import start_scheduler, stop_scheduler, get_scheduler_status

logger = logging.getLogger(__name__)

# Docs status helper
def _get_docs_status() -> dict:
    """Return docs enrichment status for health endpoint."""
    try:
        from shared.docs_loader import get_docs
        docs = get_docs()
        return {
            "enabled": docs.command_count > 0 or docs.spec_count > 0,
            "commands": docs.command_count,
            "specs": docs.spec_count,
        }
    except Exception:
        return {"enabled": False, "commands": 0, "specs": 0}

# Service state
_service_ready = False
_startup_task = None
_analysis_in_progress = False


async def _startup_analyze():
    """Background task to analyze saved searches on startup, then learn patterns."""
    global _service_ready, _analysis_in_progress
    try:
        _analysis_in_progress = True
        logger.info("Starting auto-analysis of saved searches...")

        # Run in thread pool to not block
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: analyze_all_saved_searches(force_reanalyze=False))

        logger.info(f"Auto-analysis complete: {result.get('analyzed', 0)} searches analyzed, {result.get('skipped', 0)} cached")

        # Auto-learn patterns from all feedback after analysis
        try:
            learn_result = await loop.run_in_executor(None, learn_from_feedback)
            logger.info(
                f"Auto-learning complete: {learn_result.get('new_patterns_learned', 0)} new patterns, "
                f"{learn_result.get('total_patterns', 0)} total"
            )
        except Exception as learn_err:
            logger.warning(f"Auto-learning failed (non-fatal): {learn_err}")

        _analysis_in_progress = False
        _service_ready = True
    except Exception as e:
        logger.error(f"Auto-analysis failed: {e}")
        _analysis_in_progress = False
        _service_ready = True  # Still mark ready, just without pre-analysis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown."""
    global _startup_task

    # Startup: preload caches and start background analysis
    logger.info("Search Optimization Service starting...")
    preload_caches()

    # Start background analysis if AUTO_ANALYZE is enabled (default: true)
    if os.getenv("AUTO_ANALYZE", "true").lower() in ("true", "1", "yes"):
        _startup_task = asyncio.create_task(_startup_analyze())

    # Start the persistent scheduler (hourly/daily/weekly jobs)
    await start_scheduler()

    yield

    # Shutdown
    await stop_scheduler()
    if _startup_task and not _startup_task.done():
        _startup_task.cancel()
    logger.info("Search Optimization Service stopped.")

app = FastAPI(
    title="Search Optimization Service",
    description="Intelligent SPL Agent for Query Analysis, Optimization, NLP-to-SPL Generation, and Robust Analysis",
    version="2.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Instrument for Prometheus
Instrumentator().instrument(app).expose(app)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    sql_query: str = Field(..., description="Input query (SPL or natural language)")
    type: str = Field(..., pattern="^(nlp|spl|sql)$", description="Interpretation of input")
    action: str = Field(
        ...,
        pattern="^(review|optimize|improve|learn|explain|score|annotate|auto)$",
        description="Operation to perform",
    )
    store: Optional[str] = Field(None, description="Path to persist best practices when action=learn")


class ExplainRequest(BaseModel):
    query: str = Field(..., description="SPL query to explain")


class ScoreRequest(BaseModel):
    query: str = Field(..., description="SPL query to score")


class AnnotateRequest(BaseModel):
    query: str = Field(..., description="SPL query to annotate")


class AutoAnalyzeRequest(BaseModel):
    input: str = Field(..., description="SPL query or natural language")
    force_intent: Optional[str] = Field(
        None,
        description="Force specific intent: generate, optimize, explain, validate, annotate",
    )


class SavedSearchRequest(BaseModel):
    name: str = Field(..., description="Name of the saved search to retrieve")


class FeedbackRequest(BaseModel):
    name: str = Field(..., description="Name of the saved search")
    improved_query: str = Field(..., description="User's improved version of the query")
    notes: str = Field("", description="Explanation of the improvement")
    user: str = Field("anonymous", description="Username submitting feedback")
    rank: int = Field(0, description="Quality ranking (higher = better)")


class ListSearchesRequest(BaseModel):
    limit: int = Field(100, description="Maximum number to return")
    sort_by: str = Field("name", description="Sort field: name, score, or analyzed_at")


@app.get("/health", tags=["Health"])
async def health():
    """
    Health check endpoint with detailed status.

    Returns service status including:
    - Whether the service is ready (saved searches analyzed)
    - Analysis statistics
    - Available features
    """
    stats = get_service_stats()
    return {
        "status": "ok",
        "version": "2.2.0",
        "ready": _service_ready,
        "analysis_in_progress": _analysis_in_progress,
        "stats": stats,
        "features": [
            "explain",
            "score",
            "annotate",
            "auto",
            "feedback-learning",
            "nlp-to-spl",
            "robust-analysis",
            "cost-estimation",
            "auto-fix",
            "docs-enrichment",
        ],
        "docs": _get_docs_status(),
    }


@app.get("/ready", tags=["Health"])
async def ready():
    """
    Readiness probe for container orchestration.

    Returns 200 when service is fully ready (saved searches analyzed).
    Returns 503 when still initializing.
    """
    if not _service_ready:
        raise HTTPException(
            status_code=503,
            detail="Service initializing - analyzing saved searches"
        )
    return {"ready": True}


@app.post("/analyze", tags=["Analysis"])
async def analyze(req: QueryRequest):
    """
    General analysis endpoint supporting multiple actions.

    Actions:
    - review: Validate query and check for issues
    - optimize: Convert to tstats/improve performance
    - improve: Same as optimize
    - learn: Save query patterns for learning
    - explain: Explain query step-by-step
    - score: Score query quality
    - annotate: Add inline comments
    - auto: Auto-detect intent and analyze
    """
    try:
        store_path = Path(req.store) if req.store else None
        result = handle_query(req.sql_query, req.type, req.action, store_path=store_path)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/explain", tags=["Explanation"])
async def explain(req: ExplainRequest):
    """
    Explain an SPL query step by step.

    Returns:
    - Summary of what the query does
    - Stage-by-stage breakdown
    - Fields used
    - Data flow description
    - Overall purpose
    - Complexity assessment
    """
    try:
        return explain_query(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/score", tags=["Scoring"])
async def score(req: ScoreRequest):
    """
    Score an SPL query for quality and efficiency.

    Returns scores (0-100) for:
    - Overall quality
    - Readability
    - Efficiency
    - Best practices compliance
    """
    try:
        return score_query(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/annotate", tags=["Annotation"])
async def annotate(req: AnnotateRequest):
    """
    Add inline comments to an SPL query.

    Adds descriptive comments to each pipeline stage
    to make the query easier to understand.
    """
    try:
        return annotate_query(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/auto", tags=["Auto Analysis"])
async def auto(req: AutoAnalyzeRequest):
    """
    Auto-detect intent and analyze input.

    Automatically determines:
    - If input is SPL or natural language
    - What the user wants (generate, optimize, explain, validate)

    Then performs the appropriate analysis.
    """
    try:
        return auto_analyze(req.input, force_intent=req.force_intent)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ----------------------------
# Saved Search Management
# ----------------------------

@app.post("/savedsearches/analyze-all", tags=["Saved Searches"])
async def analyze_all(force: bool = False):
    """
    Analyze all saved searches from savedsearches.conf files.

    Pre-analyzes every saved search found in the configured directories,
    storing validation, optimization, explanation, and scoring results.

    Args:
        force: If True, re-analyze even if previously analyzed
    """
    try:
        return analyze_all_saved_searches(force_reanalyze=force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/savedsearches/get", tags=["Saved Searches"])
async def get_search(req: SavedSearchRequest):
    """
    Retrieve analysis for a specific saved search.

    Returns both original and optimized queries along with:
    - Validation results
    - Optimization details
    - Explanation
    - Quality score
    - User feedback (sorted by rank)
    """
    try:
        return get_analyzed_search(req.name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/savedsearches/{name}", tags=["Saved Searches"])
async def get_search_by_name(name: str):
    """
    Retrieve analysis for a saved search by name (URL path version).
    """
    try:
        return get_analyzed_search(name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/savedsearches/list", tags=["Saved Searches"])
async def list_searches(req: ListSearchesRequest = None):
    """
    List all analyzed saved searches.

    Returns summary info for each search including:
    - Name and file location
    - Whether optimization is available
    - Quality score
    - Feedback count
    """
    try:
        if req:
            return list_analyzed_searches(limit=req.limit, sort_by=req.sort_by)
        return list_analyzed_searches()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/savedsearches/feedback", tags=["Saved Searches"])
async def add_feedback(req: FeedbackRequest):
    """
    Submit user feedback with an improved search query.

    Users can submit improved versions of saved searches with:
    - The improved query
    - Notes explaining the improvement
    - A rank (higher = better improvement)

    Improvements are stored and returned when the search is retrieved,
    sorted by rank.
    """
    try:
        return submit_search_feedback(
            name=req.name,
            improved_query=req.improved_query,
            notes=req.notes,
            user=req.user,
            rank=req.rank,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/savedsearches/best/{name}", tags=["Saved Searches"])
async def get_best_query(name: str):
    """
    Get the best version of a saved search query.

    Returns the best query based on this priority:
    1. Highest-ranked user feedback (if any)
    2. System-optimized query (if optimization was possible)
    3. Original query

    This is useful for agents that want the best available version
    without needing to parse the full analysis response.
    """
    try:
        return get_best_query_version(name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/learn", tags=["Learning"])
async def trigger_learning():
    """
    Trigger feedback learning to extract optimization patterns.

    Analyzes all high-ranked feedback and extracts reusable patterns
    (stats→tstats, TERM wrapping, index specification, etc.).
    Learned patterns are applied to future optimization suggestions.
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, learn_from_feedback)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class ApplyPatternsRequest(BaseModel):
    query: str = Field(..., description="SPL query to check against learned patterns")


@app.post("/learn/apply", tags=["Learning"])
async def apply_patterns(req: ApplyPatternsRequest):
    """
    Check if any learned patterns can be applied to a query.

    Returns a list of applicable optimization suggestions based on
    patterns extracted from user feedback.
    """
    try:
        suggestions = apply_learned_patterns(req.query)
        return {"query": req.query, "suggestions": suggestions, "count": len(suggestions)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/scheduler/status", tags=["Scheduler"])
async def scheduler_status():
    """
    Get scheduler status and recent job execution history.

    Shows which jobs are scheduled, their last run times, and results.
    """
    return get_scheduler_status()


@app.post("/scheduler/run/{job_name}", tags=["Scheduler"])
async def run_scheduled_job(job_name: str):
    """
    Manually trigger a scheduled job.

    Available jobs: hourly_learn, daily_analyze, weekly_assessment
    """
    from containers.search_opt.scheduler import (
        job_hourly_learn, job_daily_analyze, job_weekly_assessment
    )

    jobs = {
        "hourly_learn": job_hourly_learn,
        "daily_analyze": job_daily_analyze,
        "weekly_assessment": job_weekly_assessment,
    }

    if job_name not in jobs:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_name}' not found. Available: {list(jobs.keys())}"
        )

    try:
        result = await jobs[job_name]()
        return {"job": job_name, "status": "completed", "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/savedsearches/analyze-all/background", tags=["Saved Searches"])
async def analyze_all_background(background_tasks: BackgroundTasks, force: bool = False):
    """
    Start background analysis of all saved searches.

    Returns immediately with task status. Use /health to check progress.
    """
    global _analysis_in_progress

    if _analysis_in_progress:
        return {
            "status": "already_running",
            "message": "Analysis already in progress. Check /health for status."
        }

    def run_analysis():
        global _analysis_in_progress
        try:
            _analysis_in_progress = True
            analyze_all_saved_searches(force_reanalyze=force)
        finally:
            _analysis_in_progress = False

    background_tasks.add_task(run_analysis)

    return {
        "status": "started",
        "message": "Analysis started in background. Check /health for progress."
    }


# ----------------------------
# Splunk Configuration API
# ----------------------------

class SearchConfigRequest(BaseModel):
    query: str = Field("", description="Search query string")
    limit: int = Field(20, description="Maximum results to return")


@app.get("/configs/summary", tags=["Splunk Configs"])
async def get_config_summary():
    """
    Get summary of loaded Splunk configurations.

    Returns counts and top-ranked items for:
    - Custom commands (from commands.conf)
    - Macros (from macros.conf)
    - Saved searches (from savedsearches.conf)
    """
    try:
        mgr = get_splunk_config_manager()
        return {
            "counts": {
                "commands": len(mgr.get_commands()),
                "macros": len(mgr.get_macros()),
                "searches": len(mgr.get_searches()),
            },
            "top_macros": [
                {"name": m["name"], "rank": m.get("rank", 0), "has_index": m.get("has_index")}
                for m in mgr.get_top_macros(10)
            ],
            "top_searches": [
                {"name": s["name"], "rank": s.get("rank", 0), "is_scheduled": s.get("is_scheduled")}
                for s in mgr.get_top_searches(10)
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/configs/commands", tags=["Splunk Configs"])
async def get_commands(limit: int = 100):
    """
    Get all custom SPL commands from commands.conf files.

    Returns command metadata including:
    - Type (python, perl, etc.)
    - Whether it's streaming/generating
    - Description
    - Rank score
    """
    try:
        mgr = get_splunk_config_manager()
        commands = list(mgr.get_commands().values())
        commands.sort(key=lambda x: x.get("rank", 0), reverse=True)
        return {"commands": commands[:limit], "total": len(commands)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/configs/macros", tags=["Splunk Configs"])
async def get_macros(limit: int = 100):
    """
    Get all macros from macros.conf files.

    Returns macro metadata including:
    - Definition (the actual SPL)
    - Arguments
    - Whether it contains index/sourcetype
    - Rank score based on usage
    """
    try:
        mgr = get_splunk_config_manager()
        macros = list(mgr.get_macros().values())
        macros.sort(key=lambda x: x.get("rank", 0), reverse=True)
        return {"macros": macros[:limit], "total": len(macros)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/configs/macros/{name}", tags=["Splunk Configs"])
async def get_macro_by_name(name: str):
    """
    Get a specific macro by name.

    Returns full macro details including definition and expansion info.
    """
    try:
        mgr = get_splunk_config_manager()
        macro = mgr.get_macro(name)
        if not macro:
            raise HTTPException(status_code=404, detail=f"Macro '{name}' not found")
        return macro
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/configs/macros/search", tags=["Splunk Configs"])
async def search_macros(req: SearchConfigRequest):
    """
    Search macros by name or definition content.

    Returns macros matching the search query, ranked by relevance.
    """
    try:
        mgr = get_splunk_config_manager()
        results = mgr.search_macros(req.query, limit=req.limit)
        return {"results": results, "count": len(results)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/configs/searches/search", tags=["Splunk Configs"])
async def search_saved_searches(req: SearchConfigRequest):
    """
    Search saved searches by name or search content.

    Returns saved searches matching the query, ranked by relevance.
    """
    try:
        mgr = get_splunk_config_manager()
        results = mgr.search_saved_searches(req.query, limit=req.limit)
        return {"results": results, "count": len(results)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/configs/reload", tags=["Splunk Configs"])
async def reload_configs():
    """
    Force reload of all Splunk configurations from repository.

    Use this after updating config files in the repo.
    """
    try:
        mgr = get_splunk_config_manager()
        counts = mgr.load_all(force=True)
        return {
            "status": "reloaded",
            "counts": counts,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ----------------------------
# Splunk Validator API
# ----------------------------

class ValidateSPLRequest(BaseModel):
    query: str = Field(..., description="SPL query to validate")


@app.get("/validator/status", tags=["Splunk Validator"])
async def validator_status():
    """
    Check if Splunk validator container is available.

    Returns connection status and server info if available.
    """
    try:
        return get_splunk_validator_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/validator/validate", tags=["Splunk Validator"])
async def validate_spl(req: ValidateSPLRequest):
    """
    Validate SPL query syntax using Splunk's REST API.

    Requires Splunk validator container to be running.
    Provides authoritative syntax validation.
    """
    try:
        return validate_spl_with_splunk(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ----------------------------
# NLP to SPL API
# ----------------------------

class NLPtoSPLRequest(BaseModel):
    query: str = Field(..., description="Natural language query to convert to SPL")
    validate: bool = Field(True, description="Validate generated query with Splunk")
    optimize: bool = Field(True, description="Optimize the generated query")
    context: Optional[dict] = Field(None, description="Optional context (index, unit_id, etc.)")


@app.post("/nlp/generate", tags=["NLP to SPL"])
async def generate_spl_from_natural_language(req: NLPtoSPLRequest):
    """
    Generate SPL from natural language query.

    Uses few-shot learning with organization macros, saved searches,
    and feedback Q&A as examples.

    The generated query is:
    1. Validated using Splunk REST API (if enabled)
    2. Optimized for performance (if enabled)

    Example:
        Input: "show me failed logins in the last hour"
        Output: "index=wineventlog EventCode=4625 earliest=-1h latest=now | stats count by user, src_ip"
    """
    try:
        result = generate_spl_from_nlp(
            nl_query=req.query,
            validate=req.validate,
            optimize=req.optimize,
            context=req.context
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/nlp/stats", tags=["NLP to SPL"])
async def get_nlp_generator_stats():
    """
    Get NLP generator statistics.

    Returns counts of loaded examples by source and intent.
    """
    try:
        return get_nlp_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/nlp/examples/reload", tags=["NLP to SPL"])
async def reload_nlp_examples():
    """
    Reload NLP examples from Splunk configurations.

    Call this after updating macros, saved searches, or feedback.
    """
    try:
        mgr = get_splunk_config_manager()
        counts = mgr.load_all(force=True)
        stats = get_nlp_stats()
        return {
            "status": "reloaded",
            "config_counts": counts,
            "nlp_stats": stats,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ----------------------------
# Robust SPL Analyzer API
# ----------------------------

class RobustAnalyzeRequest(BaseModel):
    query: str = Field(..., description="SPL query to analyze")
    auto_fix: bool = Field(True, description="Apply automatic fixes to common issues")
    validate_with_splunk: bool = Field(True, description="Validate with Splunk REST API")
    context: Optional[dict] = Field(None, description="Optional context (index hints, etc.)")


class CostRequest(BaseModel):
    query: str = Field(..., description="SPL query to estimate cost for")


class AutoFixRequest(BaseModel):
    query: str = Field(..., description="SPL query to fix")


class FullPipelineRequest(BaseModel):
    query: str = Field(..., description="SPL query for full analysis pipeline")
    context: Optional[dict] = Field(None, description="Optional context")


@app.post("/analyze/robust", tags=["Robust Analyzer"])
async def analyze_robust(req: RobustAnalyzeRequest):
    """
    Comprehensive robust analysis of an SPL query.

    Features:
    - **Anti-pattern detection**: Identifies common performance killers
      (index=*, wildcards, unbounded time ranges, expensive joins)
    - **Cost estimation**: Scores query expense (0-100 scale)
    - **Optimization potential**: Estimates how much improvement is possible
    - **Auto-fix**: Automatically fixes common issues like:
      - Unbalanced parentheses
      - Missing time ranges
      - Commands in wrong order (table at end)
      - Redundant eval commands
    - **Splunk validation**: Uses REST API for authoritative syntax check

    Example response:
    ```json
    {
        "query": "index=main | stats count",
        "is_valid": true,
        "cost_score": 45,
        "optimization_potential": 30,
        "issues": [...],
        "anti_patterns": ["NO_TIME_RANGE"],
        "fixed_query": "index=main earliest=-24h | stats count",
        "fixes_applied": ["Added default time range"]
    }
    ```
    """
    try:
        return robust_analyze_query(
            query=req.query,
            auto_fix=req.auto_fix,
            validate_with_splunk=req.validate_with_splunk,
            context=req.context
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/analyze/cost", tags=["Robust Analyzer"])
async def analyze_cost(req: CostRequest):
    """
    Estimate the computational cost of an SPL query.

    Returns:
    - **cost_score**: 0-100 (0=trivial, 100=extremely expensive)
    - **optimization_potential**: How much improvement is possible (0-100)
    - **command_costs**: Per-command cost breakdown
    - **expensive_operations**: List of performance-impacting operations
    - **suggestions**: Specific optimization recommendations

    Cost scoring considers:
    - Command types (tstats=5, stats=20, join=80, transaction=90)
    - Wildcards in searches
    - Unbounded time ranges
    - Large lookups
    - Cross-index searches
    """
    try:
        return get_query_cost(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/analyze/fix", tags=["Robust Analyzer"])
async def auto_fix(req: AutoFixRequest):
    """
    Apply automatic fixes to an SPL query.

    Fixes applied:
    - Balance parentheses
    - Add default time range if missing
    - Move table/fields to end of query
    - Combine redundant eval commands
    - Remove duplicate stats operations

    Returns the fixed query and list of changes made.
    Remaining issues that couldn't be auto-fixed are also reported.
    """
    try:
        return apply_auto_fixes(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/analyze/pipeline", tags=["Robust Analyzer"])
async def full_pipeline(req: FullPipelineRequest):
    """
    Full analysis pipeline: validate, analyze, fix, and optimize.

    Combines all analysis stages:
    1. **Syntax validation** (Splunk REST API)
    2. **Anti-pattern detection** (performance killers)
    3. **Auto-fix** (common issues)
    4. **Cost estimation** (0-100 scale)
    5. **Optimization** (tstats conversion if possible)

    This is the recommended endpoint for comprehensive query improvement.

    Use this when you want the best possible version of a query with
    full explanation of what was analyzed and changed.
    """
    try:
        return validate_and_optimize_query(req.query, req.context)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Deep Analysis — Next-Level Query Intelligence
# ---------------------------------------------------------------------------

class DeepAnalysisRequest(BaseModel):
    query: str = Field(..., description="SPL query to deeply analyze")


@app.post("/analyze/deep", tags=["Deep Analysis"])
async def deep_analysis(req: DeepAnalysisRequest):
    """
    Next-level deep analysis of an SPL query.

    Goes beyond basic validation/optimization to provide:
    - **Cardinality analysis** — warns about high-cardinality BY/dedup fields
    - **Memory estimation** — per-command memory footprint with risk levels
    - **Regex complexity** — scores rex/regex patterns for backtracking risk
    - **Bucket/span optimization** — analyzes bin/timechart span sizing
    - **Lookup analysis** — placement, OUTPUT usage, table size warnings
    - **Subsearch depth** — nested subsearch detection with depth count
    - **Metric index detection** — suggests mstats for metric indexes
    - **Distribution analysis** — flags commands that break distributed search
    - **Resource risk matrix** — memory, CPU, disk I/O, network risk assessment
    - **Search profiling** — stage-by-stage cost breakdown with bottleneck ID
    - **Pipeline reorder** — suggests optimal command ordering
    - **Query fingerprint** — structural hash for dedup/caching

    This is the most comprehensive analysis available. Use for:
    - Production search optimization reviews
    - Scheduled search performance auditing
    - Search onboarding/approval workflows
    """
    try:
        return deep_analyze_query(req.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Documentation Lookup
# ---------------------------------------------------------------------------
@app.get("/docs/command/{name}", tags=["Documentation"])
async def get_command_doc(name: str):
    """
    Look up official Splunk documentation for an SPL command.

    Returns the command description, usage notes, limitations,
    examples, and a link to the official Splunk docs.
    """
    try:
        from shared.docs_loader import get_docs
        docs = get_docs()
        cmd = docs.get_command(name)
        if not cmd:
            raise HTTPException(status_code=404, detail=f"Command '{name}' not found in documentation")
        return {
            "name": cmd.name,
            "title": cmd.title,
            "description": cmd.summary,
            "source_url": cmd.source_url,
            "usage_notes": cmd.usage_notes,
            "limitations": cmd.limitations,
            "examples": cmd.examples[:5],
            "related_commands": cmd.related_commands,
            "sections": list(cmd.sections.keys()),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/docs/spec/{config_name}", tags=["Documentation"])
async def get_spec_doc(config_name: str, stanza: Optional[str] = None):
    """
    Look up Splunk configuration specification.

    Optionally filter by stanza name for specific settings.
    """
    try:
        from shared.docs_loader import get_docs
        docs = get_docs()
        spec = docs.get_spec(config_name)
        if not spec:
            raise HTTPException(status_code=404, detail=f"Spec '{config_name}' not found")

        result = {
            "config_name": spec.config_name,
            "version": spec.version,
            "overview": spec.overview[:500] if spec.overview else "",
            "stanza_count": len(spec.stanzas),
        }

        if stanza:
            s = spec.stanzas.get(stanza)
            if not s:
                raise HTTPException(status_code=404, detail=f"Stanza '{stanza}' not found in {config_name}")
            result["stanza"] = {
                "name": s.name,
                "settings": {
                    k: {"type": v.type_hint, "description": v.description[:200], "default": v.default}
                    for k, v in s.settings.items()
                },
            }
        else:
            result["stanzas"] = list(spec.stanzas.keys())[:50]

        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/docs/limits/{command}", tags=["Documentation"])
async def get_limits_for_command(command: str):
    """
    Get limits.conf settings relevant to a specific SPL command.
    """
    try:
        from shared.docs_loader import get_docs
        docs = get_docs()
        limits = docs.get_limits_info(command)
        if not limits:
            raise HTTPException(status_code=404, detail=f"No limits.conf settings found for '{command}'")
        return {"command": command, "limits": limits}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9005)
