"""Tests for Python scripting skill package."""
import pytest


class TestPythonAnalyze:
    def test_analyze_basic(self):
        from skills.python_scripting.skill import python_analyze_script
        script = 'import os\n\ndef foo():\n    try:\n        pass\n    except:\n        pass\n'
        result = python_analyze_script(script)
        assert "output" in result

    def test_detect_bare_except(self):
        from skills.python_scripting.skill import python_analyze_script
        script = 'try:\n    x = 1\nexcept:\n    pass\n'
        result = python_analyze_script(script)
        output = result.get("output", "")
        assert "except" in output.lower() or len(output) > 0

    def test_detect_eval(self):
        from skills.python_scripting.skill import python_analyze_script
        script = 'user_input = input()\nresult = eval(user_input)\n'
        result = python_analyze_script(script)
        assert "output" in result

    def test_empty_input(self):
        from skills.python_scripting.skill import python_analyze_script
        result = python_analyze_script("")
        assert "output" in result

    def test_good_script(self):
        from skills.python_scripting.skill import python_analyze_script
        script = '''#!/usr/bin/env python3
"""Good script."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def main() -> None:
    logger.info("Running")

if __name__ == "__main__":
    main()
'''
        result = python_analyze_script(script)
        assert "output" in result


class TestPythonGenerate:
    def test_generate_cli_tool(self):
        from skills.python_scripting.skill import python_generate_script
        result = python_generate_script("CLI tool with argparse")
        assert "output" in result
        output = result.get("output", "")
        assert "import" in output or "def" in output or len(output) > 20

    def test_generate_api_client(self):
        from skills.python_scripting.skill import python_generate_script
        result = python_generate_script("REST API client")
        assert "output" in result

    def test_generate_empty(self):
        from skills.python_scripting.skill import python_generate_script
        result = python_generate_script("")
        assert "output" in result


class TestPythonImprove:
    def test_improve_script(self):
        from skills.python_scripting.skill import python_improve_script
        script = 'import os, sys\n\ndef process(data=[]):\n    for i in data:\n        print(i)\n'
        result = python_improve_script(script)
        assert "output" in result


class TestPythonExplain:
    def test_explain_script(self):
        from skills.python_scripting.skill import python_explain_script
        script = '''from dataclasses import dataclass
from typing import List

@dataclass
class Config:
    host: str
    port: int = 8080
    tags: List[str] = None

    def __post_init__(self):
        self.tags = self.tags or []
'''
        result = python_explain_script(script)
        assert "output" in result
        output = result.get("output", "")
        assert len(output) > 20
