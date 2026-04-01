# Upgrade Readiness Page — Comprehensive Design

## The Vision

The upgrade readiness page is a **guided wizard** that walks the user through a complete upgrade assessment. It's NOT a simple form — it's an intelligent advisor that:

1. **Knows what you have** — auto-detects versions from org repo
2. **Knows what's available** — all 1,820 Splunkbase apps + Splunk platform versions
3. **Shows release history** — what changed between your version and latest
4. **Explains what it checks** — full transparency on the analysis
5. **Runs deep analysis** — conf diffs, CIM, dependencies, ES correlation searches
6. **Provides remediation** — specific steps to address each finding

## Data Sources

| Source | What It Provides | How We Get It |
|--------|-----------------|---------------|
| Splunkbase catalog (local) | 1,820 apps, version history, supported Splunk versions | Already cached at `/app/data/splunkbase_catalog.json` |
| Splunkbase API (live) | App description, per-version release notes page URL | `GET /api/v1/app/{uid}/` |
| Splunkbase release page | Actual release notes text | Web scrape `https://splunkbase.splunk.com/app/{uid}/#/details` (or manual) |
| Org repo | Installed versions via `app.conf`, local customizations | Scan `documents/repo/splunk/` |
| Splunk docs | Platform release notes, UF release notes | Cached reference data |
| Spec files | Valid configuration keys per conf type | `documents/specs/*.spec` |

## Page Layout (4-Step Wizard)

### Step 1: Select Upgrade Type
```
┌─────────────────────────────────────────────────────────────┐
│ What are you upgrading?                                     │
│                                                             │
│ [TA]  [App]  [ES]  [ITSI]  [UF]  [Core]                  │
│  ↑ selected                                                │
│                                                             │
│ Technology Add-on (TA)                                      │
│ TAs provide field extractions, transforms, lookups, and     │
│ event typing for specific data sources.                     │
│                                                             │
│ ▸ What we analyze (8 checks)                               │
│   • props.conf — field extractions (EXTRACT, REPORT...)    │
│   • transforms.conf — REGEX, FORMAT, lookups               │
│   • eventtypes.conf — CIM event classification             │
│   • tags.conf — CIM tag assignments                        │
│   • Index-time settings — LINE_BREAKER, TIME_FORMAT...     │
│   • CIM compliance — 15 data models                        │
│   • Cross-app dependencies — downstream consumers          │
│   • Local customization conflicts                          │
│                                                             │
│ ▸ What we need from you                                    │
│   • App/TA name (auto-detected from search)                │
│   • Current version (auto-detected from repo)              │
│   • Target version (defaults to latest)                    │
│   • Cluster name                                           │
│                                                             │
│ ▸ Risk factors (4)                                         │
│   ⚠ CRITICAL: Index-time field changes require re-indexing │
│   ⚠ HIGH: Renamed fields break saved searches              │
│   ⚠ HIGH: CIM regression breaks ES correlation searches    │
│   ⚠ MEDIUM: New defaults may conflict with local overrides │
│                                                             │
│ When ES/ITSI/UF/Core selected, show:                       │
│ ┌─ Platform Versions ──────────────────────────────────┐   │
│ │ Latest ES: v8.4.0 (Mar 2026)                        │   │
│ │ Latest ITSI: v4.19.0 (Feb 2026)                     │   │
│ │ Latest Splunk Enterprise: v10.3.0                    │   │
│ │ Latest UF: v10.3.0                                   │   │
│ └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Step 2: Find & Select App
```
┌─────────────────────────────────────────────────────────────┐
│ Find your App / TA                                          │
│                                                             │
│ Search Splunkbase (1,820 apps)                             │
│ [🔍 windows________________]                                │
│                                                             │
│ ┌─ Search Results ─────────────────────────────────────┐   │
│ │ Splunk Add-on for Windows  Splunk_TA_windows        │   │
│ │   Latest: v10.0.0 · 9 releases · Updated Mar 2026  │   │
│ │   Supported: Splunk 10.3, 10.2, 10.1, 9.4, 9.3    │   │
│ │                                          [Select →] │   │
│ ├─────────────────────────────────────────────────────┤   │
│ │ ServiceNow TA for Windows  ServiceNow_TA_windows... │   │
│ │   Latest: v1.0.5 · 6 releases                      │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                             │
│ Or enter manually:                                          │
│ App Name: [Splunk_TA_windows________]                      │
│ Cluster:  [cluster-search ▼]                                    │
│                                                             │
│ ┌─ Auto-Detected from Repo ───────────────────────────┐   │
│ │ Found in org repo:                                  │   │
│ │   cluster-search: v8.6.0 (3 local customizations)      │   │
│ │   cluster-es:     v8.6.0 (2 local customizations)      │   │
│ │   deployment-apps/_global: v8.6.0 (1 local)        │   │
│ └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Step 3: Version Selection & Release Intelligence
```
┌─────────────────────────────────────────────────────────────┐
│ Splunk Add-on for Microsoft Windows                         │
│                                                             │
│ Upgrading FROM          Latest Available     Gap            │
│ [v8.6.0 ▼]             v10.0.0              4 versions     │
│ (auto-detected)         (Mar 20, 2026)       behind        │
│                                                             │
│ ┌─ Version History ────────────────────────────────────┐   │
│ │ v   Version  Date        Splunk    Status            │   │
│ │ → 10.0.0    Mar 20, 2026 10.3+    LATEST            │   │
│ │   9.0.1     Nov 15, 2025 9.4+                       │   │
│ │   9.0.0     Aug 3, 2025  9.3+                       │   │
│ │   8.7.0     May 1, 2025  9.2+                       │   │
│ │ ★ 8.6.0     Jan 12, 2025 9.1+     YOU ARE HERE      │   │
│ │   8.5.2     Oct 8, 2024  9.0+                       │   │
│ │   8.5.0     Jul 20, 2024 8.2+                       │   │
│ │   8.4.0     Mar 5, 2024  8.2+                       │   │
│ │   8.3.0     Nov 1, 2023  8.1+                       │   │
│ └──────────────────────────────────────────────────────┘   │
│                                                             │
│ ┌─ Upgrade Path Analysis ──────────────────────────────┐   │
│ │ ✓ Direct upgrade recommended                        │   │
│ │   v8.6.0 → v10.0.0 (skipping 3 intermediate)       │   │
│ │                                                      │   │
│ │   Splunk version check:                             │   │
│ │   ✓ v10.0.0 supports Splunk 10.3 (your version)    │   │
│ │   ✓ No known compatibility issues                   │   │
│ └──────────────────────────────────────────────────────┘   │
│                                                             │
│ ▸ Changes Between v8.6.0 and v10.0.0                      │
│   (What happened in the 3 versions you're skipping)        │
│                                                             │
│   v8.7.0 (May 2025):                                      │
│     • Added PowerShell event collection support            │
│     • Updated CIM compliance for Authentication model      │
│     • Fixed TIME_FORMAT for Windows Event Log              │
│                                                             │
│   v9.0.0 (Aug 2025):                                      │
│     • BREAKING: Renamed TRANSFORMS references (v1→v2)     │
│     • New field aliases for CIM 5.0 compliance             │
│     • Deprecated WMI collection (use Windows Event Log)    │
│                                                             │
│   v9.0.1 (Nov 2025):                                      │
│     • Security fix: CVE-2025-XXXX patched                  │
│     • Bug fix: Fixed EventCode extraction regex            │
│                                                             │
│   v10.0.0 (Mar 2026):                                     │
│     • BREAKING: TIME_FORMAT changed to ISO 8601            │
│     • New: Sysmon event support                            │
│     • Updated lookup definitions                           │
│                                                             │
│ ▸ Pre-flight Checklist (6 items)                           │
│ ▸ Execution Plan (8 steps)                                 │
└─────────────────────────────────────────────────────────────┘
```

### Step 4: Run Analysis & Results
```
┌─────────────────────────────────────────────────────────────┐
│ Analysis Options                                            │
│                                                             │
│ ☑ Configuration diff (old default ⟷ new default ⟷ local)  │
│ ☑ CIM compliance check (15 data models)                   │
│ ☑ Dependency analysis (cross-app impact)                   │
│ ☐ Container test (deploys Splunk, ~5min)                   │
│ ☑ Spec file validation (124 spec files)                    │
│                                                             │
│ [▶ Run Full Analysis]                                       │
│                                                             │
│ ┌─ Analysis Progress ──────────────────────────────────┐   │
│ │ ████████████████████████░░░░░░ 75%                   │   │
│ │ ✓ Configuration backup captured                      │   │
│ │ ✓ New version extracted (v10.0.0)                    │   │
│ │ ✓ Three-way diff complete (19 findings)              │   │
│ │ ✓ CIM compliance checked (15 models)                 │   │
│ │ ⏳ Dependency analysis in progress...                │   │
│ │ ○ Spec validation pending                            │   │
│ └──────────────────────────────────────────────────────┘   │
│                                                             │
│ ┌─ Results ────────────────────────────────────────────┐   │
│ │ 🔴 CRITICAL RISK                                     │   │
│ │ Do not upgrade without addressing 2 critical items   │   │
│ │                                                      │   │
│ │ ┌── Risk Summary ──────────────────────────────┐    │   │
│ │ │ 🔴 CRITICAL  2  │  🟠 HIGH    5             │    │   │
│ │ │ 🟡 MEDIUM    3  │  🔵 LOW     1             │    │   │
│ │ │ ⚪ INFO       8  │  Total: 19 findings       │    │   │
│ │ └──────────────────────────────────────────────┘    │   │
│ │                                                      │   │
│ │ CIM Compliance:                                      │   │
│ │ ✓ Authentication ✓ Network ✓ Endpoint                │   │
│ │ ⚠ Change (1 missing field)                          │   │
│ │                                                      │   │
│ │ Dependencies Affected:                               │   │
│ │ • 3 ES correlation searches                          │   │
│ │ • 2 saved reports                                    │   │
│ │ • 1 data model acceleration                          │   │
│ │                                                      │   │
│ │ ▸ Show all 19 findings                              │   │
│ │ ▸ Download Markdown report                          │   │
│ │ ▸ Download JSON report                              │   │
│ └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints Needed

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/upgrade/types` | Upgrade type capabilities (what we check, need, risks) |
| `GET` | `/upgrade/search?q=...` | Search Splunkbase catalog |
| `GET` | `/upgrade/advisor/{app_id}` | Full advisor with versions, path, checklist, steps |
| `GET` | `/upgrade/versions/{app_id}` | Version history for an app |
| `GET` | `/upgrade/repo-scan` | Auto-detect installed versions from org repo |
| `GET` | `/upgrade/release-notes/{app_id}` | Fetch release notes between versions |
| `GET` | `/upgrade/platform-versions` | Latest Splunk Enterprise, UF, ES, ITSI versions |
| `POST` | `/upgrade/analyze` | Run full analysis |
| `GET` | `/upgrade/reports/{id}` | Get analysis report |
| `GET` | `/upgrade/reports/{id}/markdown` | Download Markdown report |

## Release Notes Strategy

The Splunkbase catalog does NOT store release notes. Options:

1. **Splunkbase API per-version page**: `GET /api/v1/app/{uid}/release/{version}/` — may have notes
2. **Splunkbase web scrape**: Parse release notes from the app's detail page
3. **Manual curation**: Admin can add notes via API
4. **LLM-generated summary**: Given conf diffs, generate human-readable change summary
5. **Cached reference data**: Bundle known release notes for major TAs/ES/ITSI

**Recommended approach**: Use option 4 (LLM summary from conf diffs) as primary, with option 5 (cached reference) for ES/ITSI/major TAs.

## Platform Version Tracking

Splunk Enterprise/UF versions are NOT in Splunkbase. Need a separate tracker:

```python
SPLUNK_PLATFORM_VERSIONS = {
    "enterprise": {
        "latest": "10.3.0",
        "releases": [
            {"version": "10.3.0", "date": "2026-03-01", "notes": "New search performance improvements"},
            {"version": "10.2.0", "date": "2025-11-15", "notes": "Enhanced dashboard framework"},
            {"version": "10.1.0", "date": "2025-08-01", "notes": "Federated search GA"},
            {"version": "10.0.0", "date": "2025-05-01", "notes": "Major platform update"},
            {"version": "9.4.0", "date": "2025-02-01", "notes": "Security fixes"},
            {"version": "9.3.2", "date": "2024-11-01", "notes": "Bug fixes"},
            {"version": "9.3.0", "date": "2024-08-01", "notes": "Performance improvements"},
        ]
    },
    "uf": {
        "latest": "10.3.0",  # Same as Enterprise
        "notes": "UF follows Enterprise versioning"
    },
    "es": {
        "latest": "8.4.0",
        "notes": "From Splunkbase SplunkEnterpriseSecurityInstaller"
    },
    "itsi": {
        "latest": "4.19.0",
        "notes": "From Splunkbase"
    }
}
```

## What's Different From Current Page

| Feature | Current | New |
|---------|---------|-----|
| App selection | Manual text input | Search + auto-complete + auto-detect from repo |
| Version selection | Manual | All versions shown, current auto-detected, latest highlighted |
| Release notes | None | Per-version change summary (LLM or cached) |
| Platform versions | None | ES/ITSI/UF/Core latest shown |
| What we check | Hidden | Visible per upgrade type with expandable details |
| Pre-flight | Hidden | Visible checklist before analysis |
| Execution plan | Hidden | Step-by-step plan visible |
| Progress | None | Real-time progress during analysis |
| Results | Simple risk badge | Full findings with CIM, dependencies, remediation |
