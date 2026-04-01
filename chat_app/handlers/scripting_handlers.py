"""Scripting handlers — Ansible, Shell, Python scripting skill delegates.

Extracted from skill_executor.py (batch 4) for modularity.
Each handler follows: def handler(user_input: str = "", **kwargs) -> str

Exports HANDLERS dict for auto-registration.
"""


def _handler_ansible_validate(user_input: str = "", **kwargs) -> str:
    from skills.ansible_ops.skill import ansible_validate_playbook
    result = ansible_validate_playbook(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_ansible_generate(user_input: str = "", **kwargs) -> str:
    from skills.ansible_ops.skill import ansible_generate_playbook
    result = ansible_generate_playbook(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_ansible_explain(user_input: str = "", **kwargs) -> str:
    from skills.ansible_ops.skill import ansible_explain_playbook
    result = ansible_explain_playbook(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_ansible_improve(user_input: str = "", **kwargs) -> str:
    from skills.ansible_ops.skill import ansible_improve_playbook
    result = ansible_improve_playbook(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_ansible_reference(user_input: str = "", **kwargs) -> str:
    from skills.ansible_ops.skill import ansible_module_reference
    result = ansible_module_reference(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_shell_analyze(user_input: str = "", **kwargs) -> str:
    from skills.shell_scripting.skill import shell_analyze_script
    result = shell_analyze_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_shell_generate(user_input: str = "", **kwargs) -> str:
    from skills.shell_scripting.skill import shell_generate_script
    result = shell_generate_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_shell_improve(user_input: str = "", **kwargs) -> str:
    from skills.shell_scripting.skill import shell_improve_script
    result = shell_improve_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_shell_explain(user_input: str = "", **kwargs) -> str:
    from skills.shell_scripting.skill import shell_explain_script
    result = shell_explain_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_python_analyze(user_input: str = "", **kwargs) -> str:
    from skills.python_scripting.skill import python_analyze_script
    result = python_analyze_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_python_generate(user_input: str = "", **kwargs) -> str:
    from skills.python_scripting.skill import python_generate_script
    result = python_generate_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_python_improve(user_input: str = "", **kwargs) -> str:
    from skills.python_scripting.skill import python_improve_script
    result = python_improve_script(user_input, **kwargs)
    return result.get("output", str(result))

def _handler_python_explain(user_input: str = "", **kwargs) -> str:
    from skills.python_scripting.skill import python_explain_script
    result = python_explain_script(user_input, **kwargs)
    return result.get("output", str(result))


HANDLERS = {
    "ansible_validate_playbook": _handler_ansible_validate,
    "ansible_generate_playbook": _handler_ansible_generate,
    "ansible_explain_playbook": _handler_ansible_explain,
    "ansible_improve_playbook": _handler_ansible_improve,
    "ansible_module_reference": _handler_ansible_reference,
    "shell_analyze_script": _handler_shell_analyze,
    "shell_generate_script": _handler_shell_generate,
    "shell_improve_script": _handler_shell_improve,
    "shell_explain_script": _handler_shell_explain,
    "python_analyze_script": _handler_python_analyze,
    "python_generate_script": _handler_python_generate,
    "python_improve_script": _handler_python_improve,
    "python_explain_script": _handler_python_explain,
}
