# Splunk Upgrade Readiness Testing System — Design v3 (Final)

## What Already Exists (Reuse, Don't Rebuild)

| Component | Module | What It Does |
|-----------|--------|-------------|
| **Splunkbase Catalog** | `splunkbase_catalog.py` | 1,820 apps with versions, releases, supported Splunk versions |
| **App Fetcher** | `splunkbase_catalog.py:fetch_app_list()` | Paginated fetch from Splunkbase REST API |
| **App Details** | `splunkbase_catalog.py:fetch_app_details()` | Release history, download URLs per app |
| **Installed App Query** | `splunkbase_catalog_impl.py:get_installed_apps_from_splunk()` | REST call to live Splunk `GET /services/apps/local` |
| **Version Comparison** | `splunkbase_catalog_impl.py:compare_installed()` | Outdated/current/unknown classification |
| **Catalog Refresh** | Admin API: `POST /splunkbase/refresh` | Trigger Splunkbase re-fetch |
| **Conf Parser** | `shared/conf_parser.py:parse_conf_file_advanced()` | Stanza-aware .conf parsing with line numbers |
| **Conf Analyzer** | `conf_index_time_analyzer.py` | Index-time props analysis, ConfsScanner |
| **Cribl Migration** | `conf_cribl_migration.py` | Props/transforms diffing, field mapping |
| **Spec Files** | `documents/specs/` | 124 .spec files defining all valid Splunk settings |
| **Knowledge Graph** | `knowledge_graph.py` | Entity relationships for SPL commands/fields |
| **Container Mgmt** | `admin_containers.py` | Podman container lifecycle (create/start/stop/logs) |

## The Gap: What's New

The upgrade readiness system adds **5 new capabilities** on top of existing infrastructure:

### 1. Repo-Aware Baseline Builder
Scans the org git repo (already cloned via GitHub integration) to build per-cluster app inventories. Uses `parse_conf_file_advanced()` for conf parsing. Matches each app against the Splunkbase catalog using `compare_installed()`.

### 2. Three-Way Conf Differ
Not just old-vs-new diff — a THREE-WAY diff: `old_default/ ⟷ new_default/ ⟷ local/`. Simulates Splunk's merge semantics to predict exactly what changes behavior.

### 3. CIM Impact Analyzer
Goes beyond conf diffing — checks if field extractions still satisfy CIM data model requirements. Uses the 124 spec files in `documents/specs/` to validate settings.

### 4. Auto-Download + Container Test Pipeline
```
Splunkbase Catalog (1,820 apps)
  → identify upgrade (compare_installed)
    → auto-download new version (fetch_app_details → download URL)
      → extract .tgz
        → static analysis (conf_differ)
          → deploy Splunk container (admin_containers pattern)
            → mount old configs + new app
              → run validation tests via REST API
                → compare before/after
                  → generate report
```

### 5. Extensive Test Suite in Container
Not just "does it parse" — runs 15+ validation categories:

| # | Test Category | Method | What It Catches |
|---|--------------|--------|-----------------|
| 1 | Conf merge | `btool list --debug` | Merge conflicts, precedence issues |
| 2 | Search parse | `| rest /services/saved/searches` | Broken SPL from renamed fields/macros |
| 3 | Field extraction | `| rest /services/data/props/extractions` | Missing/renamed extractions |
| 4 | Transform validation | `| rest /services/data/transforms/extractions` | Invalid REGEX/FORMAT |
| 5 | Lookup integrity | `| inputlookup <name> | head 1` | Missing/changed lookup files |
| 6 | Eventtype validity | `| rest /services/saved/eventtypes` | Broken eventtype searches |
| 7 | Tag mapping | `| rest /services/saved/fvtags` | Broken tag assignments |
| 8 | Data model accel | `| rest /services/datamodel/model` | Acceleration failures |
| 9 | CIM field check | `| datamodel <model> search | head 0` | CIM field compliance |
| 10 | Macro expansion | `| rest /services/data/macros` | Missing/changed macros |
| 11 | Index-time props | btool props list --app=<app> | LINE_BREAKER, TIME_FORMAT changes |
| 12 | Metadata perms | Compare default.meta vs local.meta | Permission changes |
| 13 | Collection defs | `| rest /services/kvstore/collectionconfig` | KV store schema changes |
| 14 | Alert actions | `| rest /services/saved/searches` where alert | Broken alert configurations |
| 15 | View/dashboard | Check for XML dashboard changes | Dashboard/view compatibility |

## Detailed Architecture

### New Package Structure

```
chat_app/upgrade_readiness/
    __init__.py                 — Public API: run_upgrade_check(), get_upgrade_service()
    models.py                   — Frozen dataclasses + Pydantic models (< 500 lines)
    baseline_builder.py         — Phase 1: Scan repo + match Splunkbase catalog
    conf_differ.py              — Phase 2: Three-way stanza-level diffing
    impact_scorer.py            — Phase 2: Risk scoring + finding generation
    cim_analyzer.py             — Phase 2: CIM compliance checking
    dependency_tracer.py        — Phase 2: Cross-app dependency graph (NetworkX)
    splunkbase_fetcher.py       — Phase 3: Auto-download from Splunkbase (extends existing catalog)
    container_deployer.py       — Phase 3: Splunk test container lifecycle (extends admin_containers)
    test_executor.py            — Phase 3: Run 15 validation test categories
    report_builder.py           — Phase 4: JSON/Markdown/HTML report generation
    spec_validator.py           — Uses documents/specs/ to validate conf settings
```

### How It Uses Existing Code

```python
# baseline_builder.py — reuses splunkbase_catalog
from chat_app.splunkbase_catalog import get_splunkbase_catalog

class BaselineBuilder:
    def __init__(self):
        self.catalog = get_splunkbase_catalog()

    async def build_cluster_baseline(self, cluster_name: str, repo_path: str) -> ClusterBaseline:
        """
        1. Walk repo_path/{cluster}/apps/ for all app directories
        2. For each app: parse default/app.conf → get installed version
        3. For each app: parse ALL .conf files in default/ and local/
        4. Match against self.catalog using compare_installed()
        5. Return ClusterBaseline with upgrade candidates marked
        """

    async def get_upgrade_candidates(self, cluster: str) -> List[UpgradeCandidate]:
        """
        Uses self.catalog.compare_installed() to find outdated apps.
        Enriches each with: versions_behind, release_notes, breaking_changes.
        """
```

```python
# splunkbase_fetcher.py — extends existing fetch_app_details
from chat_app.splunkbase_catalog import get_splunkbase_catalog

class SplunkbaseFetcher:
    def __init__(self):
        self.catalog = get_splunkbase_catalog()

    async def download_upgrade(self, app_id: str, target_version: str) -> str:
        """
        1. Look up app in catalog by app_id
        2. Get specific release from releases[] list
        3. Download .tgz from Splunkbase download URL
        4. Cache in /app/data/splunkbase_downloads/{app_id}/{version}.tgz
        5. Extract to temp dir
        6. Return path to extracted app directory
        """

    async def auto_download_latest(self, app_id: str) -> str:
        """Download the latest version automatically."""
        app = self.catalog.get_app_by_id(app_id)
        return await self.download_upgrade(app_id, app["latest_version"])
```

```python
# container_deployer.py — extends admin_containers pattern
from chat_app.admin_shared import _container_cmd, _arun

class SplunkTestContainer:
    def __init__(self):
        self.runtime = "podman"  # from _container_cmd()

    async def deploy_test_splunk(
        self,
        cluster_name: str,
        apps_dirs: Dict[str, str],  # app_name -> extracted app dir
        splunk_version: str = "9.3.2",
    ) -> str:
        """
        Uses same podman commands as admin_containers.py:
        1. podman create with Splunk image
        2. Mount each app dir to /opt/splunk/etc/apps/{app_name}
        3. Set SPLUNK_START_ARGS, SPLUNK_PASSWORD
        4. Start container
        5. Wait for ready via /services/server/health/splunkd
        6. Return container_id
        """

    async def apply_upgrade(self, container_id: str, app_name: str, new_app_dir: str):
        """
        1. Stop Splunk inside container
        2. Replace /opt/splunk/etc/apps/{app_name}/default/ with new default/
        3. Keep /opt/splunk/etc/apps/{app_name}/local/ unchanged (org customizations)
        4. Start Splunk
        5. Wait for ready
        """

    async def capture_state(self, container_id: str) -> SplunkState:
        """Capture comprehensive state via REST API."""

    async def cleanup(self, container_id: str):
        """Stop and remove test container."""
```

### Conf Differ — Three-Way Algorithm

```python
class ConfDiffer:
    """Three-way Splunk conf diffing engine."""

    def three_way_diff(
        self,
        old_default: Dict[str, Dict[str, str]],  # from old .tgz default/
        new_default: Dict[str, Dict[str, str]],  # from new .tgz default/
        local: Dict[str, Dict[str, str]],         # from org repo local/
    ) -> List[UpgradeFinding]:
        """
        For EVERY stanza in union(old_default, new_default, local):

        1. STANZA IN OLD ONLY (removed by vendor):
           - If local has customizations → CRITICAL: orphaned local customization
           - If no local → MEDIUM: feature removed

        2. STANZA IN NEW ONLY (added by vendor):
           - If local has same stanza → MEDIUM: check for key conflicts
           - If no local → INFO: new feature, no conflict

        3. STANZA IN BOTH OLD AND NEW (modified by vendor):
           For each key:
           a. Key REMOVED in new:
              - Local overrides? → LOW (local wins, but base gone)
              - No local override → HIGH (behavior change)
           b. Key VALUE CHANGED in new:
              - Local overrides same key? → LOW (local wins)
              - No local override → HIGH (silent behavior change)
              - Is it an index-time key (LINE_BREAKER etc)? → CRITICAL
           c. Key ADDED in new:
              - Local has same key? → MEDIUM (potential conflict)
              - No conflict → INFO

        4. SIMULATE MERGED STATE:
           merged_before = {**old_default[stanza], **local[stanza]}
           merged_after  = {**new_default[stanza], **local[stanza]}
           If merged_before != merged_after → actual behavior change
        """
```

### CIM Analyzer

```python
# Embedded CIM data model definitions (from Splunk_SA_CIM app)
CIM_MODELS = {
    "Authentication": {
        "constraints": 'tag=authentication',
        "required_fields": ["action", "app", "dest", "src", "user"],
        "optional_fields": ["authentication_method", "duration", "reason", "signature"],
        "related_eventtypes": ["authentication"],
        "related_tags": {"authentication": ["authentication"]},
    },
    "Change": {
        "constraints": 'tag=change',
        "required_fields": ["action", "object", "object_category", "result", "status"],
    },
    "Endpoint.Processes": {
        "constraints": 'tag=process tag=report',
        "required_fields": ["dest", "process", "process_id", "user"],
        "optional_fields": ["action", "parent_process", "parent_process_id", "process_path"],
    },
    "Intrusion_Detection": {
        "constraints": 'tag=ids tag=attack',
        "required_fields": ["action", "category", "dest", "severity", "signature", "src"],
    },
    "Malware": {
        "constraints": 'tag=malware tag=attack',
        "required_fields": ["action", "dest", "file_name", "signature"],
    },
    "Network_Traffic": {
        "constraints": 'tag=network tag=communicate',
        "required_fields": ["action", "bytes_in", "bytes_out", "dest", "dest_port", "src", "transport"],
    },
    "Web": {
        "constraints": 'tag=web',
        "required_fields": ["dest", "http_method", "src", "status", "url"],
    },
    # ... 15+ more models
}

class CIMAnalyzer:
    def check_compliance(self, app_baseline: AppBaseline) -> List[CIMResult]:
        """
        1. From eventtypes.conf → find eventtype definitions with their search strings
        2. From tags.conf → find which eventtypes are tagged for which CIM models
        3. From props.conf → find EXTRACT/REPORT/FIELDALIAS for relevant sourcetypes
        4. From transforms.conf → resolve REPORT references to actual regex/field names
        5. Compare extracted fields against CIM_MODELS[model].required_fields
        6. Return compliance status per model with missing/extra fields
        """

    def check_upgrade_cim_impact(
        self,
        old_baseline: AppBaseline,
        new_default_confs: Dict[str, Dict],
    ) -> List[CIMFinding]:
        """
        Compare CIM compliance BEFORE vs AFTER upgrade.
        Flag regressions: fields that were compliant before but not after.
        """
```

### Spec Validator

```python
class SpecValidator:
    """Validates conf settings against Splunk .spec files."""

    def __init__(self):
        self.specs = self._load_specs("documents/specs/")

    def _load_specs(self, specs_dir: str) -> Dict[str, SpecFile]:
        """
        Parse all 124 .spec files:
        - props.conf.spec → valid keys for [stanza] in props.conf
        - transforms.conf.spec → valid keys for transforms
        etc.
        """

    def validate_conf(
        self,
        conf_type: str,
        stanzas: Dict[str, Dict[str, str]],
    ) -> List[SpecViolation]:
        """
        Check every key in every stanza against the .spec definition:
        - Is this key valid for this conf type?
        - Is the value format correct?
        - Are required keys present?
        - Are deprecated keys used?
        """
```

## End-to-End Workflow (Fully Automated)

```
User: "Check upgrade readiness for Splunk_TA_windows on cluster-es"

STEP 1: IDENTIFY
├── Look up Splunk_TA_windows in org repo → installed v8.6.0 with 23 local/ customizations
├── Look up in Splunkbase catalog (1,820 apps) → latest v10.0.0
├── 4 intermediate releases: v8.7.0, v9.0.0, v9.0.1, v10.0.0
└── Output: "Upgrade available: v8.6.0 → v10.0.0 (4 versions behind)"

STEP 2: DOWNLOAD
├── Check cache: /app/data/splunkbase_downloads/Splunk_TA_windows/
├── If not cached: fetch_app_details() → get download URL
├── Download v10.0.0 .tgz from Splunkbase
├── Extract to temp directory
└── Output: extracted app at /tmp/upgrade_test/Splunk_TA_windows_10.0.0/

STEP 3: STATIC ANALYSIS
├── Parse old default/ (from repo, v8.6.0)
├── Parse new default/ (from download, v10.0.0)
├── Parse local/ (from repo, org customizations)
├── Three-way diff: old_default ⟷ new_default ⟷ local
├── For EACH conf file (props, transforms, savedsearches, eventtypes, tags, macros):
│   ├── Identify added/removed/modified stanzas
│   ├── Cross-reference against local/ customizations
│   ├── Score risk per finding
│   └── Check against spec files for validity
├── CIM compliance check:
│   ├── Which CIM models does this TA feed? (from eventtypes/tags)
│   ├── Do field extractions still satisfy model requirements?
│   └── Impact on ES correlation searches?
├── Dependency trace:
│   ├── Which other apps depend on this TA's fields/transforms?
│   ├── Which saved searches reference this TA's lookups?
│   └── Propagate risk to downstream consumers
└── Output: UpgradeImpactReport with risk scores

STEP 4: CONTAINER TESTING
├── Create test container:
│   ├── podman create splunk/splunk:9.3.2
│   ├── Mount ALL cluster apps (from repo) to /opt/splunk/etc/apps/
│   ├── Include: CIM (Splunk_SA_CIM), ES suite (if cluster-es), all TAs
│   └── Wait for Splunk ready
├── BEFORE snapshot:
│   ├── btool props list --app=Splunk_TA_windows (full merged output)
│   ├── | rest /services/saved/searches (all searches with parse status)
│   ├── | rest /services/data/props/extractions (all field extractions)
│   ├── | rest /services/data/transforms/extractions (all transforms)
│   ├── | rest /services/data/lookup-table-files (all lookups)
│   ├── | rest /services/saved/eventtypes (all eventtypes)
│   ├── | rest /services/saved/fvtags (all tags)
│   ├── | rest /services/datamodel/model (all data models)
│   └── | rest /services/data/macros (all macros)
├── APPLY UPGRADE:
│   ├── Replace Splunk_TA_windows/default/ with v10.0.0 default/
│   ├── Keep local/ untouched
│   ├── Restart Splunk
│   └── Wait for ready
├── AFTER snapshot: (same 9 REST queries)
├── COMPARE before vs after:
│   ├── Field extractions: added/removed/changed
│   ├── Saved searches: any parse errors?
│   ├── Data models: acceleration status changed?
│   ├── Lookups: any missing files?
│   ├── Eventtypes: any broken searches?
│   ├── btool diff: what changed in merged config?
│   └── Generate before/after diff report
├── RUN VALIDATION TESTS (15 categories):
│   ├── ✓/✗ per test with details
│   └── Capture any Splunk errors from _internal
├── CLEANUP: stop + remove container
└── Output: ContainerTestResults

STEP 5: REPORT
├── Combine: static analysis + container test results
├── Overall risk: CRITICAL / HIGH / MEDIUM / LOW / SAFE
├── Recommendation: "Safe to upgrade" / "Review required" / "Do not upgrade"
├── Per-finding: description, risk, remediation, affected searches
├── CIM compliance: before/after comparison per data model
├── Container test: 15 test results with before/after state
├── Export: JSON, Markdown, HTML
└── Store in ChromaDB for future reference
```

## API Endpoints (18 total)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/upgrade/inventory` | Full baseline inventory (all clusters) |
| `POST` | `/upgrade/inventory/scan` | Trigger baseline scan |
| `GET` | `/upgrade/inventory/{cluster}` | Apps for a cluster |
| `GET` | `/upgrade/candidates` | All apps with upgrades available |
| `GET` | `/upgrade/candidates/{cluster}` | Upgrade candidates for a cluster |
| `POST` | `/upgrade/analyze` | Full analysis: static + optional container test |
| `POST` | `/upgrade/analyze/quick` | Quick analysis: static only, no container |
| `GET` | `/upgrade/download/{app_id}/{version}` | Download status (or trigger download) |
| `POST` | `/upgrade/test/deploy` | Deploy test container |
| `GET` | `/upgrade/test/{suite_id}` | Test progress/results |
| `POST` | `/upgrade/test/{suite_id}/abort` | Abort running test |
| `GET` | `/upgrade/reports` | List reports |
| `GET` | `/upgrade/reports/{id}` | Full report |
| `GET` | `/upgrade/reports/{id}/download` | Export as Markdown/HTML |
| `GET` | `/upgrade/cim/status/{cluster}` | CIM compliance matrix |
| `GET` | `/upgrade/dependencies/{cluster}` | Dependency graph |
| `GET` | `/upgrade/history` | Analysis history |
| `GET` | `/upgrade/splunkbase/search` | Search Splunkbase catalog |

## Frontend — 6-Tab UpgradeReadinessPage

### Tab 1: Dashboard
```
┌──────────────────────────────────────────────────────────┐
│  UPGRADE READINESS DASHBOARD                             │
├────────────┬────────────┬────────────┬──────────────────┤
│ Clusters   │ Total Apps │ Outdated   │ Critical Risk    │
│     4      │    156     │    43      │      7           │
├────────────┴────────────┴────────────┴──────────────────┤
│                                                          │
│  Risk Heatmap by Cluster:                               │
│  cluster-search:  ███████░░░ 12 outdated (2 high risk)     │
│  cluster-es:      █████████░ 18 outdated (4 high risk)     │
│  cluster-itsi:    ████░░░░░░  6 outdated (1 high risk)     │
│  cluster-dma:     ██████░░░░  7 outdated (0 high risk)     │
│                                                          │
│  Recent Reports:                                         │
│  • Splunk_TA_windows v8.6→10.0 on cluster-es: HIGH RISK    │
│  • Splunk_TA_nix v9.0→9.2 on cluster-search: LOW RISK     │
└──────────────────────────────────────────────────────────┘
```

### Tab 2: Inventory Browser
```
┌─────────────────────────────────────────────────────────┐
│  Cluster: [cluster-es ▼]     Filter: [________] [TAs only] │
├─────────────────────────┬─────────┬─────────┬──────────┤
│ App Name                │ Installed│ Latest  │ Status   │
├─────────────────────────┼─────────┼─────────┼──────────┤
│ Splunk_TA_windows       │ 8.6.0   │ 10.0.0  │ ⚠ 4 behind│
│ Splunk_TA_nix           │ 9.0.0   │ 9.2.1   │ ⚠ 2 behind│
│ Splunk_TA_cisco_asa     │ 4.1.0   │ 4.1.0   │ ✓ current │
│ DA-ESS-ContentUpdate    │ 5.20.0  │ 5.24.0  │ ⚠ 4 behind│
│ Splunk_SA_CIM           │ 5.1.0   │ 5.3.0   │ ⚠ 2 behind│
│                         │         │         │          │
│ [23 local customizations in props.conf]                │
│ [8 custom saved searches]                              │
│ [3 local transforms]                                    │
└─────────────────────────┴─────────┴─────────┴──────────┘
```

### Tab 3: Analyze Upgrade
```
┌─────────────────────────────────────────────────────────┐
│  Step 1: Select Cluster   [cluster-es ▼]                    │
│  Step 2: Select App       [Splunk_TA_windows ▼]         │
│          Installed: v8.6.0 → Latest: v10.0.0            │
│  Step 3: Target Version   [v10.0.0 ▼] (auto-download)  │
│                                                          │
│  Options:                                                │
│  ☑ CIM compliance check                                │
│  ☑ Cross-app dependency analysis                        │
│  ☐ Container-based live testing (takes ~5 min)          │
│  ☑ Validate against spec files                          │
│                                                          │
│  [ ▶ Run Upgrade Analysis ]                             │
│                                                          │
│  ─── Results ──────────────────────────────────────     │
│  Risk: HIGH                                              │
│  Recommendation: Review required before upgrade          │
│                                                          │
│  Findings: 2 critical, 5 high, 12 medium, 23 low       │
│  ┌─────────────────────────────────────────────────┐    │
│  │ ⛔ CRITICAL: props.conf [WinEventLog:Security]  │    │
│  │    TRANSFORMS-msad-xml removed from default     │    │
│  │    Your local/ has custom FIELDALIAS for src_ip │    │
│  │    Impact: 3 ES correlation searches affected   │    │
│  │    Fix: Add TRANSFORMS back in local/props.conf │    │
│  ├─────────────────────────────────────────────────┤    │
│  │ ⚠ HIGH: transforms.conf [msad-xml-extract-v2]  │    │
│  │    REGEX pattern changed                        │    │
│  │    Old: (?<EventCode>\d{4})                    │    │
│  │    New: (?<EventCode>\d{4,5})                  │    │
│  │    No local override → behavior changes         │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Tab 4: Container Testing
```
┌─────────────────────────────────────────────────────────┐
│  Container Test: Splunk_TA_windows v8.6→10.0 on cluster-es │
│                                                          │
│  Status: ████████████████████████░░ 80% — Running tests │
│  Container: upgrade_test_abc123 (splunk/splunk:9.3.2)   │
│                                                          │
│  Test Results:                                           │
│  ✓ Conf merge check         (0.3s)                      │
│  ✓ Saved search parse       (1.2s) — 145/145 parse OK  │
│  ✓ Field extractions        (0.8s) — 67 registered      │
│  ✓ Transform validation     (0.5s) — 23 valid           │
│  ✓ Lookup integrity         (0.4s) — 12/12 loadable     │
│  ✗ Eventtype validity       (0.6s) — 1 broken           │
│      [WinEventLog:Security] search references removed   │
│      macro `winevent_sec_actions`                        │
│  ✓ Tag mapping             (0.3s)                        │
│  ⏳ Data model acceleration (running...)                 │
│  ⏳ CIM field validation    (pending)                    │
│  ⏳ Index-time props check  (pending)                    │
│                                                          │
│  Before/After Comparison:                                │
│  ┌────────────────────┬──────────┬──────────┐           │
│  │ Metric             │ Before   │ After    │           │
│  ├────────────────────┼──────────┼──────────┤           │
│  │ Field extractions  │ 67       │ 72 (+5)  │           │
│  │ Saved searches     │ 145      │ 145      │           │
│  │ Eventtypes         │ 34       │ 33 (-1)  │           │
│  │ Lookups            │ 12       │ 14 (+2)  │           │
│  │ Data models accel  │ 8/8      │ 7/8 ⚠   │           │
│  └────────────────────┴──────────┴──────────┘           │
└─────────────────────────────────────────────────────────┘
```

### Tab 5: CIM Compliance Matrix
```
┌──────────────────────────────────────────────────────────┐
│  CIM Compliance: cluster-es                                  │
├──────────────────────┬───────┬───────┬──────┬───────────┤
│ Data Model           │ Before│ After │ Risk │ Missing   │
├──────────────────────┼───────┼───────┼──────┼───────────┤
│ Authentication       │ ✓ 5/5│ ✓ 5/5│ None │           │
│ Network_Traffic      │ ✓ 7/7│ ⚠ 6/7│ HIGH │ bytes_out │
│ Endpoint.Processes   │ ✓ 5/5│ ✓ 5/5│ None │           │
│ Malware              │ ✓ 4/4│ ✓ 4/4│ None │           │
│ Change               │ ✓ 5/5│ ⚠ 4/5│ MED  │ result    │
│ Web                  │ ✓ 5/5│ ✓ 5/5│ None │           │
│ Intrusion_Detection  │ ✓ 6/6│ ✓ 6/6│ None │           │
└──────────────────────┴───────┴───────┴──────┴───────────┘
```

### Tab 6: Reports & History
- List all past reports with search/filter
- Click to view full report
- Export as Markdown for change review board
- Export as HTML for email distribution
- Compare two reports side-by-side

## Implementation Sprints

### Sprint 1: Core (models + differ + scorer) — 5 files, ~100 tests
### Sprint 2: CIM + dependencies + spec validation — 4 files, ~80 tests
### Sprint 3: Auto-download + container testing — 4 files, ~60 tests
### Sprint 4: API + frontend + integration — 4 files, ~60 tests
### Total: 17 new files, ~300 tests

## Config (config.yaml)

```yaml
upgrade_readiness:
  enabled: true
  repo_path: "documents/repo/splunk"
  download_cache: "/app/data/splunkbase_downloads"
  splunkbase_auth_token: ""          # env: SPLUNKBASE_AUTH_TOKEN
  container_image: "splunk/splunk:9.3.2"
  container_cpus: 2
  container_memory: "4g"
  max_test_duration: 600             # seconds
  cim_version: "5.3.0"
  auto_download: true
  clusters:
    cluster-search:
      splunk_version: "9.3.2"
      type: "shc"
      apps_path: "shcluster/cluster-search/apps"
    cluster-es:
      splunk_version: "9.3.2"
      type: "shc"
      apps_path: "shcluster/cluster-es/apps"
      features: ["enterprise_security", "cim"]
    cluster-itsi:
      splunk_version: "9.3.2"
      type: "shc"
      apps_path: "shcluster/cluster-itsi/apps"
      features: ["itsi"]
    cluster-dma:
      splunk_version: "9.3.2"
      type: "shc"
      apps_path: "shcluster/cluster-dma/apps"
```

---

## Phase 5: Universal Forwarder (UF) Upgrade Testing

### Why UF Upgrades Are Different

UF upgrades are NOT just version bumps — they affect:
1. **inputs.conf** — data collection changes (WMI, perfmon, file monitors, scripted inputs)
2. **outputs.conf** — forwarding topology (indexer discovery, load balancing, SSL)
3. **deploymentclient.conf** — deployment server communication
4. **server.conf** — SSL/TLS settings, connection limits
5. **limits.conf** — throtling, queue sizes
6. **props.conf** — index-time field extractions (LINE_BREAKER, TIME_FORMAT) that run ON the forwarder
7. **transforms.conf** — index-time transforms (routing, nullQueue, regex)

### UF-Specific Risks

| Risk | Impact | Example |
|------|--------|---------|
| **Data loss** | Events stop flowing | inputs.conf monitor path changed; WMI collection deprecated |
| **Index-time parsing breaks** | Events malformed in indexes | LINE_BREAKER regex changed; TIME_FORMAT incompatible |
| **SSL/TLS incompatibility** | Forwarder can't connect to indexers | TLS 1.0/1.1 dropped; cipher suite changes |
| **Deployment server disconnect** | Forwarder loses management | deploymentclient.conf format change |
| **Resource exhaustion** | Forwarder OOM/CPU spike | New default queue sizes; changed limits |
| **Routing changes** | Events go to wrong index | transforms.conf routing rules changed |
| **Backwards compat** | Mixed-version environment issues | New UF version + old indexer cluster |

### UF Test Container Strategy

Unlike search head testing (single Splunk instance), UF testing requires a **two-container setup**:

```
┌──────────────────┐     ┌──────────────────┐
│  UF Container    │────>│  Indexer Container│
│  (forwarder)     │ TCP │  (receiver)       │
│                  │9997 │                   │
│  - inputs.conf   │     │  - Receives events│
│  - outputs.conf  │     │  - Validates data │
│  - props.conf    │     │  - Checks parsing │
│  - Test data     │     │  - CIM fields OK? │
└──────────────────┘     └──────────────────┘
```

### UF Validation Tests

| # | Test | Method | What It Catches |
|---|------|--------|-----------------|
| 1 | UF starts clean | `splunk status` returns running | Install/upgrade failures |
| 2 | Deployment client connects | Check `splunk list deploy-clients` | deploymentclient.conf issues |
| 3 | Outputs configured | `splunk list forward-server` | outputs.conf problems |
| 4 | Inputs active | `splunk list inputstatus` | Broken/changed inputs |
| 5 | Data forwarding works | Send test event, verify received on indexer | End-to-end data path |
| 6 | Index-time parsing | Send known event, check parsed fields on indexer | LINE_BREAKER/TIME_FORMAT |
| 7 | SSL/TLS handshake | Check `splunk show tls-status` | Certificate/cipher issues |
| 8 | File monitor | Create test file, verify events collected | Monitor stanza changes |
| 9 | WMI collection (Windows) | Check WMI input status | WMI deprecation/changes |
| 10 | Scripted inputs | Verify scripted input execution | Script compatibility |
| 11 | Resource usage | Check CPU/memory after start | Resource regression |
| 12 | Queue health | Check `splunk list queue` | Queue sizing changes |
| 13 | Backwards compat | UF→old indexer version forwarding works | Version compatibility |
| 14 | Routing rules | Send event matching routing rule, verify index | transforms routing changes |
| 15 | Config merge | `btool inputs list --debug` | Merge conflict detection |

### UF Version Matrix

Test against these version combinations:

| UF Version | Indexer Version | Expected |
|------------|----------------|----------|
| Current UF | Current Indexer | Baseline (must pass) |
| New UF | Current Indexer | Backward compat test |
| New UF | New Indexer | Full upgrade test |
| Current UF | New Indexer | Forward compat test |

### UF Container Setup

```python
class UFTestEnvironment:
    """Manages UF + Indexer two-container test setup."""

    async def deploy(
        self,
        uf_version: str,
        indexer_version: str,
        uf_apps: Dict[str, str],      # app_name -> app_dir
        indexer_apps: Dict[str, str],  # app_name -> app_dir (for props/transforms)
    ) -> Tuple[str, str]:
        """
        1. Create indexer container:
           podman create --name idx_test_{uuid}
             -e SPLUNK_START_ARGS=--accept-license
             -e SPLUNK_PASSWORD=Test123!
             -p 9997:9997   # receiving port
             splunk/splunk:{indexer_version}

        2. Create UF container:
           podman create --name uf_test_{uuid}
             -e SPLUNK_START_ARGS=--accept-license
             -e SPLUNK_PASSWORD=Test123!
             -e SPLUNK_STANDALONE_URL=idx_test_{uuid}:8089
             -e SPLUNK_FORWARD_SERVER=idx_test_{uuid}:9997
             splunk/universalforwarder:{uf_version}

        3. Mount test data directory for file monitoring
        4. Wait for both containers ready
        5. Return (uf_container_id, indexer_container_id)
        """

    async def send_test_events(self, uf_id: str, events: List[str]):
        """Write test events to a monitored file on the UF."""

    async def verify_received(self, indexer_id: str, expected_count: int) -> bool:
        """Search on indexer to verify events were received and parsed."""

    async def capture_uf_state(self, uf_id: str) -> UFState:
        """Capture UF runtime state via CLI commands."""

    async def cleanup(self, uf_id: str, indexer_id: str):
        """Stop and remove both containers."""
```

### Org Repo UF Structure

```
documents/repo/splunk/
├── deployment-apps/              # Apps deployed TO forwarders
│   ├── _global/                  # All forwarders
│   │   ├── Splunk_TA_windows/
│   │   │   ├── default/inputs.conf     # WMI, perfmon, file monitors
│   │   │   ├── default/props.conf      # Index-time extractions
│   │   │   └── local/inputs.conf       # Org-specific input overrides
│   │   └── org_all_forwarders/
│   │       ├── default/outputs.conf    # Indexer targets
│   │       └── local/outputs.conf      # Org overrides
│   ├── cluster-prod-dc/              # Production domain controllers
│   │   └── Splunk_TA_windows/
│   │       └── local/inputs.conf       # DC-specific inputs (Security, DNS)
│   └── cluster-prod-web/             # Production web servers
│       └── Splunk_TA_iis/
│           └── local/inputs.conf       # IIS-specific inputs
└── master-apps/                  # Indexer cluster apps (index-time configs)
    └── _cluster/
        ├── Splunk_TA_windows/
        │   └── default/props.conf      # Index-time only (MUST match UF props)
        └── indexes.conf
```

### UF-Specific Findings

```python
class UFUpgradeFinding(UpgradeFinding):
    """Extended finding for UF-specific issues."""
    affected_forwarder_groups: List[str] = field(default_factory=list)
    data_loss_risk: bool = False
    requires_indexer_upgrade: bool = False
    requires_reindex: bool = False
    ssl_impact: bool = False
```

### Config (added to upgrade_readiness section)

```yaml
upgrade_readiness:
  uf_testing:
    enabled: true
    uf_image: "splunk/universalforwarder:9.3.2"
    indexer_image: "splunk/splunk:9.3.2"
    test_event_count: 100           # events to send for forwarding test
    test_timeout_seconds: 120       # per-test timeout
    forwarder_groups:
      - name: "cluster-prod-dc"
        description: "Production domain controllers"
        apps_path: "deployment-apps/cluster-prod-dc"
      - name: "cluster-prod-web"
        description: "Production web servers"
        apps_path: "deployment-apps/cluster-prod-web"
```
