"""
ObsAI Context Data — App type definitions, pattern dictionaries, and tstats knowledge.

Extracted from obsai_context.py to keep file sizes manageable.
All public names are re-exported from obsai_context.py for backward compatibility.
"""

import re
from dataclasses import dataclass


# =====================================================================
# ORG APP TYPE DEFINITIONS
# =====================================================================

@dataclass(slots=True)
class AppContext:
    """Context information about a Splunk app."""
    app_name: str
    app_type: str  # UI, TA, BA, IA, _general
    category: str  # What kind of app it is
    description: str
    deployment_target: str  # Where it deploys
    typical_contents: list[str]  # What you'd expect to find


# UI Apps - User-facing functionality
UI_APPS = {
    "org-es": AppContext(
        app_name="org-es",
        app_type="UI",
        category="Enterprise Security",
        description="Splunk Enterprise Security - threat detection, incident response, risk analysis",
        deployment_target="Search Heads",
        typical_contents=[
            "Correlation searches for threats",
            "Notable event configurations",
            "Risk scoring rules",
            "Asset/identity lookups",
            "ES dashboards and reports",
        ]
    ),
    "org-dma": AppContext(
        app_name="org-dma",
        app_type="UI",
        category="Data Model Acceleration",
        description="Data model acceleration configs for fast tstats queries",
        deployment_target="Search Heads + Indexers",
        typical_contents=[
            "Accelerated data models",
            "Data model searches",
            "Acceleration settings",
            "Summary indexing configs",
        ]
    ),
    "org-itsi": AppContext(
        app_name="org-itsi",
        app_type="UI",
        category="IT Service Intelligence",
        description="ITSI - service monitoring, KPI tracking, event analytics",
        deployment_target="Search Heads",
        typical_contents=[
            "Service definitions",
            "KPI base searches",
            "Notable event aggregation policies",
            "Glass table configurations",
            "Service dependencies",
        ]
    ),
    "org-mltk": AppContext(
        app_name="org-mltk",
        app_type="UI",
        category="Machine Learning Toolkit",
        description="ML models, experiments, and predictive analytics",
        deployment_target="Search Heads",
        typical_contents=[
            "ML model definitions",
            "Feature extraction searches",
            "Training data queries",
            "Prediction dashboards",
        ]
    ),
    "org-search": AppContext(
        app_name="org-search",
        app_type="UI",
        category="User Facing Search",
        description="Main user-facing search interface and custom dashboards for {ORG_NAME} users",
        deployment_target="Search Heads",
        typical_contents=[
            "User dashboards",
            "Custom searches for business users",
            "Scheduled reports",
            "Alert definitions",
            "Lookup tables for user queries",
        ]
    ),
}

# TA Apps - Technology Add-ons (data ingestion)
TA_APPS = {
    "TA-nmap": AppContext(
        app_name="TA-nmap",
        app_type="TA",
        category="Network Scanning",
        description="Nmap network scanning data ingestion and parsing",
        deployment_target="Heavy Forwarders",
        typical_contents=[
            "Nmap scan ingestion configs (inputs.conf)",
            "Field extractions for nmap XML (props.conf)",
            "CIM mappings for network scans",
            "Lookup generation for discovered hosts",
        ]
    ),
    # Generic TA pattern
    "TA-*": AppContext(
        app_name="TA-*",
        app_type="TA",
        category="Technology Add-on",
        description="Data ingestion and parsing for specific technology/vendor",
        deployment_target="Heavy Forwarders / Indexers",
        typical_contents=[
            "Data inputs configuration (inputs.conf)",
            "Field extractions (props.conf)",
            "Field transformations (transforms.conf)",
            "CIM compliance mappings",
            "Lookup generation scripts",
            "Modular inputs",
        ]
    ),
}

# BA Apps - Base Apps (supporting functionality)
BA_APPS = {
    "BA-*": AppContext(
        app_name="BA-*",
        app_type="BA",
        category="Base App",
        description="Supporting functionality, shared resources, or foundational configs",
        deployment_target="Varies",
        typical_contents=[
            "Shared macros",
            "Common lookup tables",
            "Shared saved searches",
            "Base configurations",
        ]
    ),
}

# IA Apps - Infrastructure Apps
IA_APPS = {
    "IA-*": AppContext(
        app_name="IA-*",
        app_type="IA",
        category="Infrastructure App",
        description="Infrastructure monitoring and management",
        deployment_target="Varies",
        typical_contents=[
            "Infrastructure monitoring searches",
            "System health dashboards",
            "Capacity planning queries",
        ]
    ),
}

# _general - Deployment to all tiers
GENERAL_APPS = {
    "_general": AppContext(
        app_name="_general",
        app_type="_general",
        category="Global Deployment",
        description="Configs deployed to ALL search heads, indexers, and forwarders",
        deployment_target="All Splunk instances (SH + Indexers + Forwarders)",
        typical_contents=[
            "Global indexes.conf settings",
            "Universal forwarder configs",
            "Global props/transforms",
            "Deployment-wide limits",
            "System-level authentication",
        ]
    ),
}

# Combine all app contexts
ALL_APP_CONTEXTS = {
    **UI_APPS,
    **TA_APPS,
    **BA_APPS,
    **IA_APPS,
    **GENERAL_APPS,
}


# =====================================================================
# PATH PATTERN MATCHING
# =====================================================================

# Regex patterns for app type detection
# Supports multiple naming conventions:
#   - /UIs/org-es/, /UIs/org_UI_home/, /UIs/org-search/
#   - /TAs/TA-windows/, /TAs/Splunk_TA_windows/
#   - Underscores or hyphens, mixed case
APP_TYPE_PATTERNS = {
    "UI": re.compile(r'/(?:UIs?|apps?)/([a-zA-Z0-9_-]+)', re.IGNORECASE),
    "TA": re.compile(r'/(?:TAs?|technology_addons?)/([a-zA-Z0-9_-]+)', re.IGNORECASE),
    "BA": re.compile(r'/(?:BAs?|business_apps?)/([a-zA-Z0-9_-]+)', re.IGNORECASE),
    "IA": re.compile(r'/(?:IAs?|input_apps?)/([a-zA-Z0-9_-]+)', re.IGNORECASE),
    "_general": re.compile(r'/_general/', re.IGNORECASE),
}

# Config file type patterns
CONFIG_FILE_TYPES = {
    "savedsearches.conf": "saved searches (scheduled reports, alerts, dashboards)",
    "inputs.conf": "data inputs (monitoring, scripted inputs, network inputs)",
    "props.conf": "field extractions, source type definitions, timestamp parsing",
    "transforms.conf": "field transformations, lookup definitions, regex replacements",
    "macros.conf": "search macros (reusable SPL snippets)",
    "indexes.conf": "index definitions, retention policies, storage settings",
    "outputs.conf": "forwarding destinations, indexer connections",
    "authorize.conf": "role-based access control, capabilities",
    "datamodels.conf": "data model definitions for tstats acceleration",
    "alert_actions.conf": "custom alert actions, webhook configs",
}

# Stanza type patterns
STANZA_TYPE_PATTERNS = {
    r'^\[.*:\s*.*\]$': "macro definition",
    r'^\[WinEventLog://.*\]$': "Windows Event Log input",
    r'^\[monitor://.*\]$': "file/directory monitoring input",
    r'^\[script://.*\]$': "scripted input",
    r'^\[tcp://.*\]$': "TCP network input",
    r'^\[udp://.*\]$': "UDP network input",
    r'^\[.*-too_small\]$': "transforms extraction rule",
    r'^\[.*_lookup\]$': "lookup table definition",
    r'^\[role_.*\]$': "user role definition",
}


# =====================================================================


# TERM() is used in tstats WHERE clause for indexed field acceleration
# TERM() prefix matching works on major/minor breakers

TSTATS_PATTERNS = {
    # Correct tstats patterns
    "tstats_with_term": re.compile(r'\|\s*tstats.*WHERE.*TERM\(', re.IGNORECASE),
    "tstats_basic": re.compile(r'\|\s*tstats\s+', re.IGNORECASE),

    # Indexed fields (use with TERM())
    "indexed_field": re.compile(r'\b(sourcetype|source|host|index|_time|_raw)\b', re.IGNORECASE),
}

# Major breakers (create token boundaries): space, =, (, ), <, >, [, ], {, }, !, ?, @, #, $, %, ^, &, *, +, \
# Minor breakers (searchable but don't split): / : . - _

# TERM() prefix matching rules:
# - TERM(192.168) matches 192.168.1.1, 192.168.2.1, etc.
# - TERM(error) matches error, errors, error_count, etc.
# - TERM(win*) does NOT work - no wildcards in TERM()

INDEXED_TOKEN_KNOWLEDGE = {
    "best_practices": [
        "Use TERM() in tstats WHERE clause for indexed field acceleration",
        "TERM() works with prefix matching on indexed tokens",
        "TERM() respects major breakers (space, =, etc.) but not minor breakers (/, :, ., -, _)",
        "Don't use wildcards in TERM() - use prefix matching instead",
        "sourcetype, source, host, index are always indexed - perfect for TERM()",
        "Custom indexed fields defined in fields.conf can use TERM()",
    ],

    "common_mistakes": [
        "Using TERM() outside tstats WHERE clause (doesn't work)",
        "Using TERM(win*) with wildcards (use TERM(win) for prefix match)",
        "Using TERM() on extracted fields (only works on indexed fields)",
        "Piping search into tstats (tstats must start with |)",
    ],

    "examples": {
        "correct": [
            '| tstats count WHERE index=main TERM(sourcetype=access) by host',
            '| tstats count WHERE TERM(192.168) by source',
            '| tstats count WHERE TERM(error) AND TERM(fatal) by sourcetype',
            '| tstats sum(bytes) WHERE index=web TERM(status=200) by source',
        ],
        "incorrect": [
            'index=main | tstats count by host  # Cannot pipe into tstats',
            '| tstats count WHERE TERM(source*=http)  # No wildcards in TERM()',
            '| tstats count WHERE user=admin  # user is extracted, not indexed',
            'sourcetype=access | stats count  # Should use tstats for performance',
        ],
    },
}

