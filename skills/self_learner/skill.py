"""
Self Learner Skill — Review interactions, identify knowledge gaps, generate
training Q&A pairs, and measure improvement trends.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge topic catalog with sample Q&A seeds
# ---------------------------------------------------------------------------

_TOPIC_CATALOG: Dict[str, Dict[str, Any]] = {
    "spl_optimization": {
        "description": "SPL query optimization techniques and best practices",
        "seed_pairs": [
            {"q": "How can I optimize a search that uses index=*?",
             "a": "Replace index=* with specific index names to reduce the search scope. Wildcard index searches scan all indexes, consuming excessive resources."},
            {"q": "When should I use tstats instead of stats?",
             "a": "Use tstats when searching indexed fields or accelerated data models. tstats searches tsidx files directly, which is significantly faster than raw event scanning."},
            {"q": "How do I optimize a search with multiple join commands?",
             "a": "Replace join with stats using values() and by clauses where possible. The join command is memory-intensive with a 50K row default limit. Use '| stats values(field) as field by common_key' instead."},
            {"q": "What is the impact of sorting early in the pipeline?",
             "a": "Sorting early forces processing of all events before reduction. Move sort after filtering and aggregation commands to reduce the number of events being sorted."},
            {"q": "How can I reduce the cost of rex extractions?",
             "a": "Move regex extractions to props.conf as indexed extractions (EXTRACT-) for search-time extraction, or combine multiple rex into a single pattern."},
        ],
    },
    "security_detection": {
        "description": "Security threat detection and MITRE ATT&CK mapping",
        "seed_pairs": [
            {"q": "How do I detect brute force attacks in Splunk?",
             "a": "Search for multiple failed authentication attempts from a single source: 'index=security sourcetype=*auth* action=failure | stats count by src | where count > 20'. Tune the threshold based on your environment baseline."},
            {"q": "What SPL detects lateral movement?",
             "a": "Look for RDP/SSH connections to multiple hosts: 'index=network (dest_port=3389 OR dest_port=22) | stats dc(dest) as dest_count by src, user | where dest_count > 3'. This maps to MITRE T1021."},
            {"q": "How do I detect PowerShell abuse?",
             "a": "Search for encoded or obfuscated PowerShell: 'index=endpoint process_name=\"powershell.exe\" (command_line=\"*-enc*\" OR command_line=\"*bypass*\" OR command_line=\"*downloadstring*\")'. Maps to MITRE T1059.001."},
            {"q": "What is the best way to detect data exfiltration?",
             "a": "Monitor for large outbound transfers on non-standard ports: 'index=network dest_port!=80 dest_port!=443 | stats sum(bytes_out) as total by src | where total > 104857600'. Also check for DNS tunneling indicators."},
            {"q": "How do I create a MITRE ATT&CK coverage dashboard?",
             "a": "Map your correlation searches to MITRE technique IDs in a lookup table, then use '| inputlookup mitre_coverage | stats count by tactic, technique_id, detection_name' to visualize coverage gaps."},
        ],
    },
    "data_models": {
        "description": "CIM data models and data normalization",
        "seed_pairs": [
            {"q": "What is the CIM and why is it important?",
             "a": "The Common Information Model (CIM) is a shared semantic model that normalizes field names across different data sources. It enables apps like Enterprise Security to work with any data source that maps to CIM fields."},
            {"q": "How do I map my data to the Authentication data model?",
             "a": "Map your fields to CIM fields: action (success/failure), user, src, dest, app. Use FIELDALIAS in props.conf to rename fields, e.g., 'FIELDALIAS-user = login_name AS user'."},
            {"q": "What is data model acceleration?",
             "a": "Data model acceleration pre-computes summary data in tsidx format, enabling tstats queries that are 10-100x faster than raw searches. Enable via Settings > Data Models > Accelerate."},
            {"q": "How do I validate my CIM mapping?",
             "a": "Use the CIM Validator app or run: '| datamodel Authentication All_Authentication search | head 10 | table user, action, src, dest' to verify field mappings are correct."},
            {"q": "When should I use tags vs eventtypes for CIM compliance?",
             "a": "Use tags on eventtypes to map data to CIM data models. Create eventtypes to match your data, then apply the required tags. Example: eventtype=my_auth_events tags: authentication, default."},
        ],
    },
    "cribl_pipelines": {
        "description": "Cribl Stream pipeline design and optimization",
        "seed_pairs": [
            {"q": "How do I design a Cribl pipeline for PII masking?",
             "a": "Use the Mask function with regex patterns for SSN, credit card, and email. Place the mask function after parsing but before output. Configure replacement patterns like XXX-XX-XXXX for SSN."},
            {"q": "What is the optimal function order in a Cribl pipeline?",
             "a": "Order functions as: 1) Drop/filter (reduce volume first), 2) Parse/extract, 3) Eval/transform, 4) Mask/security, 5) Lookup/enrich, 6) Aggregate, 7) Serialize/format. Filtering first reduces CPU load on subsequent functions."},
            {"q": "How do I estimate data reduction from Cribl?",
             "a": "Common reductions: Drop/filter (30-50%), Suppress duplicates (15-25%), Trim unused fields (10-20%), Aggregation (50-70%), Sampling (configurable). Compound effects multiply, so 3 transforms can achieve 60-80% total reduction."},
            {"q": "How do I route data to multiple destinations in Cribl?",
             "a": "Create routes with filter expressions matching source type or input ID. Routes are evaluated in order — place specific routes before catch-all. Use clone for sending to multiple destinations simultaneously."},
            {"q": "What are Cribl pipeline best practices?",
             "a": "Keep pipelines focused on one purpose. Use comments for documentation. Filter early to reduce volume. Test with sample data before production. Monitor pipeline metrics for performance. Use pack/unpack for nested data."},
        ],
    },
    "troubleshooting": {
        "description": "Splunk troubleshooting and diagnostics",
        "seed_pairs": [
            {"q": "How do I diagnose indexing lag?",
             "a": "Check pipeline queues: 'index=_internal component=Metrics group=queue | eval fill=round((current_size/max_size)*100,2) | stats max(fill) by name'. Queues above 80% indicate congestion."},
            {"q": "What causes search performance degradation?",
             "a": "Common causes: wildcard index searches, expensive commands (join, transaction), excessive time ranges, too many concurrent searches, search head memory pressure, and slow disk I/O on indexers."},
            {"q": "How do I troubleshoot forwarder connectivity?",
             "a": "Check: 1) splunkd process is running, 2) outputs.conf has correct indexer addresses, 3) Firewall allows port 9997, 4) SSL certificates are valid. Query: 'index=_internal component=TcpOutputProc | stats latest(_time) by host'."},
            {"q": "How do I find the cause of license violations?",
             "a": "Identify top data sources: 'index=_internal component=LicenseUsage type=Usage | eval gb=b/1073741824 | stats sum(gb) by st | sort -sum(gb)'. Look for unexpected sourcetypes or duplicated data."},
            {"q": "What should I check after a Splunk crash?",
             "a": "Check: splunkd.log for crash traces, system memory (OOM kills), disk space, ulimit settings, and KV Store health. Query: 'index=_internal log_level=ERROR OR log_level=FATAL | stats count by component, message | sort -count'."},
        ],
    },
    "deployment": {
        "description": "Splunk deployment and configuration management",
        "seed_pairs": [
            {"q": "How do I set up a deployment server?",
             "a": "Create serverclass.conf in $SPLUNK_HOME/etc/system/local/ with server class definitions. Use whitelist/blacklist to target clients. Deploy apps via $SPLUNK_HOME/etc/deployment-apps/. Reload with 'splunk reload deploy-server'."},
            {"q": "What is the correct config file precedence in Splunk?",
             "a": "Precedence (highest to lowest): system/local, app/local, app/default, system/default. Within apps, user directory overrides local which overrides default. Use 'btool list --debug' to trace effective settings."},
            {"q": "How do I manage configurations across a search head cluster?",
             "a": "Use the deployer ($SPLUNK_HOME/etc/shcluster/apps/) to push configs to SHC members. Run 'splunk apply shcluster-bundle' to deploy. Never modify local configs directly on SHC members."},
            {"q": "What are best practices for Splunk version upgrades?",
             "a": "Upgrade order: 1) SHC deployer, 2) Cluster manager, 3) Search heads, 4) Indexers, 5) Heavy forwarders, 6) Universal forwarders. Always test in staging first. Back up etc/ before upgrading."},
            {"q": "How do I configure index replication in a cluster?",
             "a": "Set replication_factor and search_factor on the cluster manager in server.conf: [clustering] mode=manager, replication_factor=3, search_factor=2. Peers must have sufficient disk for the replication factor."},
        ],
    },
}

# ---------------------------------------------------------------------------
# Interaction analysis patterns
# ---------------------------------------------------------------------------

_QUALITY_INDICATORS = {
    "positive": ["thanks", "helpful", "great", "perfect", "worked", "solved", "correct"],
    "negative": ["wrong", "incorrect", "not helpful", "didn't work", "error", "failed", "bad"],
    "clarification": ["what do you mean", "can you explain", "unclear", "confused", "don't understand"],
    "followup": ["also", "additionally", "another question", "what about", "how about"],
}

# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def review_interactions(interactions: str) -> str:
    """
    Review past interactions for improvement opportunities.

    Args:
        interactions: JSON string of interaction records or description.

    Returns:
        JSON string with review analysis.
    """
    if not interactions or not interactions.strip():
        return json.dumps({"status": "error", "error": "Interactions data cannot be empty"})

    # Try to parse as JSON
    records = []
    try:
        parsed = json.loads(interactions)
        if isinstance(parsed, list):
            records = parsed
        elif isinstance(parsed, dict):
            records = [parsed]
    except (json.JSONDecodeError, TypeError):
        # Treat as text description
        pass

    # Analyze interaction patterns
    analysis = {
        "total_interactions": len(records) if records else "unknown",
        "quality_signals": {"positive": 0, "negative": 0, "clarification": 0, "followup": 0},
        "improvement_areas": [],
        "strengths": [],
    }

    text_to_analyze = interactions.lower()

    for category, keywords in _QUALITY_INDICATORS.items():
        count = sum(1 for kw in keywords if kw in text_to_analyze)
        analysis["quality_signals"][category] = count

    # Identify improvement areas
    if analysis["quality_signals"]["negative"] > 0:
        analysis["improvement_areas"].append({
            "area": "accuracy",
            "description": "Negative feedback detected — review response accuracy",
            "action": "Cross-reference responses with documentation sources",
        })
    if analysis["quality_signals"]["clarification"] > 0:
        analysis["improvement_areas"].append({
            "area": "clarity",
            "description": "Clarification requests indicate unclear responses",
            "action": "Improve response structure with examples and step-by-step explanations",
        })
    if analysis["quality_signals"]["followup"] > 0:
        analysis["improvement_areas"].append({
            "area": "completeness",
            "description": "Follow-up questions suggest incomplete initial responses",
            "action": "Anticipate related questions and include relevant context proactively",
        })

    # Identify strengths
    if analysis["quality_signals"]["positive"] > 0:
        analysis["strengths"].append({
            "area": "helpfulness",
            "description": "Positive feedback indicates helpful responses",
        })

    # General recommendations
    analysis["recommendations"] = [
        "Track confidence scores across response categories to identify weak areas",
        "Build a feedback loop to capture user satisfaction signals",
        "Create targeted training data for topics with low confidence",
        "Review responses that required clarification for pattern improvements",
    ]

    return json.dumps({"status": "ok", **analysis}, indent=2)


def identify_gaps(responses: str) -> str:
    """
    Identify knowledge gaps based on response patterns.

    Args:
        responses: JSON string of response records or description.

    Returns:
        JSON string with identified knowledge gaps.
    """
    if not responses or not responses.strip():
        return json.dumps({"status": "error", "error": "Responses data cannot be empty"})

    # Try to parse as JSON
    records = []
    try:
        parsed = json.loads(responses)
        if isinstance(parsed, list):
            records = parsed
        elif isinstance(parsed, dict):
            records = [parsed]
    except (json.JSONDecodeError, TypeError):
        pass

    text_to_analyze = responses.lower()
    gaps = []

    # Check for topic coverage gaps
    topic_keywords = {
        "spl_optimization": ["optimize", "slow search", "performance", "tstats"],
        "security_detection": ["threat", "detection", "mitre", "attack", "security"],
        "data_models": ["cim", "data model", "normalization", "field mapping"],
        "cribl_pipelines": ["cribl", "pipeline", "routing", "stream"],
        "troubleshooting": ["troubleshoot", "diagnose", "error", "issue"],
        "deployment": ["deploy", "config", "upgrade", "cluster"],
        "dashboard_building": ["dashboard", "report", "visualization", "panel"],
        "index_management": ["index", "retention", "bucket", "storage"],
    }

    covered_topics = []
    uncovered_topics = []
    for topic, keywords in topic_keywords.items():
        if any(kw in text_to_analyze for kw in keywords):
            covered_topics.append(topic)
        else:
            uncovered_topics.append(topic)

    # Identify specific gap patterns
    if "don't know" in text_to_analyze or "not sure" in text_to_analyze or "unable" in text_to_analyze:
        gaps.append({
            "type": "explicit_uncertainty",
            "description": "Explicit uncertainty markers found in responses",
            "action": "Research and document the uncertain topics",
        })

    if "fallback" in text_to_analyze or "generic" in text_to_analyze or "default" in text_to_analyze:
        gaps.append({
            "type": "fallback_responses",
            "description": "Fallback/generic responses indicate missing specific knowledge",
            "action": "Add domain-specific training data for affected topics",
        })

    # Analyze confidence patterns from records
    low_confidence_topics = []
    if records:
        for record in records:
            confidence = record.get("confidence", 1.0)
            topic = record.get("topic", record.get("intent", "unknown"))
            if isinstance(confidence, (int, float)) and confidence < 0.6:
                low_confidence_topics.append({"topic": topic, "confidence": confidence})

    if low_confidence_topics:
        gaps.append({
            "type": "low_confidence",
            "description": f"Found {len(low_confidence_topics)} responses with confidence below 0.6",
            "topics": low_confidence_topics[:10],
            "action": "Generate targeted training data for low-confidence topics",
        })

    # Coverage analysis
    coverage_pct = round((len(covered_topics) / len(topic_keywords)) * 100, 1) if topic_keywords else 0

    return json.dumps({
        "status": "ok",
        "coverage_percentage": coverage_pct,
        "covered_topics": covered_topics,
        "uncovered_topics": uncovered_topics,
        "gaps": gaps,
        "gap_count": len(gaps),
        "recommendations": [
            f"Focus on uncovered topics: {', '.join(uncovered_topics[:5])}" if uncovered_topics else "All topics covered",
            "Create at least 5 Q&A pairs per uncovered topic",
            "Review and update existing training data quarterly",
            "Use real user questions to generate authentic training pairs",
        ],
    }, indent=2)


def generate_training(topic: str, count: Optional[int] = None) -> str:
    """
    Generate training Q&A pairs from existing knowledge.

    Args:
        topic: Topic area to generate training pairs for.
        count: Number of pairs to generate.

    Returns:
        JSON string with training Q&A pairs.
    """
    if not topic or not topic.strip():
        return json.dumps({"status": "error", "error": "Topic cannot be empty"})

    topic_key = topic.strip().lower().replace(" ", "_")
    num_pairs = min(count or 5, 20)

    # Direct match
    topic_data = _TOPIC_CATALOG.get(topic_key)

    # Fuzzy match
    if not topic_data:
        for key, data in _TOPIC_CATALOG.items():
            if topic_key in key or any(word in key for word in topic_key.split("_")):
                topic_data = data
                topic_key = key
                break

    if not topic_data:
        return json.dumps({
            "status": "error",
            "error": f"Unknown topic: {topic}",
            "available_topics": list(_TOPIC_CATALOG.keys()),
        })

    seed_pairs = topic_data["seed_pairs"]
    training_pairs = seed_pairs[:num_pairs]

    # Generate additional pairs by creating variations if needed
    if len(training_pairs) < num_pairs:
        for pair in seed_pairs:
            if len(training_pairs) >= num_pairs:
                break
            # Create a variation
            variation = {
                "q": f"Explain: {pair['q'].rstrip('?').lower()}",
                "a": pair["a"],
                "is_variation": True,
            }
            training_pairs.append(variation)

    return json.dumps({
        "status": "ok",
        "topic": topic_key,
        "description": topic_data["description"],
        "pairs_generated": len(training_pairs),
        "training_pairs": training_pairs,
        "usage_notes": [
            "Review and validate each Q&A pair before using as training data",
            "Add environment-specific context to answers where applicable",
            "Use these pairs for fine-tuning, RAG knowledge base, or evaluation",
            "Regularly refresh training data with new questions from user interactions",
        ],
    }, indent=2)


def measure_improvement(metrics: str) -> str:
    """
    Measure improvement trends over time.

    Args:
        metrics: JSON string of historical metrics or description.

    Returns:
        JSON string with improvement analysis.
    """
    if not metrics or not metrics.strip():
        return json.dumps({"status": "error", "error": "Metrics data cannot be empty"})

    # Try to parse as JSON
    records = []
    try:
        parsed = json.loads(metrics)
        if isinstance(parsed, list):
            records = parsed
        elif isinstance(parsed, dict):
            records = [parsed]
    except (json.JSONDecodeError, TypeError):
        pass

    # Analyze metrics if available
    trends = {
        "confidence_trend": "unknown",
        "accuracy_trend": "unknown",
        "coverage_trend": "unknown",
        "response_time_trend": "unknown",
    }

    if records and len(records) >= 2:
        # Look for confidence scores
        confidences = [r.get("confidence", r.get("avg_confidence")) for r in records
                       if r.get("confidence") is not None or r.get("avg_confidence") is not None]
        if len(confidences) >= 2:
            first_half = sum(confidences[:len(confidences)//2]) / max(len(confidences)//2, 1)
            second_half = sum(confidences[len(confidences)//2:]) / max(len(confidences) - len(confidences)//2, 1)
            if second_half > first_half * 1.05:
                trends["confidence_trend"] = "improving"
            elif second_half < first_half * 0.95:
                trends["confidence_trend"] = "declining"
            else:
                trends["confidence_trend"] = "stable"

        # Look for accuracy scores
        accuracies = [r.get("accuracy", r.get("success_rate")) for r in records
                      if r.get("accuracy") is not None or r.get("success_rate") is not None]
        if len(accuracies) >= 2:
            first_half = sum(accuracies[:len(accuracies)//2]) / max(len(accuracies)//2, 1)
            second_half = sum(accuracies[len(accuracies)//2:]) / max(len(accuracies) - len(accuracies)//2, 1)
            if second_half > first_half * 1.05:
                trends["accuracy_trend"] = "improving"
            elif second_half < first_half * 0.95:
                trends["accuracy_trend"] = "declining"
            else:
                trends["accuracy_trend"] = "stable"

    # Determine overall trajectory
    trend_values = {"improving": 1, "stable": 0, "declining": -1, "unknown": 0}
    known_trends = [v for k, v in trends.items() if v != "unknown"]
    if known_trends:
        avg_trend = sum(trend_values.get(t, 0) for t in known_trends) / len(known_trends)
        if avg_trend > 0.3:
            overall = "improving"
        elif avg_trend < -0.3:
            overall = "declining"
        else:
            overall = "stable"
    else:
        overall = "insufficient_data"

    return json.dumps({
        "status": "ok",
        "overall_trajectory": overall,
        "trends": trends,
        "data_points_analyzed": len(records),
        "recommendations": [
            "Collect at least 30 data points for statistically meaningful trends",
            "Track metrics weekly for consistent comparison",
            "Focus improvement efforts on declining metrics",
            "Set target thresholds: confidence > 0.8, accuracy > 0.9",
            "Use A/B testing when implementing knowledge improvements",
        ],
        "suggested_metrics_to_track": [
            {"name": "avg_confidence", "description": "Average confidence score per response"},
            {"name": "accuracy", "description": "Percentage of correct/helpful responses"},
            {"name": "coverage", "description": "Percentage of topics with adequate training data"},
            {"name": "response_time", "description": "Average time to generate a response"},
            {"name": "user_satisfaction", "description": "User satisfaction score (1-5)"},
            {"name": "clarification_rate", "description": "Percentage of responses requiring follow-up clarification"},
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("self_learner skill cleaned up")
