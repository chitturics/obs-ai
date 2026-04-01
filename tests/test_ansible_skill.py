"""Tests for Ansible skill package."""
import pytest
from unittest.mock import patch


class TestAnsibleValidate:
    def test_valid_playbook(self):
        from skills.ansible_ops.skill import ansible_validate_playbook
        yaml_content = """---
- name: Test
  hosts: all
  tasks:
    - name: Install pkg
      apt:
        name: nginx
        state: present
"""
        result = ansible_validate_playbook(yaml_content)
        assert "output" in result

    def test_invalid_yaml(self):
        from skills.ansible_ops.skill import ansible_validate_playbook
        result = ansible_validate_playbook("not: valid: yaml: [[[")
        assert "output" in result

    def test_empty_input(self):
        from skills.ansible_ops.skill import ansible_validate_playbook
        result = ansible_validate_playbook("")
        assert "output" in result

    def test_non_list_playbook(self):
        from skills.ansible_ops.skill import ansible_validate_playbook
        result = ansible_validate_playbook("key: value\nfoo: bar")
        assert "output" in result

    def test_best_practices_check(self):
        from skills.ansible_ops.skill import ansible_validate_playbook
        yaml_content = """---
- name: Test
  hosts: all
  tasks:
    - name: Run command
      command: rm -rf /tmp/stuff
"""
        result = ansible_validate_playbook(yaml_content, check_best_practices=True)
        output = result.get("output", "")
        assert len(output) > 0


class TestAnsibleGenerate:
    @patch("skills.ansible_ops.skill._get_llm", return_value=None)
    def test_generate_basic(self, _mock_llm):
        from skills.ansible_ops.skill import ansible_generate_playbook
        result = ansible_generate_playbook("install nginx on all servers")
        assert "output" in result
        output = result.get("output", "")
        assert "name:" in output.lower() or "hosts:" in output.lower()

    def test_generate_docker(self):
        from skills.ansible_ops.skill import ansible_generate_playbook
        result = ansible_generate_playbook("setup docker containers")
        assert "output" in result

    def test_generate_user(self):
        from skills.ansible_ops.skill import ansible_generate_playbook
        result = ansible_generate_playbook("create user accounts")
        assert "output" in result

    def test_generate_empty(self):
        from skills.ansible_ops.skill import ansible_generate_playbook
        result = ansible_generate_playbook("")
        assert "output" in result


class TestAnsibleExplain:
    def test_explain_playbook(self):
        from skills.ansible_ops.skill import ansible_explain_playbook
        yaml_content = """---
- name: Setup
  hosts: webservers
  become: true
  tasks:
    - name: Install nginx
      apt:
        name: nginx
        state: present
    - name: Start nginx
      service:
        name: nginx
        state: started
"""
        result = ansible_explain_playbook(yaml_content)
        assert "output" in result
        output = result.get("output", "")
        assert "play" in output.lower() or "task" in output.lower()


class TestAnsibleImprove:
    def test_improve_playbook(self):
        from skills.ansible_ops.skill import ansible_improve_playbook
        yaml_content = """---
- name: Bad playbook
  hosts: all
  tasks:
    - command: apt install nginx
    - shell: systemctl start nginx
"""
        result = ansible_improve_playbook(yaml_content)
        assert "output" in result


class TestAnsibleModuleReference:
    def test_module_reference(self):
        from skills.ansible_ops.skill import ansible_module_reference
        result = ansible_module_reference("copy")
        assert "output" in result

    def test_unknown_module(self):
        from skills.ansible_ops.skill import ansible_module_reference
        result = ansible_module_reference("nonexistent_module_xyz")
        assert "output" in result

    def test_all_modules(self):
        from skills.ansible_ops.skill import ansible_module_reference
        result = ansible_module_reference("all")
        assert "output" in result
        assert len(result.get("output", "")) > 100
