"""
Data Engineer Skill — Analyze data flows, suggest transforms, validate
CIM data models, and design index strategies.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CIM data model field definitions
# ---------------------------------------------------------------------------

_CIM_MODELS: Dict[str, Dict[str, Any]] = {
    "Authentication": {
        "required": ["action", "app", "dest", "src", "user"],
        "recommended": ["authentication_method", "duration", "reason", "signature",
                        "src_user", "tag", "vendor_product"],
        "description": "Tracks authentication attempts including logins, logouts, and failures",
    },
    "Network_Traffic": {
        "required": ["action", "bytes", "bytes_in", "bytes_out", "dest", "dest_port",
                      "protocol", "src", "src_port", "transport"],
        "recommended": ["app", "dest_ip", "dest_mac", "direction", "duration",
                        "packets", "src_ip", "src_mac", "vendor_product"],
        "description": "Models network communication events between hosts",
    },
    "Endpoint": {
        "required": ["action", "dest", "process", "process_id", "user"],
        "recommended": ["app", "file_hash", "file_name", "file_path", "os",
                        "parent_process", "parent_process_id", "vendor_product"],
        "description": "Models endpoint process and file activity",
    },
    "Web": {
        "required": ["action", "dest", "http_method", "src", "status", "uri_path", "url"],
        "recommended": ["bytes", "http_content_type", "http_referrer", "http_user_agent",
                        "uri_query", "user", "vendor_product"],
        "description": "Models web/HTTP request and response activity",
    },
    "Change": {
        "required": ["action", "change_type", "dest", "object", "object_category", "user"],
        "recommended": ["command", "object_attrs", "object_id", "object_path",
                        "result", "status", "vendor_product"],
        "description": "Models change events such as configuration and account changes",
    },
    "Malware": {
        "required": ["action", "dest", "file_hash", "file_name", "signature", "user"],
        "recommended": ["file_path", "severity", "src", "url", "vendor_product"],
        "description": "Models malware detection and response events",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOTTLENECK_KEYWORDS = {
    "heavy forwarder": "Heavy forwarders add processing overhead. Consider using Universal Forwarders where possible.",
    "single indexer": "Single indexer is a bottleneck. Consider indexer clustering for load distribution.",
    "no load balancer": "Without load balancing, a single forwarder-to-indexer link is a single point of failure.",
    "parsing": "Parsing at ingest time can cause queue blocking. Move complex regex to search time if possible.",
    "tcp": "TCP inputs without acknowledgment can lose data. Enable indexer acknowledgment for critical data.",
    "udp": "UDP is unreliable for log transport. Consider switching to TCP with TLS for production data.",
    "syslog": "Syslog inputs can be overwhelmed at high volume. Use a dedicated syslog-ng/rsyslog tier.",
    "hec": "HEC endpoints should use load balancers and indexer acknowledgment for reliability.",
    "queue": "Queue congestion indicates the downstream component cannot keep up. Check indexer capacity.",
    "props.conf": "Excessive props.conf transforms at index time slow ingestion. Prefer search-time extractions.",
}

_FIELD_PATTERNS = {
    r"(?i)(src_?ip|source_?ip|s_ip|client_?ip)": ("src_ip", "IP address of the source"),
    r"(?i)(dst_?ip|dest_?ip|destination_?ip|d_ip|server_?ip)": ("dest_ip", "IP address of the destination"),
    r"(?i)(src_?port|source_?port|s_port)": ("src_port", "Source port number"),
    r"(?i)(dst_?port|dest_?port|destination_?port|d_port)": ("dest_port", "Destination port number"),
    r"(?i)(user_?name|usr|login_?name|account)": ("user", "Username or account name"),
    r"(?i)(time_?stamp|event_?time|log_?time|datetime)": ("_time", "Event timestamp"),
    r"(?i)(host_?name|hostname|host)": ("host", "Host name"),
    r"(?i)(severity|level|priority|log_?level)": ("severity", "Log severity level"),
    r"(?i)(action|event_?action|activity)": ("action", "Action taken"),
    r"(?i)(status_?code|http_?status|response_?code)": ("status", "Status or response code"),
    r"(?i)(bytes|byte_?count|size|content_?length)": ("bytes", "Byte count"),
    r"(?i)(duration|elapsed|response_?time|latency)": ("duration", "Duration or latency"),
    r"(?i)(url|uri|request_?url|path)": ("url", "URL or URI path"),
    r"(?i)(proto|protocol|transport)": ("protocol", "Network protocol"),
    r"(?i)(pid|process_?id)": ("process_id", "Process identifier"),
    r"(?i)(process_?name|proc|command)": ("process", "Process name"),
}


def _identify_bottlenecks(description: str) -> List[Dict[str, str]]:
    """Scan a data flow description for common bottleneck keywords."""
    desc_lower = description.lower()
    found = []
    for keyword, advice in _BOTTLENECK_KEYWORDS.items():
        if keyword in desc_lower:
            found.append({"keyword": keyword, "advice": advice})
    return found


def _map_field(field_name: str) -> Optional[Dict[str, str]]:
    """Map a raw field name to a CIM-compatible field using pattern matching."""
    for pattern, (cim_field, desc) in _FIELD_PATTERNS.items():
        if re.search(pattern, field_name):
            return {"original": field_name, "cim_field": cim_field, "description": desc}
    return None


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def analyze_data_flow(description: str) -> str:
    """
    Analyze data flow from source to index, identify bottlenecks.

    Args:
        description: Description of the data flow pipeline.

    Returns:
        JSON string with analysis results and recommendations.
    """
    if not description or not description.strip():
        return json.dumps({"status": "error", "error": "Description cannot be empty"})

    desc_lower = description.lower()

    # Identify components
    components = []
    component_keywords = {
        "universal forwarder": "collection",
        "heavy forwarder": "collection",
        "forwarder": "collection",
        "syslog": "collection",
        "hec": "collection",
        "http event collector": "collection",
        "scripted input": "collection",
        "monitor": "collection",
        "indexer": "indexing",
        "index cluster": "indexing",
        "search head": "search",
        "search head cluster": "search",
        "deployment server": "management",
        "license server": "management",
        "load balancer": "routing",
        "cribl": "routing",
        "kafka": "routing",
        "intermediate forwarder": "routing",
    }
    for keyword, category in component_keywords.items():
        if keyword in desc_lower:
            components.append({"component": keyword, "category": category})

    # Identify bottlenecks
    bottlenecks = _identify_bottlenecks(description)

    # Generate recommendations
    recommendations = []
    if not any(c["category"] == "routing" for c in components):
        recommendations.append("Consider adding a load balancer between forwarders and indexers for resilience.")
    if any(c["component"] == "heavy forwarder" for c in components):
        recommendations.append("Evaluate whether heavy forwarder processing can move to indexer or search time.")
    if "syslog" in desc_lower and "tcp" not in desc_lower:
        recommendations.append("Ensure syslog is using TCP (not UDP) for reliable log delivery.")
    if not any(c["category"] == "indexing" for c in components):
        recommendations.append("No indexer detected in description. Ensure data reaches an indexer tier.")
    if any(c["component"] == "index cluster" for c in components):
        recommendations.append("With indexer clustering, ensure replication factor and search factor are configured.")

    # Estimate pipeline stages
    stages = []
    if any(c["category"] == "collection" for c in components):
        stages.append("Collection: Data ingested from sources")
    if any(c["category"] == "routing" for c in components):
        stages.append("Routing: Data routed/transformed before indexing")
    if any(c["category"] == "indexing" for c in components):
        stages.append("Indexing: Data parsed, indexed, and stored")
    if any(c["category"] == "search" for c in components):
        stages.append("Search: Data available for search and analysis")

    if not stages:
        stages = ["Unable to identify pipeline stages from description. Provide more detail about components."]

    return json.dumps({
        "status": "ok",
        "components_detected": components,
        "pipeline_stages": stages,
        "bottlenecks": bottlenecks,
        "recommendations": recommendations,
        "component_count": len(components),
    }, indent=2)


def suggest_transforms(fields: str, sourcetype: Optional[str] = None) -> str:
    """
    Suggest field transforms, extractions, and enrichments.

    Args:
        fields: Comma-separated list of field names.
        sourcetype: Optional sourcetype context.

    Returns:
        JSON string with suggested TRANSFORMS and props.conf stanzas.
    """
    if not fields or not fields.strip():
        return json.dumps({"status": "error", "error": "Fields list cannot be empty"})

    field_list = [f.strip() for f in fields.split(",") if f.strip()]
    mappings = []
    props_stanzas = []
    transforms_stanzas = []

    for field in field_list:
        mapping = _map_field(field)
        if mapping:
            mappings.append(mapping)

    # Generate props.conf suggestions
    st = sourcetype or "my_sourcetype"
    props_stanzas.append(f"[{st}]")

    for m in mappings:
        if m["original"] != m["cim_field"]:
            # FIELDALIAS
            props_stanzas.append(f"FIELDALIAS-{m['cim_field']} = {m['original']} AS {m['cim_field']}")

    # Suggest EXTRACT for unrecognized fields
    unmapped = [f for f in field_list if not _map_field(f)]
    for field in unmapped:
        props_stanzas.append(f"EXTRACT-{field} = (?i){field}[=:]\\s*(?P<{field}>\\S+)")

    # Suggest TRANSFORMS for complex extractions
    if len(field_list) > 5:
        transforms_name = f"extract_{st}_fields"
        transforms_stanzas.append(f"[{transforms_name}]")
        field_names = ",".join(field_list[:10])
        transforms_stanzas.append(f"REGEX = (.+)")
        transforms_stanzas.append(f"FORMAT = {field_names}")
        props_stanzas.append(f"TRANSFORMS-fields = {transforms_name}")

    # Suggest lookup enrichments for common field types
    enrichments = []
    for m in mappings:
        if m["cim_field"] in ("src_ip", "dest_ip"):
            enrichments.append({
                "field": m["cim_field"],
                "lookup": "geo_ip_lookup",
                "description": f"Enrich {m['cim_field']} with geolocation data via iplocation command",
            })
        elif m["cim_field"] == "user":
            enrichments.append({
                "field": m["cim_field"],
                "lookup": "identity_lookup",
                "description": f"Enrich {m['cim_field']} with identity context from ES identity table",
            })

    return json.dumps({
        "status": "ok",
        "field_count": len(field_list),
        "mappings": mappings,
        "unmapped_fields": unmapped,
        "props_conf": "\n".join(props_stanzas),
        "transforms_conf": "\n".join(transforms_stanzas) if transforms_stanzas else None,
        "suggested_enrichments": enrichments,
    }, indent=2)


def validate_data_model(data_model: str, fields: str) -> str:
    """
    Validate field mappings against a CIM data model.

    Args:
        data_model: CIM data model name.
        fields: Comma-separated list of available field names.

    Returns:
        JSON string with validation results.
    """
    if not data_model or not data_model.strip():
        return json.dumps({"status": "error", "error": "Data model name cannot be empty"})
    if not fields or not fields.strip():
        return json.dumps({"status": "error", "error": "Fields list cannot be empty"})

    model_key = data_model.strip()
    # Try case-insensitive match
    matched_model = None
    for key in _CIM_MODELS:
        if key.lower() == model_key.lower():
            matched_model = key
            break

    if not matched_model:
        return json.dumps({
            "status": "error",
            "error": f"Unknown CIM data model: {data_model}",
            "available_models": list(_CIM_MODELS.keys()),
        })

    model = _CIM_MODELS[matched_model]
    field_list = [f.strip().lower() for f in fields.split(",") if f.strip()]

    # Map provided fields to CIM fields
    field_mappings = {}
    for field in field_list:
        mapping = _map_field(field)
        if mapping:
            field_mappings[field] = mapping["cim_field"]
        else:
            field_mappings[field] = field

    mapped_cim_fields = set(field_mappings.values())

    # Check required fields
    required = model["required"]
    required_present = [f for f in required if f.lower() in mapped_cim_fields]
    required_missing = [f for f in required if f.lower() not in mapped_cim_fields]

    # Check recommended fields
    recommended = model["recommended"]
    recommended_present = [f for f in recommended if f.lower() in mapped_cim_fields]
    recommended_missing = [f for f in recommended if f.lower() not in mapped_cim_fields]

    # Calculate compliance score
    total_required = len(required)
    total_recommended = len(recommended)
    req_score = len(required_present) / total_required if total_required > 0 else 1.0
    rec_score = len(recommended_present) / total_recommended if total_recommended > 0 else 1.0
    compliance_score = round((req_score * 0.7 + rec_score * 0.3) * 100, 1)

    if compliance_score >= 90:
        compliance_level = "excellent"
    elif compliance_score >= 70:
        compliance_level = "good"
    elif compliance_score >= 50:
        compliance_level = "partial"
    else:
        compliance_level = "poor"

    return json.dumps({
        "status": "ok",
        "data_model": matched_model,
        "model_description": model["description"],
        "compliance_score": compliance_score,
        "compliance_level": compliance_level,
        "required_fields": {
            "present": required_present,
            "missing": required_missing,
            "total": total_required,
        },
        "recommended_fields": {
            "present": recommended_present,
            "missing": recommended_missing,
            "total": total_recommended,
        },
        "field_mappings": field_mappings,
        "suggestions": [
            f"Add field alias or extraction for missing required field: {f}" for f in required_missing
        ],
    }, indent=2)


def design_index_strategy(use_case: str, daily_volume_gb: float,
                           retention_days: Optional[int] = None) -> str:
    """
    Suggest index, sourcetype, and retention strategy.

    Args:
        use_case: Description of the use case.
        daily_volume_gb: Estimated daily ingest volume in GB.
        retention_days: Desired retention in days.

    Returns:
        JSON string with index strategy recommendations.
    """
    if not use_case or not use_case.strip():
        return json.dumps({"status": "error", "error": "Use case description cannot be empty"})
    if daily_volume_gb <= 0:
        return json.dumps({"status": "error", "error": "Daily volume must be positive"})

    uc_lower = use_case.lower()

    # Determine category and defaults
    if any(kw in uc_lower for kw in ["security", "threat", "ids", "firewall", "auth"]):
        category = "security"
        default_retention = 365
        suggested_index = "security"
        suggested_sourcetypes = ["syslog", "firewall", "ids", "auth"]
    elif any(kw in uc_lower for kw in ["web", "http", "apache", "nginx", "iis"]):
        category = "web"
        default_retention = 90
        suggested_index = "web"
        suggested_sourcetypes = ["access_combined", "apache:error", "nginx:access"]
    elif any(kw in uc_lower for kw in ["app", "application", "microservice", "api"]):
        category = "application"
        default_retention = 90
        suggested_index = "application"
        suggested_sourcetypes = ["app:json", "app:log", "docker:json"]
    elif any(kw in uc_lower for kw in ["metric", "perf", "monitor", "apm"]):
        category = "metrics"
        default_retention = 30
        suggested_index = "metrics"
        suggested_sourcetypes = ["collectd", "statsd", "prometheus"]
    elif any(kw in uc_lower for kw in ["network", "dns", "dhcp", "netflow"]):
        category = "network"
        default_retention = 30
        suggested_index = "network"
        suggested_sourcetypes = ["netflow", "dns", "dhcp"]
    else:
        category = "general"
        default_retention = 90
        suggested_index = "main"
        suggested_sourcetypes = ["syslog", "generic_log"]

    retention = retention_days if retention_days and retention_days > 0 else default_retention
    total_storage_gb = round(daily_volume_gb * retention * 0.5, 1)  # ~50% compression
    raw_storage_gb = round(daily_volume_gb * retention, 1)

    # Determine if multiple indexes are needed
    index_strategy = []
    if daily_volume_gb > 100:
        index_strategy.append({
            "index": f"{suggested_index}_hot",
            "purpose": "Hot/warm data for recent searches",
            "retention_days": min(retention, 30),
            "max_data_size": "auto_high_volume",
        })
        index_strategy.append({
            "index": f"{suggested_index}_cold",
            "purpose": "Cold data for long-term retention",
            "retention_days": retention,
            "max_data_size": "auto",
        })
    else:
        index_strategy.append({
            "index": suggested_index,
            "purpose": f"Primary index for {category} data",
            "retention_days": retention,
            "max_data_size": "auto_high_volume" if daily_volume_gb > 50 else "auto",
        })

    # Generate indexes.conf stanza
    conf_lines = []
    for idx in index_strategy:
        conf_lines.append(f"[{idx['index']}]")
        conf_lines.append(f"homePath = $SPLUNK_DB/{idx['index']}/db")
        conf_lines.append(f"coldPath = $SPLUNK_DB/{idx['index']}/colddb")
        conf_lines.append(f"thawedPath = $SPLUNK_DB/{idx['index']}/thaweddb")
        conf_lines.append(f"frozenTimePeriodInSecs = {idx['retention_days'] * 86400}")
        conf_lines.append(f"maxDataSize = {idx['max_data_size']}")
        conf_lines.append("")

    return json.dumps({
        "status": "ok",
        "use_case": use_case,
        "category": category,
        "daily_volume_gb": daily_volume_gb,
        "retention_days": retention,
        "estimated_storage": {
            "compressed_gb": total_storage_gb,
            "raw_gb": raw_storage_gb,
            "compression_ratio": "~50%",
        },
        "index_strategy": index_strategy,
        "suggested_sourcetypes": suggested_sourcetypes,
        "indexes_conf": "\n".join(conf_lines),
        "recommendations": [
            f"Set frozenTimePeriodInSecs to {retention * 86400} ({retention} days)",
            "Enable volume-based retention if managing multiple indexes",
            "Configure index replication factor in clustered environments",
            "Use maxHotBuckets to control concurrent bucket count",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("data_engineer skill cleaned up")
