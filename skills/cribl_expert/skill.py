"""
Cribl Expert Skill — Design pipelines, optimize performance, generate routes,
and estimate data volume reduction for Cribl Stream.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cribl function catalog
# ---------------------------------------------------------------------------

_CRIBL_FUNCTIONS: Dict[str, Dict[str, Any]] = {
    "eval": {
        "description": "Evaluate JavaScript expressions to create, modify, or remove fields",
        "category": "field_management",
        "reduction_pct": 0,
        "cpu_cost": "low",
    },
    "regex_extract": {
        "description": "Extract fields from events using regular expressions",
        "category": "field_management",
        "reduction_pct": 0,
        "cpu_cost": "medium",
    },
    "rename": {
        "description": "Rename fields in events",
        "category": "field_management",
        "reduction_pct": 0,
        "cpu_cost": "low",
    },
    "mask": {
        "description": "Mask sensitive data using regex patterns and replacement values",
        "category": "security",
        "reduction_pct": 0,
        "cpu_cost": "medium",
    },
    "drop": {
        "description": "Drop events matching a filter expression",
        "category": "filtering",
        "reduction_pct": 30,
        "cpu_cost": "low",
    },
    "sampling": {
        "description": "Sample events at a specified rate to reduce volume",
        "category": "filtering",
        "reduction_pct": 50,
        "cpu_cost": "low",
    },
    "suppress": {
        "description": "Suppress duplicate events within a time window",
        "category": "filtering",
        "reduction_pct": 25,
        "cpu_cost": "medium",
    },
    "aggregation": {
        "description": "Aggregate events over a time window into summary metrics",
        "category": "aggregation",
        "reduction_pct": 60,
        "cpu_cost": "medium",
    },
    "serialize": {
        "description": "Convert events to a different format (JSON, CSV, etc.)",
        "category": "formatting",
        "reduction_pct": 5,
        "cpu_cost": "low",
    },
    "parser": {
        "description": "Parse structured data formats (JSON, CSV, KV, etc.)",
        "category": "parsing",
        "reduction_pct": 0,
        "cpu_cost": "medium",
    },
    "lookup": {
        "description": "Enrich events with data from a lookup file or external source",
        "category": "enrichment",
        "reduction_pct": 0,
        "cpu_cost": "medium",
    },
    "geoip": {
        "description": "Enrich IP addresses with geolocation data",
        "category": "enrichment",
        "reduction_pct": 0,
        "cpu_cost": "low",
    },
    "publish_metrics": {
        "description": "Convert events to metrics format for metrics destinations",
        "category": "metrics",
        "reduction_pct": 70,
        "cpu_cost": "medium",
    },
    "redis": {
        "description": "Enrich events with data from Redis",
        "category": "enrichment",
        "reduction_pct": 0,
        "cpu_cost": "high",
    },
    "comment": {
        "description": "Add a comment to the pipeline for documentation",
        "category": "utility",
        "reduction_pct": 0,
        "cpu_cost": "none",
    },
    "auto_timestamp": {
        "description": "Automatically detect and set the event timestamp",
        "category": "parsing",
        "reduction_pct": 0,
        "cpu_cost": "low",
    },
    "json_unroll": {
        "description": "Unroll nested JSON arrays into separate events",
        "category": "parsing",
        "reduction_pct": -20,
        "cpu_cost": "medium",
    },
    "trim": {
        "description": "Remove unnecessary fields from events to reduce size",
        "category": "field_management",
        "reduction_pct": 15,
        "cpu_cost": "low",
    },
}

# ---------------------------------------------------------------------------
# Route destination templates
# ---------------------------------------------------------------------------

_DESTINATIONS = {
    "splunk": {"type": "splunk", "host": "${SPLUNK_HOST}", "port": 9997, "protocol": "tcp"},
    "s3": {"type": "s3", "bucket": "${S3_BUCKET}", "region": "${AWS_REGION}", "format": "json"},
    "elastic": {"type": "elastic", "url": "${ELASTIC_URL}", "index": "${ELASTIC_INDEX}"},
    "kafka": {"type": "kafka", "brokers": ["${KAFKA_BROKER}"], "topic": "${KAFKA_TOPIC}"},
    "devnull": {"type": "devnull", "description": "Discard events"},
    "syslog": {"type": "syslog", "host": "${SYSLOG_HOST}", "port": 514, "protocol": "tcp"},
    "datadog": {"type": "datadog", "apiKey": "${DD_API_KEY}", "site": "datadoghq.com"},
    "azure": {"type": "azure_blob", "container": "${AZURE_CONTAINER}", "storageAccount": "${AZURE_STORAGE}"},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIREMENT_KEYWORDS: Dict[str, List[str]] = {
    "drop": ["filter", "drop", "remove events", "discard", "exclude"],
    "mask": ["mask", "redact", "pii", "ssn", "credit card", "anonymize", "obfuscate"],
    "trim": ["trim", "remove fields", "strip", "clean"],
    "sampling": ["sample", "sampling", "reduce volume"],
    "suppress": ["dedup", "suppress", "duplicate", "deduplicate"],
    "aggregation": ["aggregate", "summarize", "rollup", "metrics"],
    "regex_extract": ["extract", "regex", "parse field"],
    "parser": ["parse json", "parse csv", "parse kv", "structured"],
    "eval": ["calculate", "compute", "transform", "add field", "create field"],
    "rename": ["rename", "alias"],
    "lookup": ["enrich", "lookup", "join"],
    "geoip": ["geo", "geoip", "geolocation", "location"],
    "serialize": ["convert", "format", "serialize"],
    "publish_metrics": ["publish metrics", "metrics format"],
    "auto_timestamp": ["timestamp", "time parse"],
}


def _match_functions(requirements: str) -> List[str]:
    """Match requirement keywords to Cribl functions."""
    req_lower = requirements.lower()
    matched = []
    for func_name, keywords in _REQUIREMENT_KEYWORDS.items():
        for kw in keywords:
            if kw in req_lower and func_name not in matched:
                matched.append(func_name)
                break
    return matched


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def design_pipeline(requirements: str) -> str:
    """
    Design a Cribl Stream pipeline from requirements description.

    Args:
        requirements: Description of pipeline requirements.

    Returns:
        JSON string with pipeline specification.
    """
    if not requirements or not requirements.strip():
        return json.dumps({"status": "error", "error": "Requirements cannot be empty"})

    matched_functions = _match_functions(requirements)

    if not matched_functions:
        return json.dumps({
            "status": "ok",
            "message": "No specific functions matched. Here is a basic pipeline template.",
            "pipeline": {
                "id": "custom_pipeline",
                "functions": [
                    {"id": "comment", "description": "Pipeline generated from requirements"},
                    {"id": "eval", "description": "Add or modify fields as needed"},
                ],
            },
            "available_functions": list(_CRIBL_FUNCTIONS.keys()),
        })

    # Order functions optimally: filter first, then process, then output formatting
    order_priority = {"drop": 0, "sampling": 1, "suppress": 2, "parser": 3,
                      "auto_timestamp": 3, "regex_extract": 4, "eval": 5,
                      "rename": 5, "trim": 6, "mask": 7, "lookup": 8,
                      "geoip": 8, "aggregation": 9, "publish_metrics": 10,
                      "serialize": 11}
    matched_functions.sort(key=lambda f: order_priority.get(f, 50))

    pipeline_functions = []
    for func_name in matched_functions:
        func_info = _CRIBL_FUNCTIONS.get(func_name, {})
        pipeline_functions.append({
            "id": func_name,
            "description": func_info.get("description", ""),
            "category": func_info.get("category", ""),
            "cpu_cost": func_info.get("cpu_cost", "unknown"),
            "conf": {},
        })

    return json.dumps({
        "status": "ok",
        "pipeline": {
            "id": "generated_pipeline",
            "description": f"Pipeline designed from: {requirements[:100]}",
            "functions": pipeline_functions,
        },
        "function_count": len(pipeline_functions),
        "design_notes": [
            "Functions are ordered: filtering first, processing second, formatting last",
            "Configure each function's 'conf' block with specific parameters",
            "Add filter expressions to limit which events each function processes",
            "Test the pipeline with sample data before deploying to production",
        ],
    }, indent=2)


def optimize_pipeline(pipeline: str) -> str:
    """
    Optimize an existing Cribl pipeline for performance and cost.

    Args:
        pipeline: JSON string or description of the existing pipeline.

    Returns:
        JSON string with optimization recommendations.
    """
    if not pipeline or not pipeline.strip():
        return json.dumps({"status": "error", "error": "Pipeline description cannot be empty"})

    # Try to parse as JSON
    functions_list = []
    try:
        parsed = json.loads(pipeline)
        if isinstance(parsed, dict) and "functions" in parsed:
            functions_list = [f.get("id", f.get("name", "")) for f in parsed["functions"]]
        elif isinstance(parsed, list):
            functions_list = [f.get("id", f.get("name", "")) if isinstance(f, dict) else str(f) for f in parsed]
    except (json.JSONDecodeError, TypeError):
        # Parse from text description
        pipe_lower = pipeline.lower()
        for func_name in _CRIBL_FUNCTIONS:
            if func_name in pipe_lower:
                functions_list.append(func_name)

    if not functions_list:
        return json.dumps({
            "status": "error",
            "error": "Could not identify pipeline functions from input",
            "hint": "Provide a JSON pipeline definition or list function names in the description",
        })

    recommendations = []
    optimized_order = list(functions_list)

    # Check if filtering happens before processing
    filter_funcs = {"drop", "sampling", "suppress"}
    process_funcs = {"eval", "regex_extract", "mask", "lookup", "geoip", "parser"}
    first_filter_idx = None
    first_process_idx = None

    for i, func in enumerate(functions_list):
        if func in filter_funcs and first_filter_idx is None:
            first_filter_idx = i
        if func in process_funcs and first_process_idx is None:
            first_process_idx = i

    if first_filter_idx is not None and first_process_idx is not None:
        if first_process_idx < first_filter_idx:
            recommendations.append({
                "type": "reorder",
                "severity": "high",
                "message": "Move filtering functions (drop, sampling, suppress) before processing functions to reduce work",
            })

    # Check for redundant functions
    seen = set()
    for func in functions_list:
        if func in seen and func not in ("eval", "rename"):
            recommendations.append({
                "type": "redundancy",
                "severity": "medium",
                "message": f"Duplicate '{func}' function detected — consider combining into one",
            })
        seen.add(func)

    # Check for expensive functions without filters
    expensive = {"regex_extract", "lookup", "redis", "geoip"}
    for func in functions_list:
        if func in expensive:
            if "drop" not in functions_list and "sampling" not in functions_list:
                recommendations.append({
                    "type": "performance",
                    "severity": "medium",
                    "message": f"'{func}' is CPU-intensive. Add filtering (drop/sampling) before it to reduce load.",
                })

    # Check for missing trim at end
    if "trim" not in functions_list and len(functions_list) > 2:
        recommendations.append({
            "type": "optimization",
            "severity": "low",
            "message": "Consider adding a 'trim' function at the end to remove unnecessary fields and reduce output size",
        })

    # Estimate overall CPU cost
    total_cost = 0
    cost_map = {"none": 0, "low": 1, "medium": 2, "high": 3}
    for func in functions_list:
        func_info = _CRIBL_FUNCTIONS.get(func, {})
        total_cost += cost_map.get(func_info.get("cpu_cost", "low"), 1)

    if total_cost > 8:
        cpu_assessment = "high"
    elif total_cost > 4:
        cpu_assessment = "medium"
    else:
        cpu_assessment = "low"

    return json.dumps({
        "status": "ok",
        "current_functions": functions_list,
        "function_count": len(functions_list),
        "cpu_assessment": cpu_assessment,
        "recommendations": recommendations,
        "recommendation_count": len(recommendations),
    }, indent=2)


def generate_route(description: str) -> str:
    """
    Generate Cribl route configuration with filters.

    Args:
        description: Description of routing requirements.

    Returns:
        JSON string with route configuration.
    """
    if not description or not description.strip():
        return json.dumps({"status": "error", "error": "Description cannot be empty"})

    desc_lower = description.lower()
    routes = []

    # Detect source types and destinations
    dest_keywords = {
        "splunk": ["splunk", "hec", "indexer"],
        "s3": ["s3", "aws", "bucket", "archive"],
        "elastic": ["elastic", "elasticsearch", "elk", "kibana"],
        "kafka": ["kafka", "topic", "stream"],
        "devnull": ["drop", "discard", "null", "devnull", "trash"],
        "syslog": ["syslog", "rsyslog", "syslog-ng"],
        "datadog": ["datadog", "dd"],
        "azure": ["azure", "blob"],
    }

    source_keywords = {
        "syslog": ["syslog", "facility", "severity"],
        "windows": ["windows", "winevent", "wmi"],
        "linux": ["linux", "auth.log", "syslog"],
        "firewall": ["firewall", "palo", "fortinet", "checkpoint"],
        "web": ["web", "apache", "nginx", "http", "access_log"],
        "metrics": ["metric", "statsd", "collectd", "prometheus"],
        "debug": ["debug", "verbose", "trace"],
        "json": ["json", "structured"],
    }

    detected_dests = []
    for dest_name, keywords in dest_keywords.items():
        for kw in keywords:
            if kw in desc_lower:
                detected_dests.append(dest_name)
                break

    detected_sources = []
    for src_name, keywords in source_keywords.items():
        for kw in keywords:
            if kw in desc_lower:
                detected_sources.append(src_name)
                break

    # Build routes from detected patterns
    if detected_sources and detected_dests:
        for i, src in enumerate(detected_sources):
            dest = detected_dests[i] if i < len(detected_dests) else detected_dests[-1]
            filter_expr = f'sourcetype=="{src}" || __inputId.startsWith("{src}")'
            routes.append({
                "id": f"route_{src}_to_{dest}",
                "name": f"Route {src} to {dest}",
                "filter": filter_expr,
                "pipeline": f"pipeline_{src}",
                "output": dest,
                "destination_config": _DESTINATIONS.get(dest, {}),
                "enabled": True,
                "description": f"Route {src} events to {dest} destination",
            })
    elif detected_dests:
        for dest in detected_dests:
            routes.append({
                "id": f"route_default_to_{dest}",
                "name": f"Route to {dest}",
                "filter": "true",
                "pipeline": "passthru",
                "output": dest,
                "destination_config": _DESTINATIONS.get(dest, {}),
                "enabled": True,
                "description": f"Default route to {dest}",
            })

    # Always add a default route
    if routes:
        routes.append({
            "id": "route_default",
            "name": "Default Route",
            "filter": "true",
            "pipeline": "passthru",
            "output": "splunk",
            "destination_config": _DESTINATIONS.get("splunk", {}),
            "enabled": True,
            "final": True,
            "description": "Catch-all default route",
        })

    if not routes:
        return json.dumps({
            "status": "ok",
            "message": "Could not auto-detect routing patterns. Providing a template.",
            "routes": [{
                "id": "route_template",
                "name": "Template Route",
                "filter": "__inputId.startsWith('in_')",
                "pipeline": "passthru",
                "output": "default",
                "enabled": True,
            }],
            "available_destinations": list(_DESTINATIONS.keys()),
        })

    return json.dumps({
        "status": "ok",
        "routes": routes,
        "route_count": len(routes),
        "detected_sources": detected_sources,
        "detected_destinations": detected_dests,
        "notes": [
            "Routes are evaluated in order — place specific routes before catch-all",
            "Use __inputId to match by input source",
            "Replace environment variables (${VAR}) with actual values",
            "Test filters with the Cribl preview feature before deploying",
        ],
    }, indent=2)


def estimate_reduction(daily_volume_gb: float, transforms: str) -> str:
    """
    Estimate data volume reduction from pipeline transformations.

    Args:
        daily_volume_gb: Current daily data volume in GB.
        transforms: Comma-separated list of transforms to apply.

    Returns:
        JSON string with reduction estimates.
    """
    if daily_volume_gb <= 0:
        return json.dumps({"status": "error", "error": "Daily volume must be positive"})
    if not transforms or not transforms.strip():
        return json.dumps({"status": "error", "error": "Transforms list cannot be empty"})

    transform_list = [t.strip().lower() for t in transforms.split(",") if t.strip()]

    # Map common transform descriptions to function names
    transform_aliases = {
        "filter_debug": "drop", "filter": "drop", "drop_debug": "drop",
        "mask_pii": "mask", "mask": "mask", "redact": "mask",
        "remove_fields": "trim", "trim": "trim", "strip_fields": "trim",
        "suppress_duplicates": "suppress", "dedup": "suppress", "suppress": "suppress",
        "sample": "sampling", "sampling": "sampling",
        "aggregate": "aggregation", "rollup": "aggregation", "summarize": "aggregation",
        "metrics": "publish_metrics", "publish_metrics": "publish_metrics",
        "serialize": "serialize", "format": "serialize",
    }

    applied = []
    remaining_pct = 100.0

    for transform in transform_list:
        func_name = transform_aliases.get(transform, transform)
        func_info = _CRIBL_FUNCTIONS.get(func_name, {})
        reduction = func_info.get("reduction_pct", 0)

        if reduction > 0:
            actual_reduction = remaining_pct * (reduction / 100.0)
            remaining_pct -= actual_reduction
            applied.append({
                "transform": transform,
                "function": func_name,
                "reduction_pct": reduction,
                "volume_after_gb": round(daily_volume_gb * remaining_pct / 100.0, 2),
            })
        elif reduction < 0:
            expansion = abs(reduction)
            remaining_pct += remaining_pct * (expansion / 100.0)
            applied.append({
                "transform": transform,
                "function": func_name,
                "reduction_pct": reduction,
                "volume_after_gb": round(daily_volume_gb * remaining_pct / 100.0, 2),
                "note": "This transform increases volume",
            })
        else:
            applied.append({
                "transform": transform,
                "function": func_name,
                "reduction_pct": 0,
                "volume_after_gb": round(daily_volume_gb * remaining_pct / 100.0, 2),
                "note": "No volume change — processing-only function",
            })

    total_reduction_pct = round(100.0 - remaining_pct, 1)
    final_volume = round(daily_volume_gb * remaining_pct / 100.0, 2)
    daily_savings_gb = round(daily_volume_gb - final_volume, 2)

    # Estimate cost savings (approximate $1/GB/day for Splunk-class tools)
    monthly_savings_gb = round(daily_savings_gb * 30, 1)
    estimated_monthly_cost_savings = round(monthly_savings_gb * 1.0, 2)

    return json.dumps({
        "status": "ok",
        "input_volume_gb": daily_volume_gb,
        "output_volume_gb": final_volume,
        "total_reduction_pct": total_reduction_pct,
        "daily_savings_gb": daily_savings_gb,
        "monthly_savings_gb": monthly_savings_gb,
        "estimated_monthly_cost_savings_usd": estimated_monthly_cost_savings,
        "transform_details": applied,
        "notes": [
            "Estimates are approximate and vary based on data characteristics",
            "Actual reduction depends on filter match rates and data patterns",
            "Cost savings assume ~$1/GB/day for SIEM/analytics platforms",
            "Test with representative data samples to validate estimates",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("cribl_expert skill cleaned up")
