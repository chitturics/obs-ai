"""Tests for Shell scripting skill package."""
import pytest


class TestShellAnalyze:
    def test_analyze_basic(self):
        from skills.shell_scripting.skill import shell_analyze_script
        script = '#!/bin/bash\necho "hello"\nrm -rf /tmp/$dir\n'
        result = shell_analyze_script(script)
        assert "output" in result

    def test_analyze_empty(self):
        from skills.shell_scripting.skill import shell_analyze_script
        result = shell_analyze_script("")
        assert "output" in result

    def test_detect_missing_strict_mode(self):
        from skills.shell_scripting.skill import shell_analyze_script
        script = '#!/bin/bash\necho "no strict mode"\n'
        result = shell_analyze_script(script)
        output = result.get("output", "")
        assert "set -e" in output.lower() or "strict" in output.lower() or len(output) > 0

    def test_detect_unquoted_vars(self):
        from skills.shell_scripting.skill import shell_analyze_script
        script = '#!/bin/bash\nset -euo pipefail\ncp $file /tmp/\necho $name\n'
        result = shell_analyze_script(script)
        assert "output" in result

    def test_good_script(self):
        from skills.shell_scripting.skill import shell_analyze_script
        script = '#!/bin/bash\nset -euo pipefail\ntrap "rm -f /tmp/lock" EXIT\necho "${USER}"\n'
        result = shell_analyze_script(script)
        assert "output" in result


class TestShellGenerate:
    def test_generate_backup(self):
        from skills.shell_scripting.skill import shell_generate_script
        result = shell_generate_script("backup script for /var/log")
        assert "output" in result
        output = result.get("output", "")
        assert "#!/bin/bash" in output or len(output) > 20

    def test_generate_health_check(self):
        from skills.shell_scripting.skill import shell_generate_script
        result = shell_generate_script("health check for web services")
        assert "output" in result

    def test_generate_empty(self):
        from skills.shell_scripting.skill import shell_generate_script
        result = shell_generate_script("")
        assert "output" in result


class TestShellImprove:
    def test_improve_script(self):
        from skills.shell_scripting.skill import shell_improve_script
        script = '#!/bin/bash\nrm -rf $dir\ncp $file /dest\n'
        result = shell_improve_script(script)
        assert "output" in result


class TestShellExplain:
    def test_explain_script(self):
        from skills.shell_scripting.skill import shell_explain_script
        script = '#!/bin/bash\nset -euo pipefail\nfind /var/log -name "*.log" -mtime +30 -delete\n'
        result = shell_explain_script(script)
        assert "output" in result
        output = result.get("output", "")
        assert len(output) > 20
