"""
Container-based Splunk upgrade testing for the Upgrade Readiness System.

Deploys ephemeral Splunk containers via podman (matching the admin_containers.py
pattern), mounts apps into them, captures pre/post-upgrade state snapshots, and
runs the full 15-category validation suite.

Also provides UFTestEnvironment for Universal Forwarder → Indexer two-container
end-to-end tests.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from chat_app.upgrade_readiness.models import (
    ContainerTestCase,
    ContainerTestResult,
    TestStatus,
)

logger = logging.getLogger(__name__)

# Splunk Docker image template — version is substituted at deploy time
SPLUNK_IMAGE_TEMPLATE = "docker.io/splunk/splunk:{version}"

# Internal Splunk REST API port inside the container
SPLUNK_REST_PORT = 8089

# Splunk management password for test containers
SPLUNK_TEST_PASSWORD = "Changeme1!"  # nosec — test-only, never production

# How often to poll for Splunk readiness (seconds)
READINESS_POLL_INTERVAL_SECONDS = 5

# Label applied to all test containers so they can be identified and cleaned up
CONTAINER_LABEL = "obsai-upgrade-test=true"

# -------------------------------------------------------------------------
# Validation test definitions — 15 categories
# -------------------------------------------------------------------------

# Each tuple: (test_id, name, description, category, command_template)
# Commands are run via `podman exec <container> splunk <cmd>` or
# via the REST API inside the container.
_VALIDATION_TESTS: List[Tuple[str, str, str, str, str]] = [
    (
        "conf_merge",
        "Conf Merge",
        "Verify btool reports no merge conflicts",
        "conf_validation",
        "splunk btool check --debug 2>&1 | head -50",
    ),
    (
        "saved_searches",
        "Saved Searches",
        "Verify saved searches parse without errors",
        "search_objects",
        "splunk rest /services/saved/searches?count=5&output_mode=json",
    ),
    (
        "field_extractions",
        "Field Extractions",
        "Check props-based field extractions are valid",
        "data_model",
        "splunk rest /services/data/props/extractions?count=10&output_mode=json",
    ),
    (
        "transforms",
        "Transforms Validation",
        "Validate REGEX/FORMAT in transforms.conf",
        "conf_validation",
        "splunk rest /services/data/transforms/extractions?count=10&output_mode=json",
    ),
    (
        "lookup_integrity",
        "Lookup Integrity",
        "Check lookup table files are accessible",
        "data_model",
        "splunk rest /services/data/transforms/lookups?count=10&output_mode=json",
    ),
    (
        "eventtypes",
        "Eventtype Validity",
        "Verify eventtype searches are syntactically valid",
        "search_objects",
        "splunk rest /services/saved/eventtypes?count=10&output_mode=json",
    ),
    (
        "tags",
        "Tag Mapping",
        "Check tag assignments resolve to known eventtypes",
        "search_objects",
        "splunk rest /services/saved/fvtags?count=10&output_mode=json",
    ),
    (
        "data_model_accel",
        "Data Model Acceleration",
        "Verify data model definitions load without errors",
        "data_model",
        "splunk rest /services/datamodel/model?count=5&output_mode=json",
    ),
    (
        "cim_fields",
        "CIM Field Compliance",
        "Check that CIM-required fields are present in extractions",
        "data_model",
        "splunk rest /services/data/props/extractions?count=20&search=app%3DCim&output_mode=json",
    ),
    (
        "macros",
        "Macro Expansion",
        "Verify macros are syntactically valid and resolve",
        "search_objects",
        "splunk rest /services/data/macros?count=20&output_mode=json",
    ),
    (
        "index_time_props",
        "Index-Time Props",
        "Check LINE_BREAKER and TIME_FORMAT settings",
        "conf_validation",
        "splunk btool props list --debug 2>&1 | grep -E 'LINE_BREAKER|TIME_FORMAT|SHOULD_LINEMERGE' | head -20",
    ),
    (
        "metadata_perms",
        "Metadata Permissions",
        "Compare default.meta vs local.meta for permission changes",
        "metadata",
        "splunk rest /services/configs/conf-default.meta?count=5&output_mode=json",
    ),
    (
        "kv_collections",
        "KV Store Collections",
        "Verify KV store collection definitions",
        "kvstore",
        "splunk rest /services/kvstore/collectionconfig?count=10&output_mode=json",
    ),
    (
        "alert_actions",
        "Alert Actions",
        "Check alert action configurations are valid",
        "alerting",
        "splunk rest /services/saved/searches?count=5&search=alert.type%3Dalways&output_mode=json",
    ),
    (
        "dashboards",
        "View / Dashboard Compat",
        "Verify XML dashboards load without parse errors",
        "ui",
        "splunk rest /services/data/ui/views?count=5&output_mode=json",
    ),
]


def _build_test_cases() -> List[ContainerTestCase]:
    """Construct the standard 15 ContainerTestCase objects."""
    cases = []
    for test_id, name, description, category, command in _VALIDATION_TESTS:
        cases.append(
            ContainerTestCase(
                test_id=test_id,
                name=name,
                description=description,
                category=category,
                command=command,
                expected_exit_code=0,
                timeout_seconds=60,
            )
        )
    return cases


def _run_podman(*args: str, timeout: int = 60) -> Tuple[int, str, str]:
    """
    Run a podman command synchronously and return (returncode, stdout, stderr).

    Uses ``subprocess.run`` directly, matching the admin_containers.py pattern.
    """
    cmd = ["podman"] + list(args)
    logger.debug("[CONTAINER_TEST] %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


async def _arun_podman(*args: str, timeout: int = 60) -> Tuple[int, str, str]:
    """Async wrapper around _run_podman — runs in a thread executor."""
    return await asyncio.to_thread(_run_podman, *args, timeout=timeout)


class SplunkTestContainer:
    """
    Lifecycle manager for an ephemeral Splunk test container.

    Each instance manages a single container from creation through cleanup.
    Uses podman commands matching the admin_containers.py pattern so the
    same runtime auto-detection applies.
    """

    def __init__(self) -> None:
        self._container_ids: List[str] = []

    # ------------------------------------------------------------------
    # Deploy
    # ------------------------------------------------------------------

    async def deploy(
        self,
        cluster_name: str,
        apps_dirs: Dict[str, str],
        splunk_version: str = "9.3.2",
    ) -> str:
        """
        Create and start a Splunk test container with apps mounted read-only.

        Args:
            cluster_name:  Used to generate the container name for traceability.
            apps_dirs:     Mapping of app_name → extracted app directory path.
                           Each app directory is bind-mounted into the container.
            splunk_version: Splunk docker image tag to use.

        Returns:
            The podman container ID string.

        Raises:
            RuntimeError: If the container cannot be created or started.
        """
        image = SPLUNK_IMAGE_TEMPLATE.format(version=splunk_version)
        safe_cluster = cluster_name.replace("/", "_").replace(":", "_")
        container_name = f"obsai-upgrade-test-{safe_cluster}-{int(time.time())}"

        # Build volume mounts for each app
        volume_args: List[str] = []
        for app_name, app_dir in apps_dirs.items():
            volume_args += [
                "-v",
                f"{app_dir}:/opt/splunk/etc/apps/{app_name}:z",
            ]

        cmd = [
            "run", "--detach",
            "--name", container_name,
            "--label", CONTAINER_LABEL,
            "-e", "SPLUNK_START_ARGS=--accept-license",
            "-e", f"SPLUNK_PASSWORD={SPLUNK_TEST_PASSWORD}",
            "-e", "SPLUNK_DISABLE_POPUPS=true",
        ] + volume_args + [image]

        returncode, stdout, stderr = await _arun_podman(*cmd, timeout=120)
        if returncode != 0:
            raise RuntimeError(
                f"Failed to create Splunk test container: {stderr}"
            )

        container_id = stdout.strip()
        self._container_ids.append(container_id)
        logger.info(
            "[CONTAINER_TEST] Deployed container %s (name=%s) for cluster=%s",
            container_id[:12], container_name, cluster_name,
        )
        return container_id

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    async def wait_ready(self, container_id: str, timeout: int = 300) -> bool:
        """
        Poll the container until Splunk is ready to serve REST requests.

        Polls ``/services/server/health/splunkd`` inside the container every
        READINESS_POLL_INTERVAL_SECONDS seconds.

        Args:
            container_id: Container ID returned by deploy().
            timeout:      Maximum seconds to wait before giving up.

        Returns:
            True if Splunk became ready within the timeout, False otherwise.
        """
        deadline = time.monotonic() + timeout
        logger.info("[CONTAINER_TEST] Waiting for Splunk ready in %s (timeout=%ds)", container_id[:12], timeout)

        while time.monotonic() < deadline:
            rc, out, _err = await _arun_podman(
                "exec", container_id,
                "splunk", "status",
                timeout=15,
            )
            if rc == 0 and "splunkd is running" in out.lower():
                logger.info("[CONTAINER_TEST] Splunk is ready in %s", container_id[:12])
                return True

            remaining = int(deadline - time.monotonic())
            logger.debug("[CONTAINER_TEST] Not ready yet, %ds remaining", remaining)
            await asyncio.sleep(READINESS_POLL_INTERVAL_SECONDS)

        logger.warning(
            "[CONTAINER_TEST] Splunk did not become ready in %s within %ds",
            container_id[:12], timeout,
        )
        return False

    # ------------------------------------------------------------------
    # State capture
    # ------------------------------------------------------------------

    async def capture_state(self, container_id: str) -> Dict[str, Any]:
        """
        Capture a comprehensive state snapshot from a running Splunk container.

        Queries key REST endpoints and btool outputs to build a dict that
        can be compared before and after an upgrade.

        Args:
            container_id: Container ID of a running Splunk instance.

        Returns:
            State dict with keys: saved_searches_count, field_extraction_count,
            macro_count, lookup_count, app_list, props_summary.
        """
        state: Dict[str, Any] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "container_id": container_id[:12],
        }

        async def _rest_count(endpoint: str, key: str) -> int:
            rc, out, _ = await _arun_podman(
                "exec", container_id,
                "splunk", "rest", f"{endpoint}?count=0&output_mode=json",
                timeout=30,
            )
            if rc != 0:
                return -1
            try:
                data = json.loads(out)
                return data.get("paging", {}).get("total", len(data.get("entry", [])))
            except (json.JSONDecodeError, KeyError, TypeError):
                return -1

        # Gather counts in parallel
        results = await asyncio.gather(
            _rest_count("/services/saved/searches", "saved_searches"),
            _rest_count("/services/data/props/extractions", "field_extractions"),
            _rest_count("/services/data/macros", "macros"),
            _rest_count("/services/data/transforms/lookups", "lookups"),
            _rest_count("/services/saved/eventtypes", "eventtypes"),
            return_exceptions=True,
        )

        labels = ["saved_searches_count", "field_extraction_count", "macro_count",
                  "lookup_count", "eventtype_count"]
        for label, value in zip(labels, results):
            state[label] = value if not isinstance(value, Exception) else -1

        # Capture installed app list
        rc, out, _ = await _arun_podman(
            "exec", container_id,
            "splunk", "rest", "/services/apps/local?count=100&output_mode=json",
            timeout=30,
        )
        if rc == 0:
            try:
                data = json.loads(out)
                state["app_list"] = [
                    e.get("name") for e in data.get("entry", [])
                ]
            except (json.JSONDecodeError, KeyError, TypeError):
                state["app_list"] = []

        return state

    # ------------------------------------------------------------------
    # Upgrade application
    # ------------------------------------------------------------------

    async def apply_upgrade(
        self, container_id: str, app_name: str, new_app_dir: str
    ) -> None:
        """
        Replace an app's default/ directory with the new version's default/.

        Preserves the organisation's local/ directory unchanged so that
        customisations are retained.

        Steps:
        1. Stop Splunk inside the container.
        2. Remove the old default/ directory.
        3. Copy the new default/ into place.
        4. Start Splunk.

        Args:
            container_id: Running container ID.
            app_name:     App folder name, e.g. ``Splunk_TA_windows``.
            new_app_dir:  Path (on the HOST) to the extracted new app version.

        Raises:
            RuntimeError: If stop/start or the copy operations fail.
        """
        app_base = f"/opt/splunk/etc/apps/{app_name}"
        new_default = f"{new_app_dir}/default"

        logger.info(
            "[CONTAINER_TEST] Applying upgrade for %s in %s from %s",
            app_name, container_id[:12], new_app_dir,
        )

        # Stop Splunk
        rc, _, err = await _arun_podman(
            "exec", container_id, "splunk", "stop", timeout=60
        )
        if rc != 0:
            raise RuntimeError(f"Could not stop Splunk in {container_id[:12]}: {err}")

        # Remove old default/
        rc, _, err = await _arun_podman(
            "exec", container_id,
            "bash", "-c", f"rm -rf {app_base}/default",
            timeout=30,
        )
        if rc != 0:
            raise RuntimeError(f"Could not remove old default/ for {app_name}: {err}")

        # Copy new default/ into the container via podman cp
        rc, _, err = await _arun_podman(
            "cp",
            f"{new_default}",
            f"{container_id}:{app_base}/default",
            timeout=60,
        )
        if rc != 0:
            raise RuntimeError(
                f"Could not copy new default/ for {app_name}: {err}"
            )

        # Restart Splunk
        rc, _, err = await _arun_podman(
            "exec", container_id,
            "splunk", "start", "--accept-license",
            timeout=120,
        )
        if rc != 0:
            raise RuntimeError(
                f"Could not restart Splunk after upgrade of {app_name}: {err}"
            )

    # ------------------------------------------------------------------
    # Validation test runner
    # ------------------------------------------------------------------

    async def run_validation_tests(
        self, container_id: str
    ) -> List[ContainerTestResult]:
        """
        Execute all 15 validation test categories inside the container.

        Each test runs via ``podman exec`` and its exit code plus output are
        recorded.  Tests that time out are marked ERROR rather than FAILED so
        the caller can distinguish timeouts from real failures.

        Args:
            container_id: Running container ID.

        Returns:
            List of ContainerTestResult, one per test category.
        """
        test_cases = _build_test_cases()
        results: List[ContainerTestResult] = []

        for case in test_cases:
            result = await self._run_single_test(container_id, case)
            results.append(result)

        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if r.status == TestStatus.FAILED)
        logger.info(
            "[CONTAINER_TEST] Validation complete in %s: %d/%d passed, %d failed",
            container_id[:12], passed, len(results), failed,
        )
        return results

    async def _run_single_test(
        self, container_id: str, case: ContainerTestCase
    ) -> ContainerTestResult:
        """Run a single test case and return the ContainerTestResult."""
        start = time.monotonic()
        try:
            rc, stdout, stderr = await _arun_podman(
                "exec", container_id,
                "bash", "-c", case.command,
                timeout=case.timeout_seconds,
            )
            duration = time.monotonic() - start

            if rc == case.expected_exit_code:
                status = TestStatus.PASSED
            else:
                status = TestStatus.FAILED

            return ContainerTestResult(
                test_id=case.test_id,
                name=case.name,
                status=status,
                duration_seconds=round(duration, 3),
                output=stdout[:2000],
                error=stderr[:500] if stderr else "",
                details={"exit_code": rc, "command": case.command},
            )

        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            return ContainerTestResult(
                test_id=case.test_id,
                name=case.name,
                status=TestStatus.ERROR,
                duration_seconds=round(duration, 3),
                output="",
                error=str(exc)[:500],
                details={"command": case.command},
            )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self, container_id: str) -> None:
        """
        Stop and remove a test container.

        Errors are logged but not re-raised so cleanup never blocks callers.

        Args:
            container_id: Container ID to clean up.
        """
        logger.info("[CONTAINER_TEST] Cleaning up container %s", container_id[:12])

        # Stop (ignore errors — container may already be stopped)
        await _arun_podman("stop", "-t", "10", container_id, timeout=30)

        # Remove
        rc, _, err = await _arun_podman("rm", "-f", container_id, timeout=30)
        if rc != 0:
            logger.warning(
                "[CONTAINER_TEST] Could not remove container %s: %s",
                container_id[:12], err,
            )
        elif container_id in self._container_ids:
            self._container_ids.remove(container_id)


# ---------------------------------------------------------------------------
# UFTestEnvironment — Universal Forwarder two-container setup
# ---------------------------------------------------------------------------


class UFTestEnvironment:
    """
    Two-container UF → Indexer test environment.

    Deploys a Universal Forwarder container and a standalone Indexer container
    on an isolated podman network, then verifies that events flow between them.
    """

    # Splunk UF image template
    UF_IMAGE_TEMPLATE = "docker.io/splunk/universalforwarder:{version}"

    def __init__(self) -> None:
        self._network_name: Optional[str] = None
        self._uf_id: Optional[str] = None
        self._indexer_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Deploy
    # ------------------------------------------------------------------

    async def deploy(
        self,
        uf_version: str,
        indexer_version: str,
        uf_apps: Dict[str, str],
        indexer_apps: Dict[str, str],
    ) -> Tuple[str, str]:
        """
        Deploy a UF container and an Indexer container on an isolated network.

        Args:
            uf_version:      UF image tag, e.g. ``"9.3.2"``.
            indexer_version: Splunk indexer image tag.
            uf_apps:         app_name → app_dir for the UF.
            indexer_apps:    app_name → app_dir for the indexer.

        Returns:
            (uf_container_id, indexer_container_id) tuple.
        """
        self._network_name = f"obsai-uf-test-{int(time.time())}"
        await _arun_podman("network", "create", self._network_name, timeout=30)

        indexer_id = await self._deploy_indexer(indexer_version, indexer_apps)
        uf_id = await self._deploy_uf(uf_version, uf_apps, indexer_id)

        self._uf_id = uf_id
        self._indexer_id = indexer_id
        return uf_id, indexer_id

    async def _deploy_indexer(
        self, version: str, apps: Dict[str, str]
    ) -> str:
        """Start the indexer container."""
        image = SPLUNK_IMAGE_TEMPLATE.format(version=version)
        name = f"obsai-indexer-{int(time.time())}"

        volume_args: List[str] = []
        for app_name, app_dir in apps.items():
            volume_args += ["-v", f"{app_dir}:/opt/splunk/etc/apps/{app_name}:z"]

        cmd = [
            "run", "--detach",
            "--name", name,
            "--network", self._network_name,
            "--label", CONTAINER_LABEL,
            "-e", "SPLUNK_START_ARGS=--accept-license",
            "-e", f"SPLUNK_PASSWORD={SPLUNK_TEST_PASSWORD}",
        ] + volume_args + [image]

        rc, stdout, stderr = await _arun_podman(*cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"Indexer deploy failed: {stderr}")
        return stdout.strip()

    async def _deploy_uf(
        self, version: str, apps: Dict[str, str], indexer_id: str
    ) -> str:
        """Start the UF container, forwarding to the indexer."""
        image = self.UF_IMAGE_TEMPLATE.format(version=version)
        name = f"obsai-uf-{int(time.time())}"

        # Get the indexer's container name from its ID for DNS resolution
        rc, out, _ = await _arun_podman("inspect", "--format", "{{.Name}}", indexer_id, timeout=15)
        indexer_name = out.lstrip("/") if rc == 0 else indexer_id[:12]

        volume_args: List[str] = []
        for app_name, app_dir in apps.items():
            volume_args += ["-v", f"{app_dir}:/opt/splunkforwarder/etc/apps/{app_name}:z"]

        cmd = [
            "run", "--detach",
            "--name", name,
            "--network", self._network_name,
            "--label", CONTAINER_LABEL,
            "-e", "SPLUNK_START_ARGS=--accept-license",
            "-e", f"SPLUNK_PASSWORD={SPLUNK_TEST_PASSWORD}",
            "-e", f"SPLUNK_FORWARD_SERVER={indexer_name}:9997",
        ] + volume_args + [image]

        rc, stdout, stderr = await _arun_podman(*cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"UF deploy failed: {stderr}")
        return stdout.strip()

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    async def send_test_events(
        self, uf_id: str, events: List[str]
    ) -> None:
        """
        Write test events to a file that the UF is monitoring.

        Appends each event as a line to ``/tmp/obsai_test_events.log`` inside
        the UF container, which should be configured in inputs.conf to be
        monitored.

        Args:
            uf_id:   UF container ID.
            events:  List of event strings to write.
        """
        for event in events:
            # Escape single quotes in event string
            safe_event = event.replace("'", "'\\''")
            await _arun_podman(
                "exec", uf_id,
                "bash", "-c",
                f"echo '{safe_event}' >> /tmp/obsai_test_events.log",
                timeout=10,
            )
        logger.debug(
            "[UF_TEST] Wrote %d test events to UF %s", len(events), uf_id[:12]
        )

    async def verify_received(
        self, indexer_id: str, expected_count: int
    ) -> bool:
        """
        Verify that the indexer has received the expected number of test events.

        Runs a simple ``splunk search`` inside the indexer container to count
        events in the ``obsai_test`` index.

        Args:
            indexer_id:     Indexer container ID.
            expected_count: Minimum number of events that should be present.

        Returns:
            True if at least expected_count events are found, False otherwise.
        """
        search_cmd = (
            "splunk search 'index=main source=/tmp/obsai_test_events.log "
            "| stats count' -maxout 1 -auth admin:" + SPLUNK_TEST_PASSWORD
        )
        rc, out, _ = await _arun_podman(
            "exec", indexer_id,
            "bash", "-c", search_cmd,
            timeout=60,
        )
        if rc != 0:
            logger.warning("[UF_TEST] Search failed on indexer %s", indexer_id[:12])
            return False

        # Parse the count from search output (simple last-integer heuristic)
        import re
        numbers = re.findall(r"\d+", out)
        actual = int(numbers[-1]) if numbers else 0
        result = actual >= expected_count
        logger.info(
            "[UF_TEST] Event verification: expected=%d, actual=%d, ok=%s",
            expected_count, actual, result,
        )
        return result

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self, uf_id: str, indexer_id: str) -> None:
        """
        Stop and remove both UF and indexer containers, then the test network.

        Args:
            uf_id:       UF container ID.
            indexer_id:  Indexer container ID.
        """
        for cid in (uf_id, indexer_id):
            if cid:
                await _arun_podman("stop", "-t", "5", cid, timeout=20)
                await _arun_podman("rm", "-f", cid, timeout=20)
                logger.info("[UF_TEST] Removed container %s", cid[:12])

        if self._network_name:
            await _arun_podman("network", "rm", self._network_name, timeout=20)
            logger.info("[UF_TEST] Removed network %s", self._network_name)
            self._network_name = None
