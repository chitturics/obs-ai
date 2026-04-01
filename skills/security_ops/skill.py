"""
Security Ops Skill — Threat detection, access auditing, compliance checking,
and risk assessment using SPL and MITRE ATT&CK.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MITRE ATT&CK technique mappings (subset for common techniques)
# ---------------------------------------------------------------------------

_MITRE_TECHNIQUES: Dict[str, Dict[str, Any]] = {
    "T1059": {
        "name": "Command and Scripting Interpreter",
        "tactic": "Execution",
        "description": "Adversaries may abuse command and script interpreters to execute commands.",
        "spl": (
            'index=endpoint (process_name="cmd.exe" OR process_name="powershell.exe" '
            'OR process_name="bash" OR process_name="python*") '
            '| stats count values(command_line) as commands by user, dest '
            '| where count > 10 '
            '| sort -count'
        ),
        "data_sources": ["Process creation", "Command execution"],
    },
    "T1059.001": {
        "name": "PowerShell",
        "tactic": "Execution",
        "description": "Adversaries may abuse PowerShell commands and scripts for execution.",
        "spl": (
            'index=endpoint process_name="powershell.exe" '
            '(command_line="*-enc*" OR command_line="*-nop*" OR command_line="*bypass*" '
            'OR command_line="*downloadstring*" OR command_line="*iex*") '
            '| stats count values(command_line) as commands by user, dest '
            '| sort -count'
        ),
        "data_sources": ["Process creation", "Script execution", "PowerShell logs"],
    },
    "T1078": {
        "name": "Valid Accounts",
        "tactic": "Persistence",
        "description": "Adversaries may obtain and abuse valid accounts to gain access.",
        "spl": (
            'index=security sourcetype=*auth* action=success '
            '| stats dc(src) as src_count values(src) as sources by user '
            '| where src_count > 3 '
            '| sort -src_count'
        ),
        "data_sources": ["Authentication logs", "Logon sessions"],
    },
    "T1110": {
        "name": "Brute Force",
        "tactic": "Credential Access",
        "description": "Adversaries may use brute force techniques to gain access to accounts.",
        "spl": (
            'index=security sourcetype=*auth* action=failure '
            '| stats count dc(user) as user_count by src '
            '| where count > 20 OR user_count > 5 '
            '| sort -count'
        ),
        "data_sources": ["Authentication logs"],
    },
    "T1053": {
        "name": "Scheduled Task/Job",
        "tactic": "Execution",
        "description": "Adversaries may abuse task scheduling to execute malicious code.",
        "spl": (
            'index=endpoint (process_name="schtasks.exe" OR process_name="at.exe" '
            'OR process_name="crontab") '
            '| stats count values(command_line) as commands by user, dest '
            '| sort -count'
        ),
        "data_sources": ["Process creation", "Scheduled job"],
    },
    "T1003": {
        "name": "OS Credential Dumping",
        "tactic": "Credential Access",
        "description": "Adversaries may attempt to dump credentials from the OS.",
        "spl": (
            'index=endpoint (process_name="mimikatz*" OR process_name="procdump*" '
            'OR process_name="gsecdump*" OR command_line="*sekurlsa*" '
            'OR command_line="*lsass*") '
            '| stats count values(command_line) as commands by user, dest '
            '| sort -count'
        ),
        "data_sources": ["Process creation", "OS API execution"],
    },
    "T1021": {
        "name": "Remote Services",
        "tactic": "Lateral Movement",
        "description": "Adversaries may use remote services to move laterally within a network.",
        "spl": (
            'index=security (sourcetype=*rdp* OR sourcetype=*ssh* OR sourcetype=*smb*) '
            'action=success '
            '| stats count dc(dest) as dest_count values(dest) as destinations by src, user '
            '| where dest_count > 3 '
            '| sort -dest_count'
        ),
        "data_sources": ["Network traffic", "Authentication logs", "Logon sessions"],
    },
    "T1048": {
        "name": "Exfiltration Over Alternative Protocol",
        "tactic": "Exfiltration",
        "description": "Adversaries may steal data by exfiltrating it over an alternative protocol.",
        "spl": (
            'index=network dest_port!=80 dest_port!=443 dest_port!=53 '
            '| stats sum(bytes_out) as total_bytes dc(dest) as dest_count by src '
            '| where total_bytes > 104857600 '
            '| eval total_mb=round(total_bytes/1048576,2) '
            '| sort -total_bytes'
        ),
        "data_sources": ["Network traffic", "Network connection creation"],
    },
    "T1071": {
        "name": "Application Layer Protocol",
        "tactic": "Command and Control",
        "description": "Adversaries may communicate using application layer protocols to avoid detection.",
        "spl": (
            'index=network (dest_port=80 OR dest_port=443 OR dest_port=53) '
            '| stats count sum(bytes_out) as total_bytes by src, dest '
            '| where count > 1000 OR total_bytes > 52428800 '
            '| sort -total_bytes'
        ),
        "data_sources": ["Network traffic"],
    },
    "T1190": {
        "name": "Exploit Public-Facing Application",
        "tactic": "Initial Access",
        "description": "Adversaries may exploit vulnerabilities in internet-facing applications.",
        "spl": (
            'index=web (status=500 OR status=503 OR status=400 OR status=403) '
            '| stats count by src, uri_path, status '
            '| where count > 50 '
            '| sort -count'
        ),
        "data_sources": ["Application logs", "Web logs"],
    },
}

# ---------------------------------------------------------------------------
# Audit query templates
# ---------------------------------------------------------------------------

_AUDIT_QUERIES: Dict[str, Dict[str, Any]] = {
    "login": {
        "description": "Audit login patterns for anomalous access",
        "queries": [
            {
                "name": "Failed logins by user",
                "spl": ('index=security sourcetype=*auth* action=failure '
                        '| stats count by user, src '
                        '| where count > 5 | sort -count'),
            },
            {
                "name": "Logins outside business hours",
                "spl": ('index=security sourcetype=*auth* action=success '
                        '| eval hour=strftime(_time, "%H") '
                        '| where hour<6 OR hour>20 '
                        '| stats count by user, src, hour | sort -count'),
            },
            {
                "name": "Multiple concurrent sessions",
                "spl": ('index=security sourcetype=*auth* action=success '
                        '| stats dc(src) as src_count values(src) as sources by user '
                        '| where src_count > 2'),
            },
        ],
    },
    "privilege": {
        "description": "Audit privilege escalation attempts",
        "queries": [
            {
                "name": "Privilege escalation events",
                "spl": ('index=security (sourcetype=*auth* OR sourcetype=*admin*) '
                        '(action=escalated OR action=elevated OR "privilege" OR "sudo" OR "runas") '
                        '| stats count by user, dest, action | sort -count'),
            },
            {
                "name": "New admin account creation",
                "spl": ('index=security sourcetype=*admin* '
                        '(action=created OR action=added) (group=admin* OR role=admin*) '
                        '| table _time, user, dest, action, object'),
            },
        ],
    },
    "access": {
        "description": "Audit data access patterns",
        "queries": [
            {
                "name": "Sensitive file access",
                "spl": ('index=endpoint action=access '
                        '(file_path="*password*" OR file_path="*credential*" '
                        'OR file_path="*secret*" OR file_path="*.key" OR file_path="*.pem") '
                        '| stats count by user, file_path, dest | sort -count'),
            },
            {
                "name": "Mass file access in short period",
                "spl": ('index=endpoint action=access '
                        '| bin _time span=5m '
                        '| stats dc(file_path) as file_count by user, dest, _time '
                        '| where file_count > 100 | sort -file_count'),
            },
        ],
    },
    "lateral_movement": {
        "description": "Audit lateral movement indicators",
        "queries": [
            {
                "name": "RDP/SSH connections to multiple hosts",
                "spl": ('index=network (dest_port=3389 OR dest_port=22) '
                        '| stats dc(dest) as dest_count values(dest) as destinations by src, user '
                        '| where dest_count > 3 | sort -dest_count'),
            },
            {
                "name": "Pass-the-hash indicators",
                "spl": ('index=security sourcetype=WinEventLog EventCode=4624 LogonType=3 '
                        'AuthenticationPackageName=NTLM '
                        '| stats count by src, dest, user | where count > 5 | sort -count'),
            },
        ],
    },
    "data_exfil": {
        "description": "Audit potential data exfiltration",
        "queries": [
            {
                "name": "Large outbound data transfers",
                "spl": ('index=network action=allowed direction=outbound '
                        '| stats sum(bytes_out) as total_bytes by src, dest '
                        '| where total_bytes > 104857600 '
                        '| eval total_mb=round(total_bytes/1048576,2) | sort -total_bytes'),
            },
            {
                "name": "DNS tunneling indicators",
                "spl": ('index=network sourcetype=*dns* '
                        '| eval query_len=len(query) '
                        '| where query_len > 50 '
                        '| stats count avg(query_len) as avg_len by src '
                        '| where count > 100 | sort -count'),
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# Compliance checks
# ---------------------------------------------------------------------------

_COMPLIANCE_CHECKS = [
    {"pattern": r"(?i)index\s*=\s*\*", "finding": "Wildcard index access — violates least privilege principle",
     "severity": "high", "benchmark": "CIS Splunk 1.1.1"},
    {"pattern": r"(?i)allowRemoteLogin\s*=\s*always", "finding": "Remote login always allowed without restriction",
     "severity": "high", "benchmark": "CIS Splunk 3.2.1"},
    {"pattern": r"(?i)enableSplunkWebSSL\s*=\s*false", "finding": "Splunk Web SSL is disabled",
     "severity": "critical", "benchmark": "CIS Splunk 2.1.1"},
    {"pattern": r"(?i)sslVersions\s*=\s*ssl3", "finding": "SSLv3 enabled — vulnerable to POODLE attack",
     "severity": "critical", "benchmark": "CIS Splunk 2.1.3"},
    {"pattern": r"(?i)requireClientCert\s*=\s*false", "finding": "Client certificate not required for inter-node communication",
     "severity": "medium", "benchmark": "CIS Splunk 2.2.1"},
    {"pattern": r"(?i)pass4SymmKey\s*=\s*changeme", "finding": "Default symmetric key in use — must be changed",
     "severity": "critical", "benchmark": "CIS Splunk 3.1.1"},
    {"pattern": r"(?i)minFreeSpace\s*=\s*0", "finding": "No minimum free disk space configured — risk of data loss",
     "severity": "medium", "benchmark": "CIS Splunk 4.1.1"},
    {"pattern": r"(?i)enableSplunkdSSL\s*=\s*false", "finding": "splunkd management port SSL is disabled",
     "severity": "critical", "benchmark": "CIS Splunk 2.1.2"},
    {"pattern": r"(?i)admin\s*:\s*changeme", "finding": "Default admin password in configuration",
     "severity": "critical", "benchmark": "CIS Splunk 3.1.2"},
    {"pattern": r"(?i)allowGuestAccess\s*=\s*true", "finding": "Guest access is enabled",
     "severity": "high", "benchmark": "CIS Splunk 3.2.2"},
]

# ---------------------------------------------------------------------------
# Risk factors
# ---------------------------------------------------------------------------

_RISK_FACTORS = [
    {"pattern": r"(?i)index\s*=\s*\*", "risk": 25, "reason": "Searches all indexes — broad data exposure"},
    {"pattern": r"(?i)(password|secret|token|api_key|credential)", "risk": 20, "reason": "Accesses sensitive fields"},
    {"pattern": r"(?i)\|\s*outputlookup", "risk": 15, "reason": "Writes data to lookup — potential data exfiltration"},
    {"pattern": r"(?i)\|\s*collect", "risk": 15, "reason": "Writes to summary index — data duplication risk"},
    {"pattern": r"(?i)\|\s*sendemail", "risk": 20, "reason": "Sends email — potential data exfiltration channel"},
    {"pattern": r"(?i)\|\s*outputcsv", "risk": 15, "reason": "Exports data to CSV file"},
    {"pattern": r"(?i)\|\s*rest\s+/services", "risk": 20, "reason": "Accesses Splunk REST API — configuration exposure"},
    {"pattern": r"(?i)_internal|_audit", "risk": 10, "reason": "Accesses internal/audit indexes — system information exposure"},
    {"pattern": r"(?i)earliest\s*=\s*0", "risk": 15, "reason": "Searches all time — excessive data scope"},
    {"pattern": r"(?i)\|\s*delete", "risk": 30, "reason": "Delete command — destructive operation"},
]

# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def detect_threats(technique: str) -> str:
    """
    Generate threat detection SPL queries from MITRE ATT&CK techniques.

    Args:
        technique: MITRE technique ID or name.

    Returns:
        JSON string with detection queries and metadata.
    """
    if not technique or not technique.strip():
        return json.dumps({"status": "error", "error": "Technique cannot be empty"})

    tech_input = technique.strip()

    # Try direct ID match
    matched = _MITRE_TECHNIQUES.get(tech_input.upper())

    # Try name-based match
    if not matched:
        tech_lower = tech_input.lower()
        for tid, info in _MITRE_TECHNIQUES.items():
            if tech_lower in info["name"].lower():
                matched = info
                matched["id"] = tid
                break

    # Try partial ID match
    if not matched:
        for tid, info in _MITRE_TECHNIQUES.items():
            if tech_input.upper() in tid:
                matched = info
                matched["id"] = tid
                break

    if not matched:
        return json.dumps({
            "status": "error",
            "error": f"No mapping found for technique: {technique}",
            "available_techniques": {tid: info["name"] for tid, info in _MITRE_TECHNIQUES.items()},
        })

    technique_id = matched.get("id", tech_input.upper())

    return json.dumps({
        "status": "ok",
        "technique_id": technique_id,
        "technique_name": matched["name"],
        "tactic": matched["tactic"],
        "description": matched["description"],
        "detection_spl": matched["spl"],
        "data_sources": matched["data_sources"],
        "recommendations": [
            "Schedule this search as a correlation search in Splunk ES",
            "Tune thresholds based on your environment baseline",
            "Create a notable event action for positive detections",
            f"Map findings to MITRE ATT&CK technique {technique_id}",
        ],
    }, indent=2)


def audit_access(audit_type: str) -> str:
    """
    Generate audit queries for access patterns.

    Args:
        audit_type: Type of audit to perform.

    Returns:
        JSON string with audit queries.
    """
    if not audit_type or not audit_type.strip():
        return json.dumps({"status": "error", "error": "Audit type cannot be empty"})

    at = audit_type.strip().lower()
    audit_info = _AUDIT_QUERIES.get(at)

    if not audit_info:
        return json.dumps({
            "status": "error",
            "error": f"Unknown audit type: {audit_type}",
            "available_types": list(_AUDIT_QUERIES.keys()),
        })

    return json.dumps({
        "status": "ok",
        "audit_type": at,
        "description": audit_info["description"],
        "queries": audit_info["queries"],
        "recommendations": [
            "Run these queries on a regular schedule for continuous monitoring",
            "Adjust thresholds to match your environment's normal baseline",
            "Export results to a summary index for trend analysis",
        ],
    }, indent=2)


def check_compliance(config: str) -> str:
    """
    Check configurations against CIS benchmarks.

    Args:
        config: Configuration content or description to check.

    Returns:
        JSON string with compliance findings.
    """
    if not config or not config.strip():
        return json.dumps({"status": "error", "error": "Configuration cannot be empty"})

    findings = []
    for check in _COMPLIANCE_CHECKS:
        if re.search(check["pattern"], config):
            findings.append({
                "finding": check["finding"],
                "severity": check["severity"],
                "benchmark": check["benchmark"],
            })

    # Determine overall compliance
    if any(f["severity"] == "critical" for f in findings):
        overall = "non_compliant"
    elif any(f["severity"] == "high" for f in findings):
        overall = "partially_compliant"
    elif findings:
        overall = "minor_issues"
    else:
        overall = "compliant"

    passed = len(_COMPLIANCE_CHECKS) - len(findings)
    total = len(_COMPLIANCE_CHECKS)
    score = round((passed / total) * 100, 1) if total > 0 else 100.0

    return json.dumps({
        "status": "ok",
        "overall_compliance": overall,
        "compliance_score": score,
        "checks_passed": passed,
        "checks_failed": len(findings),
        "total_checks": total,
        "findings": findings,
        "recommendations": [
            f"Address {len([f for f in findings if f['severity'] == 'critical'])} critical findings immediately",
            "Review CIS Splunk Benchmark for detailed remediation steps",
            "Schedule regular compliance scans",
        ],
    }, indent=2)


def assess_risk(query: str) -> str:
    """
    Assess risk score based on query patterns and data exposure.

    Args:
        query: SPL query or activity description to assess.

    Returns:
        JSON string with risk assessment.
    """
    if not query or not query.strip():
        return json.dumps({"status": "error", "error": "Query cannot be empty"})

    risk_score = 0
    risk_details = []

    for factor in _RISK_FACTORS:
        if re.search(factor["pattern"], query):
            risk_score += factor["risk"]
            risk_details.append({
                "factor": factor["reason"],
                "points": factor["risk"],
            })

    # Cap at 100
    risk_score = min(risk_score, 100)

    if risk_score >= 75:
        risk_level = "critical"
    elif risk_score >= 50:
        risk_level = "high"
    elif risk_score >= 25:
        risk_level = "medium"
    elif risk_score > 0:
        risk_level = "low"
    else:
        risk_level = "minimal"

    mitigations = []
    if risk_score > 0:
        if any("index" in d["factor"].lower() for d in risk_details):
            mitigations.append("Restrict to specific index names instead of wildcard")
        if any("sensitive" in d["factor"].lower() for d in risk_details):
            mitigations.append("Apply field-level access controls via roles")
        if any("export" in d["factor"].lower() or "csv" in d["factor"].lower() or "email" in d["factor"].lower()
               for d in risk_details):
            mitigations.append("Review data export policies and restrict output commands")
        if any("REST" in d["factor"] for d in risk_details):
            mitigations.append("Limit REST API access via capability-based authorization")
        mitigations.append("Implement role-based access control (RBAC) for sensitive searches")

    return json.dumps({
        "status": "ok",
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_factors": risk_details,
        "mitigations": mitigations,
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("security_ops skill cleaned up")
