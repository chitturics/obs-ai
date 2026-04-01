"""
Deployment Manager Skill — Plan deployments, validate bundles, generate
serverclass.conf, and check version compatibility.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known Splunk apps and compatibility data
# ---------------------------------------------------------------------------

_KNOWN_APPS: Dict[str, Dict[str, Any]] = {
    "Splunk_TA_windows": {
        "display_name": "Splunk Add-on for Microsoft Windows",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "8.8.0",
        "type": "add-on",
    },
    "Splunk_TA_linux": {
        "display_name": "Splunk Add-on for Unix and Linux",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "9.0.0",
        "type": "add-on",
    },
    "Splunk_SA_CIM": {
        "display_name": "Splunk Common Information Model",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "5.3.0",
        "type": "supporting_add-on",
    },
    "SplunkEnterpriseSecuritySuite": {
        "display_name": "Splunk Enterprise Security",
        "min_splunk": "9.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "7.3.0",
        "type": "app",
    },
    "splunk_app_for_pci_compliance": {
        "display_name": "Splunk App for PCI Compliance",
        "min_splunk": "8.0.0",
        "max_splunk": "9.2.0",
        "latest_version": "5.3.0",
        "type": "app",
    },
    "Splunk_TA_paloalto": {
        "display_name": "Palo Alto Networks Add-on for Splunk",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "8.0.0",
        "type": "add-on",
    },
    "Splunk_TA_aws": {
        "display_name": "Splunk Add-on for AWS",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "7.5.0",
        "type": "add-on",
    },
    "splunk_app_db_connect": {
        "display_name": "Splunk DB Connect",
        "min_splunk": "8.1.0",
        "max_splunk": "9.2.0",
        "latest_version": "3.16.0",
        "type": "app",
    },
    "Splunk_ML_Toolkit": {
        "display_name": "Splunk Machine Learning Toolkit",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "5.4.0",
        "type": "app",
    },
    "Splunk_TA_fortinet_fortigate": {
        "display_name": "Fortinet FortiGate Add-on for Splunk",
        "min_splunk": "8.0.0",
        "max_splunk": "9.3.0",
        "latest_version": "2.1.0",
        "type": "add-on",
    },
}

# ---------------------------------------------------------------------------
# Required files for deployment bundles
# ---------------------------------------------------------------------------

_REQUIRED_FILES = {
    "app": ["app.conf", "default/app.conf"],
    "add-on": ["app.conf", "default/app.conf"],
    "inputs": ["inputs.conf", "default/inputs.conf"],
    "transforms": ["transforms.conf", "default/transforms.conf"],
    "props": ["props.conf", "default/props.conf"],
}

_CONF_FILE_PATTERNS = [
    "app.conf", "inputs.conf", "outputs.conf", "props.conf", "transforms.conf",
    "server.conf", "web.conf", "limits.conf", "authorize.conf", "authentication.conf",
    "serverclass.conf", "deploymentclient.conf", "savedsearches.conf",
    "macros.conf", "tags.conf", "eventtypes.conf", "collections.conf",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_version(version_str: str) -> tuple:
    """Parse a version string into a tuple of integers."""
    parts = re.findall(r"\d+", version_str)
    return tuple(int(p) for p in parts[:3])


def _version_in_range(version: str, min_ver: str, max_ver: str) -> bool:
    """Check if a version falls within a range."""
    v = _parse_version(version)
    lo = _parse_version(min_ver)
    hi = _parse_version(max_ver)
    return lo <= v <= hi


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def plan_deployment(changes: str, environment: Optional[str] = None) -> str:
    """
    Create a phased deployment plan for configuration changes.

    Args:
        changes: Description of configuration changes.
        environment: Target environment.

    Returns:
        JSON string with deployment plan.
    """
    if not changes or not changes.strip():
        return json.dumps({"status": "error", "error": "Changes description cannot be empty"})

    env = (environment or "production").lower()
    changes_lower = changes.lower()

    # Determine risk level
    high_risk_keywords = ["outputs.conf", "server.conf", "authentication", "ssl",
                          "cluster", "license", "web.conf", "migration", "upgrade"]
    medium_risk_keywords = ["inputs.conf", "props.conf", "transforms.conf", "limits.conf",
                            "savedsearches", "serverclass"]
    low_risk_keywords = ["macros", "tags", "eventtypes", "lookup", "dashboard", "view"]

    risk_level = "low"
    if any(kw in changes_lower for kw in high_risk_keywords):
        risk_level = "high"
    elif any(kw in changes_lower for kw in medium_risk_keywords):
        risk_level = "medium"

    # Build phased plan
    phases = []

    # Phase 1: Preparation
    phases.append({
        "phase": 1,
        "name": "Preparation",
        "steps": [
            "Back up current configuration (etc/system/local and app directories)",
            "Document the current state of affected configurations",
            "Review changes with stakeholders and get approval",
            "Prepare rollback procedure with backup configs",
            "Schedule maintenance window if required",
        ],
        "estimated_time": "30 minutes",
    })

    # Phase 2: Validation
    phases.append({
        "phase": 2,
        "name": "Validation",
        "steps": [
            "Validate configuration syntax with btool check",
            "Test changes in dev/staging environment first",
            "Run btool list to verify config precedence",
            "Check for conf file conflicts across apps",
            "Verify no orphaned stanza references",
        ],
        "estimated_time": "1 hour",
    })

    # Phase 3: Deployment
    if env == "production":
        deploy_steps = [
            "Deploy to a single test node first (canary deployment)",
            "Monitor test node for 15 minutes",
            "If canary is healthy, deploy to remaining nodes in rolling fashion",
            "Restart affected services (splunkd, web) in maintenance window",
            "Verify all nodes come back online",
        ]
    else:
        deploy_steps = [
            f"Deploy configuration changes to {env} environment",
            "Restart affected Splunk services",
            "Verify services come back online",
        ]

    phases.append({
        "phase": 3,
        "name": "Deployment",
        "steps": deploy_steps,
        "estimated_time": "1-2 hours" if env == "production" else "30 minutes",
    })

    # Phase 4: Verification
    phases.append({
        "phase": 4,
        "name": "Verification",
        "steps": [
            "Verify data flow is working (check _internal for errors)",
            "Run test searches to confirm functionality",
            "Check dashboard and report rendering",
            "Monitor system health metrics for 30 minutes",
            "Confirm no increase in error rates",
        ],
        "estimated_time": "1 hour",
    })

    # Rollback plan
    rollback = {
        "trigger_conditions": [
            "Data ingestion drops below normal baseline",
            "Critical errors in splunkd.log after deployment",
            "Services fail to restart",
            "Searches fail with new configuration",
        ],
        "steps": [
            "Stop affected Splunk services",
            "Restore backed-up configuration files",
            "Restart Splunk services",
            "Verify data flow resumes normally",
            "Document the rollback reason for post-mortem",
        ],
    }

    return json.dumps({
        "status": "ok",
        "environment": env,
        "risk_level": risk_level,
        "changes_summary": changes[:200],
        "phases": phases,
        "rollback_plan": rollback,
        "requires_maintenance_window": risk_level in ("high", "medium") and env == "production",
    }, indent=2)


def validate_bundle(bundle_contents: str) -> str:
    """
    Validate a deployment bundle for common issues.

    Args:
        bundle_contents: Description or listing of bundle contents.

    Returns:
        JSON string with validation results.
    """
    if not bundle_contents or not bundle_contents.strip():
        return json.dumps({"status": "error", "error": "Bundle contents cannot be empty"})

    content_lower = bundle_contents.lower()
    issues = []
    warnings = []
    info = []

    # Check for app.conf
    if "app.conf" not in content_lower:
        issues.append({
            "severity": "error",
            "message": "Missing app.conf — every app/add-on must have an app.conf",
            "fix": "Create default/app.conf with [install], [ui], and [launcher] stanzas",
        })

    # Check for default vs local
    if "local/" in content_lower and "default/" not in content_lower:
        warnings.append({
            "severity": "warning",
            "message": "Bundle has local/ but no default/ — best practice is to use default/ for distribution",
            "fix": "Move configurations to default/ directory for deployment; local/ is for user overrides",
        })

    # Check for known conf files
    detected_confs = []
    for conf in _CONF_FILE_PATTERNS:
        if conf in content_lower:
            detected_confs.append(conf)

    # Check for dangerous files
    dangerous_patterns = [
        ("passwd", "Password file detected — should never be in a deployment bundle"),
        (".key", "Private key file detected — use certificate management instead"),
        (".pem", "Certificate file detected — verify it does not contain private keys"),
        ("credentials.conf", "Credentials file detected — secrets should use Splunk credential storage"),
        (".env", "Environment file detected — may contain secrets"),
    ]
    for pattern, message in dangerous_patterns:
        if pattern in content_lower:
            issues.append({"severity": "error", "message": message, "fix": "Remove sensitive files from the bundle"})

    # Check for metadata
    if "metadata/" not in content_lower and "default.meta" not in content_lower:
        warnings.append({
            "severity": "warning",
            "message": "No metadata directory found — objects may not have proper permissions",
            "fix": "Create metadata/default.meta with appropriate export settings",
        })

    # Check for README
    if "readme" not in content_lower:
        info.append({
            "severity": "info",
            "message": "No README file — consider adding documentation",
        })

    # Check for bin/ scripts without correct permissions note
    if "bin/" in content_lower:
        info.append({
            "severity": "info",
            "message": "Bundle contains scripts in bin/ — ensure execute permissions are set",
        })

    # Overall assessment
    if issues:
        validation_status = "failed"
    elif warnings:
        validation_status = "passed_with_warnings"
    else:
        validation_status = "passed"

    return json.dumps({
        "status": "ok",
        "validation_result": validation_status,
        "detected_conf_files": detected_confs,
        "issues": issues,
        "warnings": warnings,
        "info": info,
        "issue_count": len(issues),
        "warning_count": len(warnings),
    }, indent=2)


def generate_serverclass(requirements: str) -> str:
    """
    Generate serverclass.conf from deployment requirements.

    Args:
        requirements: Description of deployment requirements.

    Returns:
        JSON string with serverclass.conf configuration.
    """
    if not requirements or not requirements.strip():
        return json.dumps({"status": "error", "error": "Requirements cannot be empty"})

    req_lower = requirements.lower()
    server_classes = []

    # Detect platform-based deployments
    platform_mappings = {
        "windows": {
            "filter": "Windows",
            "apps": ["Splunk_TA_windows"],
            "whitelist": "*.windows.*",
        },
        "linux": {
            "filter": "Linux",
            "apps": ["Splunk_TA_linux", "Splunk_TA_nix"],
            "whitelist": "*.linux.*",
        },
        "palo": {
            "filter": "PaloAlto",
            "apps": ["Splunk_TA_paloalto"],
            "whitelist": "*.paloalto.*",
        },
        "fortinet": {
            "filter": "Fortinet",
            "apps": ["Splunk_TA_fortinet_fortigate"],
            "whitelist": "*.fortinet.*",
        },
        "aws": {
            "filter": "AWS",
            "apps": ["Splunk_TA_aws"],
            "whitelist": "*.aws.*",
        },
    }

    for platform, mapping in platform_mappings.items():
        if platform in req_lower:
            sc = {
                "name": f"SC_{mapping['filter']}_Servers",
                "filter": mapping["filter"],
                "apps": mapping["apps"],
                "whitelist": mapping["whitelist"],
            }
            server_classes.append(sc)

    # Detect app-specific deployments
    for app_name in _KNOWN_APPS:
        if app_name.lower() in req_lower or _KNOWN_APPS[app_name]["display_name"].lower() in req_lower:
            # Check if already covered by platform mapping
            already_mapped = any(app_name in sc.get("apps", []) for sc in server_classes)
            if not already_mapped:
                server_classes.append({
                    "name": f"SC_{app_name}",
                    "filter": app_name,
                    "apps": [app_name],
                    "whitelist": "*",
                })

    # If no specific matches, create a generic template
    if not server_classes:
        server_classes.append({
            "name": "SC_AllForwarders",
            "filter": "All Forwarders",
            "apps": ["outputs_app", "base_config"],
            "whitelist": "*",
        })

    # Generate serverclass.conf
    conf_lines = ["# serverclass.conf - Auto-generated", "# Place in $SPLUNK_HOME/etc/system/local/", ""]

    for sc in server_classes:
        conf_lines.append(f"[serverClass:{sc['name']}]")
        conf_lines.append(f"whitelist.0 = {sc['whitelist']}")
        conf_lines.append(f"# Filter: {sc['filter']}")
        conf_lines.append("")

        for app in sc["apps"]:
            conf_lines.append(f"[serverClass:{sc['name']}:app:{app}]")
            conf_lines.append(f"restartSplunkWeb = 0")
            conf_lines.append(f"restartSplunkd = 1")
            conf_lines.append(f"stateOnClient = enabled")
            conf_lines.append("")

    return json.dumps({
        "status": "ok",
        "server_classes": server_classes,
        "class_count": len(server_classes),
        "serverclass_conf": "\n".join(conf_lines),
        "notes": [
            "Adjust whitelist/blacklist patterns to match your naming convention",
            "Use machineTypesFilter for OS-based filtering",
            "Test with 'splunk reload deploy-server' after changes",
            "Monitor deployment status via CLI: splunk list deploy-clients",
        ],
    }, indent=2)


def check_compatibility(apps: str, target_version: Optional[str] = None) -> str:
    """
    Check version compatibility of apps and add-ons.

    Args:
        apps: Comma-separated list of app names and optional versions.
        target_version: Target Splunk version.

    Returns:
        JSON string with compatibility results.
    """
    if not apps or not apps.strip():
        return json.dumps({"status": "error", "error": "Apps list cannot be empty"})

    splunk_version = target_version or "9.2.0"
    app_list = [a.strip() for a in apps.split(",") if a.strip()]
    results = []

    for app_entry in app_list:
        # Parse app_name:version format
        parts = app_entry.split(":")
        app_name = parts[0].strip()
        app_version = parts[1].strip() if len(parts) > 1 else None

        # Look up app
        app_info = _KNOWN_APPS.get(app_name)
        if not app_info:
            # Try case-insensitive match
            for key, info in _KNOWN_APPS.items():
                if key.lower() == app_name.lower():
                    app_info = info
                    app_name = key
                    break

        if not app_info:
            results.append({
                "app": app_name,
                "version": app_version,
                "status": "unknown",
                "message": f"App '{app_name}' not found in compatibility database",
            })
            continue

        compatible = _version_in_range(splunk_version, app_info["min_splunk"], app_info["max_splunk"])

        result_entry = {
            "app": app_name,
            "display_name": app_info["display_name"],
            "app_version": app_version or "unknown",
            "latest_version": app_info["latest_version"],
            "type": app_info["type"],
            "compatible": compatible,
            "min_splunk": app_info["min_splunk"],
            "max_splunk": app_info["max_splunk"],
            "status": "compatible" if compatible else "incompatible",
        }

        if not compatible:
            result_entry["message"] = (
                f"Splunk {splunk_version} is outside supported range "
                f"({app_info['min_splunk']} - {app_info['max_splunk']})"
            )
        else:
            result_entry["message"] = f"Compatible with Splunk {splunk_version}"

        if app_version and app_version != app_info["latest_version"]:
            result_entry["update_available"] = True
            result_entry["update_message"] = f"Update available: {app_version} -> {app_info['latest_version']}"

        results.append(result_entry)

    # Overall assessment
    incompatible_count = sum(1 for r in results if r.get("status") == "incompatible")
    unknown_count = sum(1 for r in results if r.get("status") == "unknown")

    if incompatible_count > 0:
        overall = "incompatible"
    elif unknown_count > 0:
        overall = "partial"
    else:
        overall = "compatible"

    return json.dumps({
        "status": "ok",
        "target_splunk_version": splunk_version,
        "overall_compatibility": overall,
        "apps_checked": len(results),
        "compatible_count": sum(1 for r in results if r.get("status") == "compatible"),
        "incompatible_count": incompatible_count,
        "unknown_count": unknown_count,
        "results": results,
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("deployment_manager skill cleaned up")
