"""
Splunk REST API and validator container integration.
"""
import logging
import os
import shutil
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)

_SPLUNK_VALIDATOR_HOST = os.getenv("SPLUNK_VALIDATOR_HOST", "localhost")
_SPLUNK_VALIDATOR_PORT = int(os.getenv("SPLUNK_VALIDATOR_PORT", "8089"))
_SPLUNK_VALIDATOR_USER = os.getenv("SPLUNK_VALIDATOR_USER", "admin")
_SPLUNK_VALIDATOR_PASS = os.getenv("SPLUNK_VALIDATOR_PASS", "ValidatorP@ss123")
_verify_ssl = os.environ.get("SPLUNK_VERIFY_SSL", "true").lower() != "false"
_ca_bundle = os.environ.get("SPLUNK_CA_BUNDLE", "")
_ssl_verify = _ca_bundle if _ca_bundle else _verify_ssl


def _remote_parse(query: str) -> Dict[str, Any]:
    """Optional remote validation using Splunk's /services/search/parser via splunk-sdk."""
    host = os.getenv("SPLUNK_HOST")
    if not host:
        return {"available": False, "reason": "SPLUNK_HOST not set"}

    port = int(os.getenv("SPLUNK_PORT", "8089"))
    verify = os.getenv("SPLUNK_VERIFY", "true").lower() not in {"0", "false", "no"}
    token = os.getenv("SPLUNK_TOKEN")
    username = os.getenv("SPLUNK_USERNAME")
    password = os.getenv("SPLUNK_PASSWORD")

    try:
        import splunklib.client as client  # type: ignore

        if token:
            service = client.connect(host=host, port=port, token=token, verify=verify)
        elif username and password:
            service = client.connect(host=host, port=port, username=username, password=password, verify=verify)
        else:
            return {"available": False, "reason": "No SPLUNK_TOKEN or SPLUNK_USERNAME/PASSWORD provided"}

        parsed = service.parse(query, parse_only=True)
        messages = []
        if parsed and hasattr(parsed, "messages"):
            for msg in parsed.messages:
                messages.append({"type": msg.get("type"), "text": msg.get("text")})

        return {
            "available": True,
            "messages": messages,
            "status": "ok" if not any(m.get("type") == "ERROR" for m in messages) else "error",
        }
    except Exception as exc:
        return {"available": True, "status": "error", "reason": str(exc)}


def _run_btool_check() -> Dict[str, Any]:
    """Attempt a simple btool sanity check if available."""
    cmd = ["btool", "check"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
        return {
            "available": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"available": False, "reason": "btool not installed"}
    except Exception as exc:
        return {"available": True, "error": str(exc)}


def _btool_all(conf_dir) -> Dict[str, Any]:
    """Run btool check --debug against a repo/conf directory if available."""
    from pathlib import Path
    conf_dir = Path(conf_dir)
    btool = shutil.which("btool")
    if not btool:
        return {"available": False, "reason": "btool not installed"}
    if not conf_dir.exists():
        return {"available": False, "reason": f"conf dir not found: {conf_dir}"}
    cmd = [btool, "check", "--debug", f"--app={conf_dir}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        return {
            "available": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:2000],
        }
    except Exception as exc:
        return {"available": True, "error": str(exc)}


def validate_spl_with_splunk(query: str) -> Dict[str, Any]:
    """Validate SPL query syntax using Splunk's REST API /services/search/parser."""
    result = {
        "available": False,
        "valid": None,
        "errors": [],
        "warnings": [],
        "parsed_info": {},
    }

    try:
        import requests
        from urllib3.exceptions import InsecureRequestWarning
        import urllib3
        urllib3.disable_warnings(InsecureRequestWarning)

        url = f"https://{_SPLUNK_VALIDATOR_HOST}:{_SPLUNK_VALIDATOR_PORT}/services/search/parser"
        response = requests.post(
            url,
            auth=(_SPLUNK_VALIDATOR_USER, _SPLUNK_VALIDATOR_PASS),
            data={"q": query, "output_mode": "json", "parse_only": "true"},
            verify=_ssl_verify,
            timeout=10,
        )

        result["available"] = True

        if response.status_code == 200:
            data = response.json()
            result["valid"] = True
            result["parsed_info"] = data
            if "messages" in data:
                for msg in data["messages"]:
                    msg_type = msg.get("type", "").upper()
                    msg_text = msg.get("text", "")
                    if msg_type == "ERROR":
                        result["errors"].append(msg_text)
                        result["valid"] = False
                    elif msg_type in ("WARN", "WARNING"):
                        result["warnings"].append(msg_text)
        elif response.status_code == 400:
            result["valid"] = False
            try:
                error_data = response.json()
                if "messages" in error_data:
                    for msg in error_data["messages"]:
                        result["errors"].append(msg.get("text", str(msg)))
                else:
                    result["errors"].append(error_data.get("detail", str(error_data)))
            except Exception:
                result["errors"].append(response.text[:500])
        else:
            result["errors"].append(f"Unexpected response: {response.status_code}")

    except Exception as e:
        if "ConnectionError" in type(e).__name__:
            result["available"] = False
            result["reason"] = f"Cannot connect to Splunk validator at {_SPLUNK_VALIDATOR_HOST}:{_SPLUNK_VALIDATOR_PORT}"
        elif isinstance(e, ImportError):
            result["available"] = False
            result["reason"] = "requests library not installed"
        else:
            result["available"] = True
            result["errors"].append(f"Validation error: {str(e)}")

    return result


def run_search_preview(query: str, max_results: int = 1) -> Dict[str, Any]:
    """Run a search preview against Splunk to verify it executes without errors."""
    result = {
        "available": False,
        "executed": False,
        "errors": [],
        "warnings": [],
        "sample_results": [],
    }

    try:
        import requests
        from urllib3.exceptions import InsecureRequestWarning
        import urllib3
        urllib3.disable_warnings(InsecureRequestWarning)

        url = f"https://{_SPLUNK_VALIDATOR_HOST}:{_SPLUNK_VALIDATOR_PORT}/services/search/jobs"
        test_query = f"{query} | head {max_results}"
        if "earliest=" not in query.lower():
            test_query = f"earliest=-5m latest=now {test_query}"

        response = requests.post(
            url,
            auth=(_SPLUNK_VALIDATOR_USER, _SPLUNK_VALIDATOR_PASS),
            data={
                "search": f"search {test_query}" if not test_query.strip().startswith("|") else test_query,
                "output_mode": "json",
                "exec_mode": "oneshot",
                "max_count": max_results,
                "timeout": 30,
            },
            verify=_ssl_verify,
            timeout=35,
        )

        result["available"] = True

        if response.status_code == 200:
            result["executed"] = True
            data = response.json()
            if "results" in data:
                result["sample_results"] = data["results"][:max_results]
            if "messages" in data:
                for msg in data["messages"]:
                    msg_type = msg.get("type", "").upper()
                    msg_text = msg.get("text", "")
                    if msg_type == "ERROR":
                        result["errors"].append(msg_text)
                        result["executed"] = False
                    elif msg_type in ("WARN", "WARNING"):
                        result["warnings"].append(msg_text)
        else:
            result["executed"] = False
            try:
                error_data = response.json()
                if "messages" in error_data:
                    for msg in error_data["messages"]:
                        result["errors"].append(msg.get("text", str(msg)))
                else:
                    result["errors"].append(str(error_data))
            except Exception:
                result["errors"].append(response.text[:500])

    except Exception as e:
        if "ConnectionError" in type(e).__name__:
            result["available"] = False
            result["reason"] = f"Cannot connect to Splunk validator at {_SPLUNK_VALIDATOR_HOST}:{_SPLUNK_VALIDATOR_PORT}"
        elif isinstance(e, ImportError):
            result["available"] = False
            result["reason"] = "requests library not installed"
        else:
            result["available"] = True
            result["errors"].append(f"Execution error: {str(e)}")

    return result


def run_btool_via_container(conf_type: str = "check") -> Dict[str, Any]:
    """Run btool via the Splunk validator container using docker exec."""
    result = {
        "available": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }

    docker_cmd = "podman" if shutil.which("podman") else "docker"
    container_name = os.getenv("SPLUNK_VALIDATOR_CONTAINER", "splunk-validator")

    try:
        cmd = [docker_cmd, "exec", container_name, "/opt/splunk/bin/splunk", "btool"] + conf_type.split()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        result["available"] = True
        result["returncode"] = proc.returncode
        result["stdout"] = proc.stdout[:4000]
        result["stderr"] = proc.stderr[:2000]
    except FileNotFoundError:
        result["reason"] = f"{docker_cmd} not found"
    except subprocess.TimeoutExpired:
        result["reason"] = "btool timed out after 30s"
    except Exception as e:
        result["reason"] = str(e)

    return result


def get_splunk_validator_status() -> Dict[str, Any]:
    """Check if the Splunk validator container is available and healthy."""
    result = {
        "available": False,
        "healthy": False,
        "host": _SPLUNK_VALIDATOR_HOST,
        "port": _SPLUNK_VALIDATOR_PORT,
    }

    try:
        import requests
        from urllib3.exceptions import InsecureRequestWarning
        import urllib3
        urllib3.disable_warnings(InsecureRequestWarning)

        url = f"https://{_SPLUNK_VALIDATOR_HOST}:{_SPLUNK_VALIDATOR_PORT}/services/server/info"
        response = requests.get(
            url,
            auth=(_SPLUNK_VALIDATOR_USER, _SPLUNK_VALIDATOR_PASS),
            params={"output_mode": "json"},
            verify=_ssl_verify,
            timeout=5,
        )

        result["available"] = True

        if response.status_code == 200:
            result["healthy"] = True
            data = response.json()
            if "entry" in data and data["entry"]:
                content = data["entry"][0].get("content", {})
                result["version"] = content.get("version", "unknown")
                result["server_name"] = content.get("serverName", "unknown")
                result["license_state"] = content.get("licenseState", "unknown")
        else:
            result["error"] = f"Unexpected status: {response.status_code}"

    except Exception as e:
        if "ConnectionError" in type(e).__name__:
            result["reason"] = "Connection refused"
        elif isinstance(e, ImportError):
            result["reason"] = "requests library not installed"
        else:
            result["reason"] = str(e)

    return result
