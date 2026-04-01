# Upgrade Readiness — Product Design (v4)

## Market Gap

Splunk's official Upgrade Readiness App is **DEAD** (deprecated v4.7.0, July 2025).
The community `splunk_upgrade_app_compatibility_checker` only checks Splunkbase metadata.
**Nobody** does conf auditing, CVE correlation, infra validation, or runbook generation.

## Five Analysis Engines

### Engine 1: App Compatibility Analyzer
- Query installed apps (REST API or repo scan)
- Match against Splunkbase API for version compatibility
- Scan private/custom app code for deprecated patterns (Python 2, old jQuery, removed imports)
- Categorize: Compatible / Incompatible / Unknown / Private

### Engine 2: Configuration Auditor
- Parse ALL `*.conf` files via `btool` output or filesystem scan
- Match against **Breaking Changes Database** (versioned YAML per Splunk version)
- Flag: deprecated settings, removed features, renamed settings, default changes
- Specific: `master_uri`→`manager_uri`, `slave-apps`→`peer-apps`, TLS settings, Python version

### Engine 3: Security & CVE Analyzer
- Local database of Splunk advisories (from advisory.splunk.com)
- Given current version: calculate open CVEs, cumulative CVSS exposure
- Given target version: show CVEs resolved, still open, net security improvement
- Recommend minimum safe version based on critical CVEs

### Engine 4: Infrastructure Readiness
- **Hardware**: CPU instruction sets (AVX/SSE4.2/AES-NI mandatory for 10.0+)
- **OS**: Supported versions, filesystem requirements (ext2→ext3)
- **Network**: TLS versions, certificate hash algorithms
- **Dependencies**: KV Store version (4.2+ required for 10.0), MongoDB state

### Engine 5: Upgrade Path Calculator
- Valid upgrade paths (official matrix)
- Risk per hop with breaking changes
- Optimal path: fewest hops vs safest
- Timeline with maintenance windows, rollback points, validation gates
- Effort estimation

## Breaking Changes Database (Core Differentiator)

Structured YAML, one file per Splunk major version:

```yaml
# data/breaking_changes/10.0.yaml
version: "10.0"
changes:
  - id: "BC-10.0-001"
    category: "hardware"
    severity: "blocker"
    title: "CPU instruction set requirement"
    description: "Requires AVX, SSE4.2, AES-NI"
    detection: "check_cpu_flags"
    migration: "Replace hardware or stay on 9.x"

  - id: "BC-10.0-002"
    category: "runtime"
    severity: "blocker"
    title: "Python 3.7 removed, only 3.9"
    detection: "scan_python_version"
    migration: "Update apps to Python 3.9"

  - id: "BC-10.0-003"
    category: "configuration"
    severity: "warning"
    title: "master_uri renamed to manager_uri"
    detection: "grep server.conf for master_uri"
    conf_file: "server.conf"
    migration: "Replace master_uri with manager_uri"

  - id: "BC-10.0-004"
    category: "configuration"
    severity: "warning"
    title: "slave-apps renamed to peer-apps"
    detection: "grep paths for slave-apps"
    migration: "Update all paths referencing slave-apps"

  - id: "BC-10.0-005"
    category: "security"
    severity: "blocker"
    title: "Minimum TLS 1.2 enforced"
    detection: "check server.conf sslVersions"
    conf_file: "server.conf"
    migration: "Remove tls1.0/tls1.1 from sslVersions"
```

## UX: Assessment Wizard

### Step 1: Environment
- Current Splunk version (auto-detect or manual)
- Target Splunk version (show recommendations based on CVEs)
- Environment type: single-instance / distributed / clustered
- Component roles: indexer / search head / cluster manager / forwarder

### Step 2: Scope
- Upgrade type: Platform / Apps / ES / ITSI / UF
- For Platform: show hardware/OS/TLS checks
- For Apps: run Splunkbase compatibility + code scan
- For ES/ITSI: show product-specific breaking changes

### Step 3: Assessment
- Run all selected engines
- Show progress per engine (5 progress bars)
- Results: overall readiness score (0-100)

### Step 4: Results Dashboard
```
┌─────────────────────────────────────────────────────┐
│ UPGRADE READINESS SCORE: 72/100 — MODERATE RISK     │
├─────────────┬─────────────┬─────────────┬───────────┤
│ Apps        │ Config      │ Security    │ Infra     │
│ 🟡 45/50   │ 🟠 12/20    │ 🔴 8/15     │ 🟢 7/15   │
│ 3 incomp   │ 8 warnings  │ 2 critical  │ All pass  │
│ 2 unknown   │ 2 blockers  │ CVEs       │           │
├─────────────┴─────────────┴─────────────┴───────────┤
│                                                      │
│ Release Timeline: v9.3.0 → v10.3.0                  │
│ ●━━━━●━━━━●━━━━●━━━━●━━━━●━━━━●                    │
│ 9.3  9.3.2 9.4  10.0 10.1 10.2 10.3               │
│ YOU       ⚠CVE  🔴BRK          → TARGET            │
│                                                      │
│ 🔴 BLOCKERS (must fix before upgrade):              │
│ • BC-10.0-001: CPU needs AVX support                │
│ • BC-10.0-005: TLS 1.0 still configured             │
│                                                      │
│ 🟡 WARNINGS (review recommended):                   │
│ • BC-10.0-003: master_uri needs rename (12 files)   │
│ • BC-10.0-004: slave-apps paths (3 locations)       │
│ • 3 apps not on Splunkbase (need code review)       │
│                                                      │
│ 🔒 SECURITY:                                        │
│ • SVD-2025-0501 (CRITICAL): Auth bypass — fixed in  │
│   10.0.0. Currently exposed on v9.3.0               │
│ • SVD-2025-0201 (MEDIUM): Info disclosure — fixed   │
│   in 9.4.0                                          │
│                                                      │
│ [Generate Runbook] [Export PDF] [Export JSON]        │
└─────────────────────────────────────────────────────┘
```

### Step 5: Runbook
Auto-generated ordered task list:
1. Pre-upgrade (backup, health baseline, app updates)
2. Infrastructure prep (hardware, OS, certs)
3. Configuration changes (specific commands per finding)
4. Upgrade execution order (cluster manager → indexers → SH → DS → UF)
5. Post-upgrade validation checklist
6. Rollback procedure

## Implementation Priority

| Sprint | Focus | Deliverable |
|--------|-------|-------------|
| 1 | Breaking Changes DB | YAML files for v9.0→10.3, loader, matcher |
| 2 | Config Auditor | Parse conf, match against DB, generate findings |
| 3 | CVE Analyzer | Advisory DB, version-range matching, risk scoring |
| 4 | App Compatibility | Splunkbase API + code scanning |
| 5 | Infra Checker | Hardware/OS/TLS validation |
| 6 | Upgrade Path | Version graph, path calculator |
| 7 | Runbook Generator | Synthesize findings into actionable plan |
| 8 | UI + Export | React page, PDF/JSON export |

## Files to Create

```
chat_app/upgrade_readiness/
    breaking_changes_db.py      — Load and query breaking changes
    config_auditor.py           — Scan conf against breaking changes
    cve_analyzer.py             — CVE database and version matching
    app_compat_checker.py       — Splunkbase API + code scan
    infra_checker.py            — Hardware/OS/TLS validation
    path_calculator.py          — Version graph and path optimization
    runbook_generator.py        — Generate ordered upgrade runbook
    readiness_scorer.py         — Overall score calculation (0-100)

data/breaking_changes/
    9.0.yaml
    9.1.yaml
    9.2.yaml
    9.3.yaml
    9.4.yaml
    10.0.yaml
    10.1.yaml
    10.2.yaml
    10.3.yaml

data/security_advisories/
    advisories.yaml             — Curated from advisory.splunk.com
```
