"""
Profile-Based Retrieval Strategies and Prompts

Seven profiles optimized for different use cases:
1. general - Balanced, auto-detecting assistant
2. spl_expert - SPL query specialist (command docs-first)
3. config_helper - Configuration assistant (specs-first)
4. troubleshooter - Troubleshooting specialist (docs-first)
5. org_expert - Organization config expert (repo-first)
6. cribl_expert - Cribl Stream/Edge data pipeline specialist
7. observability_expert - Full-stack observability engineer
"""

import os
import logging
from typing import Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _org_replace(text: str) -> str:
    """Replace {ORG_NAME} and {ORG_FULL_NAME} placeholders with configured org name."""
    try:
        from chat_app.settings import get_settings
        s = get_settings()
        org, org_full = s.app.org_name, s.app.org_full_name
    except Exception as _exc:  # broad catch — resilience against all failures
        org = os.getenv("ORG_NAME", "MY_ORG")
        org_full = os.getenv("ORG_FULL_NAME", "My Organization")
    text = text.replace("{ORG_NAME}", org).replace("{ORG_FULL_NAME}", org_full)
    return text


@dataclass
class RetrievalStrategy:
    """Defines how to retrieve and weight context for a profile"""
    weight_map: Dict[str, int]
    fetch_multipliers: Dict[str, float]
    top_n_per_collection: int
    keep_per_collection: int
    description: str


# =============================================================================
# Profile Definitions
# =============================================================================

PROFILES = {
    "org_expert": RetrievalStrategy(
        weight_map={
            "feedback_qa": 1,            # MINIMAL - only use for high-confidence matches
            "org_repo_mxbai": 50,        # HIGHEST - your actual configs
            "spl_commands_mxbai": 2,     # Low - not primary focus
            "local_docs_mxbai": 3,       # Low - supplementary
            "secondary_specs": 2,        # Low - supplementary
            "primary": 1,
        },
        fetch_multipliers={
            "org_repo_mxbai": 4.0,       # Heavy fetch from repo
            "feedback_qa": 1.0,          # Minimal fetch from feedback
        },
        top_n_per_collection=30,
        keep_per_collection=20,
        description="Organization expert - HEAVILY relies on repo configs"
    ),

    "spl_expert": RetrievalStrategy(
        weight_map={
            "feedback_qa": 1,            # MINIMAL - only use for high-confidence matches
            "spl_commands_mxbai": 50,    # HIGHEST - SPL command docs
            "org_repo_mxbai": 5,         # Low - supplementary
            "secondary_specs": 3,        # Low
            "local_docs_mxbai": 2,       # Low
            "primary": 1,
        },
        fetch_multipliers={
            "spl_commands_mxbai": 4.0,   # Heavy fetch from commands
            "feedback_qa": 1.0,          # Minimal fetch from feedback
        },
        top_n_per_collection=30,
        keep_per_collection=20,
        description="SPL expert - HEAVILY relies on command documentation"
    ),

    "troubleshooter": RetrievalStrategy(
        weight_map={
            "feedback_qa": 2,            # LOW - only high-confidence past solutions
            "local_docs_mxbai": 40,      # HEAVY - troubleshooting docs
            "org_repo_mxbai": 10,        # Medium - context
            "spl_commands_mxbai": 5,     # Low
            "secondary_specs": 3,        # Low
            "primary": 2,
        },
        fetch_multipliers={
            "local_docs_mxbai": 4.0,     # Heavy fetch from local docs
            "feedback_qa": 1.0,          # Minimal fetch from feedback
        },
        top_n_per_collection=25,
        keep_per_collection=15,
        description="Troubleshooter - HEAVILY relies on documentation"
    ),

    "config_helper": RetrievalStrategy(
        weight_map={
            "feedback_qa": 1,            # MINIMAL - only use for high-confidence matches
            "secondary_specs": 40,       # HEAVY - spec files
            "org_repo_mxbai": 30,        # HEAVY - repo examples
            "spl_commands_mxbai": 5,     # Low
            "local_docs_mxbai": 3,       # Low
            "primary": 2,
        },
        fetch_multipliers={
            "secondary_specs": 3.0,      # Heavy fetch from specs
            "org_repo_mxbai": 3.0,       # Heavy fetch from repo
            "feedback_qa": 1.0,          # Minimal fetch from feedback
        },
        top_n_per_collection=25,
        keep_per_collection=15,
        description="Config helper - HEAVILY relies on specs and repo examples"
    ),

    "cribl_expert": RetrievalStrategy(
        weight_map={
            "feedback_qa": 1,
            "cribl_docs_mxbai": 50,      # HIGHEST - Cribl documentation
            "local_docs_mxbai": 10,       # Medium - supplementary docs
            "org_repo_mxbai": 8,          # Medium - org pipeline configs
            "spl_commands_mxbai": 3,      # Low - SPL reference
            "secondary_specs": 2,         # Low
            "primary": 1,
        },
        fetch_multipliers={
            "cribl_docs_mxbai": 4.0,
            "local_docs_mxbai": 2.0,
            "feedback_qa": 1.0,
        },
        top_n_per_collection=25,
        keep_per_collection=15,
        description="Cribl expert - HEAVILY relies on Cribl Stream/Edge documentation"
    ),

    "observability_expert": RetrievalStrategy(
        weight_map={
            "feedback_qa": 1,
            "spl_commands_mxbai": 30,     # HIGH - mstats, mcatalog, metrics commands
            "local_docs_mxbai": 25,       # HIGH - observability docs
            "cribl_docs_mxbai": 15,       # MEDIUM - Cribl for data routing
            "org_repo_mxbai": 10,         # Medium - org metrics configs
            "secondary_specs": 5,         # Low
            "primary": 2,
        },
        fetch_multipliers={
            "spl_commands_mxbai": 3.0,
            "local_docs_mxbai": 3.0,
            "cribl_docs_mxbai": 2.0,
            "feedback_qa": 1.0,
        },
        top_n_per_collection=25,
        keep_per_collection=15,
        description="Observability expert - metrics, traces, OpenTelemetry, monitoring"
    ),

    "general": RetrievalStrategy(
        weight_map={
            "feedback_qa": 1,            # MINIMAL - only use for high-confidence matches
            "org_repo_mxbai": 20,        # HIGH - repo configs
            "local_docs_mxbai": 20,      # HIGH - local docs
            "spl_commands_mxbai": 15,    # MEDIUM - commands
            "secondary_specs": 15,       # MEDIUM - specs
            "primary": 5,
        },
        fetch_multipliers={
            "org_repo_mxbai": 2.0,
            "local_docs_mxbai": 2.0,
            "feedback_qa": 1.0,          # Minimal fetch from feedback
            "spl_commands_mxbai": 1.5,
            "secondary_specs": 1.5,
        },
        top_n_per_collection=20,
        keep_per_collection=12,
        description="General - balanced across repo, docs, commands and specs"
    ),
}


def get_active_profile() -> str:
    """Get active profile from environment or default to general"""
    profile = os.getenv("ACTIVE_PROFILE", "general").lower()
    if profile not in PROFILES:
        logger.warning(f"Unknown profile '{profile}', defaulting to general")
        return "general"
    return profile


def get_retrieval_strategy(profile: str = None) -> RetrievalStrategy:
    """Get retrieval strategy for a profile"""
    if profile is None:
        profile = get_active_profile()

    if profile not in PROFILES:
        logger.warning(f"Unknown profile '{profile}', using org_expert")
        profile = "org_expert"

    strategy = PROFILES[profile]
    logger.info(f"Using profile: {profile} - {strategy.description}")
    return strategy


def get_fetch_count(strategy: RetrievalStrategy, collection_name: str) -> int:
    """Calculate fetch count for a collection based on strategy"""
    base_count = strategy.top_n_per_collection
    multiplier = strategy.fetch_multipliers.get(collection_name, 1.0)
    return int(base_count * multiplier)


# =============================================================================
# Profile-Specific Prompts
# =============================================================================

ORG_EXPERT_PROMPT = """
You're {ORG_NAME}'s Splunk configuration specialist - you know their deployment inside and out.

## What Makes You Special
You have COMPLETE KNOWLEDGE of {ORG_NAME}'s Splunk environment:
- Every app in UIs/, TAs/, IAs/, BAs/, Scripts/
- Every saved search, alert, and dashboard
- All custom configurations and why they're set that way
- The history behind configuration decisions

## Your Primary Job
Answer questions about {ORG_NAME}'s ACTUAL configurations, not generic Splunk concepts.

## How to Answer

1. **Start with the specific config** from their repo:
   - "In your org-search app (UIs/org-search/local/savedsearches.conf)..."
   - "Your TA-nmap technical add-on has an inputs.conf that..."

2. **Explain what it does** in {ORG_NAME}'s environment:
   - "This search monitors your production firewall logs every 5 minutes..."
   - "This input collects Nmap scan results from your scanning servers..."

3. **Connect related configs** when relevant:
   - "This search references the 'critical_assets' lookup defined in BA-assets..."
   - "Similar patterns are used in your org-network app for network monitoring..."

4. **Suggest improvements** based on what you see:
   - "You could optimize this by using tstats instead of stats..."
   - "Your other searches use earliest=-1h, consider standardizing..."

## Example Response

**User:** "What does my org-search app do?"

**Your Response:**
"Your org-search app (UIs/org-search/) contains 47 saved searches for security monitoring. The main searches are:

- **Error Monitoring**: Runs every 15min, alerts on error spikes (>100/hour)
- **Failed Logins**: Tracks authentication failures across all unit_ids
- **Suspicious Traffic**: Flags unusual network patterns using ML

All searches use tstats with the Network_Traffic and Authentication data models for performance. They're scheduled during off-peak hours (02:00-05:00 UTC) to minimize search head load."

## Remember
You're not explaining generic Splunk - you're explaining {ORG_NAME}'s SPECIFIC Splunk deployment. Be detailed, be specific, and show you understand their environment.
"""

TROUBLESHOOTER_PROMPT = """
You are a **Splunk Troubleshooting Specialist** for {ORG_NAME} ({ORG_FULL_NAME}).

## Your Expertise
You diagnose and solve Splunk problems:
- Data ingestion issues (missing data, parsing errors)
- Search performance problems (slow queries, memory issues)
- Indexer/search head errors
- Configuration conflicts
- Permission and access issues

## Troubleshooting Approach
1. **Identify symptoms** from the user's description
2. **Check common causes** first (permissions, connections, configs)
3. **Provide diagnostic commands** to gather info
4. **Suggest fixes** with specific steps
5. **Explain prevention** to avoid future issues

## CRITICAL: What You Do NOT Do
- **NEVER prepend |rest commands to user queries** - |rest is for server diagnostics only
- **NEVER modify user's SPL** with |rest /services/server/info - that's unrelated to their query
- If user asks to "improve" or "optimize" a query, ONLY optimize the query itself
- |rest commands are SEPARATE diagnostic tools, not query modifications

## Response Pattern
```
**Problem Identified**: [What's wrong]

**Common Causes**:
1. [Most likely cause]
2. [Second likely cause]
3. [Less common cause]

**Diagnostic Commands** (SEPARATE from user's query - run independently):
index=_internal sourcetype=splunkd ERROR | head 20
# Or for server info (run separately):
# | rest /services/server/info

**Solution**:
1. [Step-by-step fix]
2. [Verification]

**Prevention**:
[How to avoid this in future]
```

## Key Resources
- Past troubleshooting examples from feedback_qa
- Troubleshooting guides from local_docs_mxbai
- Organization configs for environment context
- Error messages and their meanings

## What Makes You Different
- Focus on SOLVING problems, not just explaining
- Provide actionable diagnostic commands
- Reference similar past issues from feedback
- Consider {ORG_NAME}'s specific environment
"""

CONFIG_HELPER_PROMPT = """
You are a **Splunk Configuration Assistant**.

## Your Expertise
You guide users on Splunk configuration files:
- .conf file syntax and options (from .spec files)
- SPL command usage and parameters
- Best practices for configuration
- Stanza structure and requirements

## Primary Focus
**Official Splunk documentation is your primary source**.

When answering:
1. **Start with official .spec files** for authoritative syntax
2. **Reference SPL command documentation** for search commands
3. **Show examples from org configs** when relevant
4. **Explain options, defaults, and requirements** clearly

## Response Pattern
```
From [file.conf.spec]:

[setting_name] = <value>
* [Description from spec]
* Default: [value]
* Required: [yes/no]

Example configuration:
[stanza_name]
setting_name = value
...

SPL Command Usage:
| command [options]
* [Description]
* Parameters: [list]
```

## What Makes You Different
- Authoritative reference to official documentation
- Comprehensive coverage of all options
- Clear explanation of syntax and requirements
- Examples from both docs and org configs
"""

SPL_EXPERT_PROMPT = """
You are an **SPL (Search Processing Language) Expert** for {ORG_NAME} ({ORG_FULL_NAME}).

## Your Expertise
You are a master of Splunk's search language:
- 173 official SPL commands and their usage
- Query optimization and performance
- CIM (Common Information Model) compliance
- tstats and data model acceleration
- Complex transforming and streaming commands

## Primary Focus
**SPL command mastery and query optimization**.

When answering:
1. **Start with SPL command syntax** from official docs
2. **Show optimized query patterns** (tstats over stats, etc.)
3. **Reference real queries** from org repo when available
4. **Explain performance implications**

## Response Pattern
```
**SPL Command**: command_name

**Syntax**:
| command_name [required_options] [optional_options]

**Parameters**:
- param1: [description]
- param2: [description]

**Example Query**:
```spl
index=main sourcetype=access
| stats count by status
| where count > 100
```

**Performance Tips**:
- [Optimization 1]
- [Optimization 2]

**Your Organization's Usage**:
[Examples from repo if available]
```

## Key Principles
1. **Search early, filter early** - limit data before transforming
2. **Use tstats** when possible for speed
3. **Avoid joins** - use stats instead
4. **Streaming before transforming** - understand command order
5. **CIM compliance** - use standard field names

## What Makes You Different
- Deep SPL command knowledge
- Performance optimization focus
- Real examples from your saved searches
- Best practices and anti-patterns
"""


CRIBL_EXPERT_PROMPT = """
You are a **Cribl Stream/Edge Expert** and Data Pipeline Architect.

## Your Expertise
You are a master of Cribl's data routing and transformation platform:
- **Cribl Stream**: Pipeline configuration, routes, packs, functions
- **Cribl Edge**: Agent deployment, fleet management, data collection
- **Cribl Search**: Federated search across data stores
- **Cribl Lake**: Data lake management, storage tiering
- Data routing: Sources (inputs), destinations (outputs), routing rules
- Pipeline functions: Regex, eval, lookup, aggregation, sampling, masking, encryption
- Pack management: Creating, deploying, sharing pipeline packs
- Performance: Worker groups, load balancing, backpressure handling

## Key Concepts You Know
- **Routes**: Filter expressions that match events to pipelines
- **Pipelines**: Ordered chains of functions that transform data
- **Functions**: Individual processing steps (regex_extract, eval, lookup, etc.)
- **Sources & Destinations**: S3, Splunk, Kafka, Kinesis, syslog, HTTP, etc.
- **Worker Groups**: Scaling and isolating processing workloads
- **Packs**: Reusable pipeline packages for common use cases

## Response Pattern
1. **Understand the data flow** - what's coming in, what needs to go out
2. **Recommend the right approach** - route, pipeline, pack, or function
3. **Provide configuration** - YAML/JSON snippets with explanations
4. **Highlight performance considerations** - volume, latency, resource usage
5. **Suggest best practices** - naming conventions, testing, monitoring

## Integration with Splunk
- Data reduction before Splunk (reduce license costs)
- Event breaking and parsing in Cribl vs. Splunk
- Routing data to both Splunk and S3/data lake
- Converting Splunk HEC to Cribl HTTP source
- Migrating Splunk heavy forwarders to Cribl Edge
"""

OBSERVABILITY_EXPERT_PROMPT = """
You are a **Senior Observability & Platform Engineer** specializing in full-stack observability.

## Your Expertise
- **Metrics**: Splunk Metrics (mstats, mcatalog, mpreview), Prometheus, OpenMetrics
- **Traces**: Distributed tracing, OpenTelemetry, APM, service maps
- **Logs**: Log routing, aggregation, structured logging, log-to-metrics conversion
- **SLI/SLO/SLA**: Service level indicators, error budgets, availability monitoring
- **Infrastructure**: Kubernetes, cloud (AWS/Azure/GCP), containers, serverless monitoring
- **Data Pipeline**: OpenTelemetry Collector, Cribl Stream, Splunk Connect for Kubernetes

## Key Commands You Master
### Metrics (Splunk)
- `mstats` — Aggregate metrics data (avg, sum, count, percentile, etc.)
- `mcatalog` — Discover available metrics and dimensions
- `mpreview` — Preview metric data before ingestion
- `mcollect` / `meventcollect` — Write data to metrics indexes

### Observability Patterns
- **RED Method**: Rate, Errors, Duration for services
- **USE Method**: Utilization, Saturation, Errors for resources
- **Four Golden Signals**: Latency, Traffic, Errors, Saturation
- **SLI-based alerting**: Alert on error budget burn rate, not thresholds

## Response Pattern
1. **Identify the observability pillar** (metrics, traces, logs, or all three)
2. **Recommend the right approach** (SPL for Splunk, PromQL for Prometheus, etc.)
3. **Provide queries and configurations** with performance notes
4. **Connect the dots** between metrics, traces, and logs
5. **Suggest monitoring best practices** and dashboard layouts

## OpenTelemetry Integration
- OTLP ingestion into Splunk via HEC or OTEL Collector
- Trace-to-log correlation using trace_id/span_id
- Metric conversion from OTel to Splunk metrics format
- Cribl Stream as an OTLP-compatible pipeline processor
"""

PROFILE_PROMPTS = {
    "org_expert": ORG_EXPERT_PROMPT,
    "troubleshooter": TROUBLESHOOTER_PROMPT,
    "config_helper": CONFIG_HELPER_PROMPT,
    "spl_expert": SPL_EXPERT_PROMPT,
    "cribl_expert": CRIBL_EXPERT_PROMPT,
    "observability_expert": OBSERVABILITY_EXPERT_PROMPT,
}


def get_profile_prompt(profile: str = None) -> str:
    """Get the system prompt for a profile, with org name substitution."""
    if profile is None:
        profile = get_active_profile()

    if profile not in PROFILE_PROMPTS:
        logger.warning(f"Unknown profile '{profile}', using org_expert prompt")
        profile = "org_expert"

    return _org_replace(PROFILE_PROMPTS[profile])


def get_profile_info() -> Dict:
    """Get information about all available profiles"""
    return {
        name: {
            "description": strategy.description,
            "weight_map": strategy.weight_map,
            "fetch_multipliers": strategy.fetch_multipliers,
        }
        for name, strategy in PROFILES.items()
    }


# =============================================================================
# Profile Selection Helpers
# =============================================================================

def detect_profile_from_query(query: str, memory_chunks: list = None) -> str:
    """
    Auto-detect which profile to use based on query keywords and retrieved chunks.

    Enhanced detection for org_expert:
    - Detects repo-specific file queries (inputs.conf from repo, my inputs.conf)
    - Detects app name patterns (org-search, TA-nmap, etc.)
    - Checks if retrieved chunks are mostly from org_repo
    - Looks for org-specific indicators
    - Defaults to org_expert for ambiguous .conf queries

    Returns profile name or None if no clear match.
    """
    import re

    query_lower = query.lower()

    # PRIORITY 1: Repo-specific file queries (HIGHEST PRIORITY)
    repo_file_patterns = [
        # Possessive patterns
        r'(my|our)\s+(inputs|outputs|props|transforms|savedsearches|indexes|macros|lookups?)\.conf',
        r'(inputs|outputs|props|transforms|savedsearches|indexes|macros|lookups?)\.conf\s+(from|in)\s+(repo|my|our)',

        # Show/explain patterns
        r'show\s+(me\s+)?(my|our|repo|all)\s+\w+\.conf',
        r'explain\s+(my|our|repo|the)\s+\w+\.conf',
        r'list\s+(my|our|all)\s+\w+\.conf',
        r'what\s+(is|are)\s+(in|on)\s+(my|our)\s+\w+\.conf',

        # Stanza patterns (expanded)
        r'(inputs|outputs|props|transforms|savedsearches|indexes|macros)\s+stanzas?\s+(in|from|for)\s+(app|application)',
        r'(in|from)\s+(app|application):\s*[\w-]+',
        r'what\s+\w+\s+stanzas?\s+(are|exist|in|from)',
        r'list\s+(all\s+)?\w+\s+stanzas?',
        r'show\s+(me\s+)?(\w+\s+)?stanzas?',

        # Config file queries
        r'(what|which)\s+\w+\s+(are\s+)?configured',
        r'(what|which)\s+apps?\s+(have|use|contain)',
        r'config(uration)?\s+(for|in|of)\s+\w+',
    ]

    for pattern in repo_file_patterns:
        if re.search(pattern, query_lower):
            logger.info(f"[PROFILE_DETECT] Detected repo file query: {pattern}")
            return "org_expert"

    # PRIORITY 2: Org-specific app name patterns (expanded)
    org_app_patterns = [
        r'\b(ta|ia|ba|sa|da)-\w+',  # TAs, IAs, BAs, etc.
        r'\b(ui|ta|addon)-',             # Generic UI/TA patterns
        r'/(uis|tas|bas|ias|scripts)/',  # Path-based detection
        r'app:\s*[\w-]+',                # NEW: "app: abc" or "app:xyz"
        r'application:\s*[\w-]+',        # NEW: "application: abc"
    ]

    for pattern in org_app_patterns:
        if re.search(pattern, query_lower):
            logger.info(f"[PROFILE_DETECT] Detected org app pattern: {pattern}")
            return "org_expert"

    # PRIORITY 3: Org indicators (expanded for natural queries)
    org_indicators = [
        # Possessive
        'my ', 'our ', 'my\n', 'our\n',

        # Saved searches
        'this search', 'this saved search', 'saved search', 'savedsearches',

        # Repo/deployment
        'deployment', 'environment', 'repo', 'repository',
        'from repo', 'in repo', 'from my', 'from our',

        # Action verbs with possessive
        'show me my', 'show my', 'show me our', 'show our',
        'explain my', 'explain our', 'explain the',
        'list my', 'list our', 'list all',
        'what is my', 'what are my', 'what is our', 'what are our',
        'which apps', 'what apps',

        # Configuration context
        'configuration', 'configured', 'configs',
        'in my environment', 'in our environment',
        'we have', 'we use', 'i have',
        'doing in my', 'doing in our',  # NEW: "what is X doing in my configs"
    ]

    # PRIORITY 3.5: Check for specific stanza references
    # If query mentions a stanza pattern (monitor://, WinEventLog://, etc.), assume org query
    stanza_patterns = [
        r'monitor://',
        r'wineventlog://',
        r'script://',
        r'tcp://',
        r'udp://',
        r'batch://',
        r'\[[^\]]*://[^\]]+\]',  # Stanza with protocol like [monitor://var/log]
    ]

    for pattern in stanza_patterns:
        if re.search(pattern, query_lower):
            logger.info(f"[PROFILE_DETECT] Detected stanza reference in query: {pattern}")
            return "org_expert"

    if any(ind in query_lower for ind in org_indicators):
        logger.info("[PROFILE_DETECT] Detected org indicator in query")
        return "org_expert"

    # Check retrieved chunks - if >50% from org_repo, use org_expert
    if memory_chunks:
        org_count = sum(1 for c in memory_chunks
                       if 'org_repo' in str(c.get('collection', '')))
        total = len(memory_chunks)
        if total > 0 and org_count / total > 0.5:
            logger.info(f"[PROFILE_DETECT] Detected org-focused retrieval: {org_count}/{total} chunks from org_repo")
            return "org_expert"

    # PRIORITY 3.7: Cribl indicators
    cribl_keywords = {
        "cribl", "cribl stream", "cribl edge", "cribl search", "cribl lake",
        "pipeline", "route", "pack", "worker group",
        "data routing", "data reduction", "event breaker",
    }
    # Only match "pipeline" and "route" when in Cribl context
    if any(kw in query_lower for kw in cribl_keywords):
        return "cribl_expert"

    # PRIORITY 3.8: Observability indicators
    observability_keywords = {
        "mstats", "mcatalog", "mpreview", "metric index", "metrics",
        "opentelemetry", "otel", "otlp", "trace", "tracing", "span",
        "distributed trace", "apm", "service map",
        "sli", "slo", "error budget", "availability",
        "observability", "o11y", "prometheus", "grafana",
        "red method", "use method", "golden signals",
        "kubernetes monitoring", "k8s monitoring", "container monitoring",
    }
    if any(kw in query_lower for kw in observability_keywords):
        return "observability_expert"

    # Troubleshooting indicators (check after org, as org troubleshooting exists)
    troubleshoot_keywords = {
        "error", "not working", "problem", "issue", "broken", "fix", "debug",
        "troubleshoot", "why", "fails", "failed", "can't", "cannot", "won't",
        "missing data", "no results", "slow"
    }
    if any(kw in query_lower for kw in troubleshoot_keywords):
        return "troubleshooter"

    # SPL expert indicators
    spl_keywords = {
        "how to write", "spl query", "search query", "optimize query",
        "stats command", "eval", "timechart", "tstats", "streamstats",
        "query performance", "search performance"
    }
    if any(kw in query_lower for kw in spl_keywords):
        return "spl_expert"

    # Config helper indicators (generic spec questions)
    config_keywords = {
        "conf syntax", "conf.spec", ".spec file", "configuration options",
        "valid settings", "configuration parameters", "what are the options",
        "what can i", "how do i configure", "parameters for"
    }
    if any(kw in query_lower for kw in config_keywords):
        return "config_helper"

    # PRIORITY 4: Default to org_expert for ambiguous .conf queries
    # If query mentions a .conf file but doesn't ask for generic spec info, assume repo query
    if re.search(r'\w+\.conf(?!\.(spec|example))', query_lower):
        # Check if it's NOT explicitly a generic spec question
        generic_spec_indicators = ['options for', 'syntax of', 'parameters for', 'settings in', 'what are the', 'valid values', 'how do i']
        if not any(ind in query_lower for ind in generic_spec_indicators):
            logger.info("[PROFILE_DETECT] Defaulting to org_expert for .conf file query (not generic spec)")
            return "org_expert"

    # Default: None (use environment setting)
    return None


# Example usage
if __name__ == "__main__":
    # Show all profiles
    print("Available Profiles:")
    print("=" * 80)
    for name, info in get_profile_info().items():
        print(f"\n{name.upper()}")
        print(f"  {info['description']}")
        print(f"  Weights: {info['weight_map']}")
        print(f"  Multipliers: {info['fetch_multipliers']}")

    # Test auto-detection
    print("\n" + "=" * 80)
    print("Auto-Detection Tests:")
    test_queries = [
        "Explain our savedsearches.conf",
        "Why is data missing from my index?",
        "What are the options for inputs.conf?",
        "How do I optimize this stats query?",
    ]
    for q in test_queries:
        profile = detect_profile_from_query(q)
        print(f"  '{q}' → {profile}")
