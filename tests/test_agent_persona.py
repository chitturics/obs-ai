"""Tests for enhanced agent persona system."""
import pytest
from chat_app.agent_catalog import (
    AgentPersona, Department, ExpertiseLevel,
    DEPT_DIRECTIVES, EXPERTISE_STYLES,
)


class TestDeptDirectives:
    def test_all_departments_covered(self):
        for dept in Department:
            assert dept.value in DEPT_DIRECTIVES, f"Missing directive for {dept.value}"

    def test_directives_non_empty(self):
        for dept, directive in DEPT_DIRECTIVES.items():
            assert len(directive) > 20, f"Directive too short for {dept}"


class TestExpertiseStyles:
    def test_all_levels_covered(self):
        for level in ExpertiseLevel:
            assert level.value in EXPERTISE_STYLES, f"Missing style for {level.value}"

    def test_styles_non_empty(self):
        for level, style in EXPERTISE_STYLES.items():
            assert len(style) > 20, f"Style too short for {level}"


class TestEnhancedPromptFragment:
    def test_includes_role(self):
        a = AgentPersona(
            role="ops engineer", name="ops_eng",
            description="Handles operations",
            department=Department.OPERATIONS,
        )
        prompt = a.get_system_prompt_fragment()
        assert "Ops Engineer" in prompt

    def test_includes_department_directive(self):
        a = AgentPersona(
            role="coder", name="coder",
            description="Writes code",
            department=Department.ENGINEERING,
        )
        prompt = a.get_system_prompt_fragment()
        assert "Engineering" in prompt
        assert "code quality" in prompt.lower()

    def test_includes_expertise_style(self):
        a = AgentPersona(
            role="expert", name="expert",
            description="Expert",
            department=Department.KNOWLEDGE,
            expertise=ExpertiseLevel.EXPERT,
        )
        prompt = a.get_system_prompt_fragment()
        assert "Expert" in prompt

    def test_includes_personality(self):
        a = AgentPersona(
            role="helper", name="helper",
            description="Helps users",
            department=Department.SUPPORT,
            personality="Friendly and patient.",
        )
        prompt = a.get_system_prompt_fragment()
        assert "Friendly and patient" in prompt

    def test_includes_skills(self):
        a = AgentPersona(
            role="analyst", name="analyst",
            description="Analyzes data",
            department=Department.DATA,
            skills=["analyze_spl", "optimize_spl"],
        )
        prompt = a.get_system_prompt_fragment()
        assert "analyze_spl" in prompt

    def test_multi_section_format(self):
        a = AgentPersona(
            role="architect", name="arch",
            description="Designs systems",
            department=Department.ENGINEERING,
            expertise=ExpertiseLevel.LEAD,
            personality="Strategic thinker.",
            skills=["design", "review"],
        )
        prompt = a.get_system_prompt_fragment()
        assert "## Agent Role" in prompt
        assert "## Department Directive" in prompt
        assert "## Expertise Level" in prompt
        assert "## Personality" in prompt
        assert "## Core Skills" in prompt

    def test_new_agents_have_rich_prompts(self):
        from chat_app.agent_catalog import AGENT_CATALOG
        for agent in AGENT_CATALOG:
            prompt = agent.get_system_prompt_fragment()
            assert len(prompt) > 100, f"Agent {agent.name} prompt too short ({len(prompt)} chars)"
            assert "## Agent Role" in prompt

    def test_ansible_engineer_exists(self):
        from chat_app.agent_catalog import get_agent_catalog
        cat = get_agent_catalog()
        agent = cat.get("ansible_engineer")
        assert agent is not None
        assert agent.department == Department.OPERATIONS

    def test_shell_scripter_exists(self):
        from chat_app.agent_catalog import get_agent_catalog
        cat = get_agent_catalog()
        agent = cat.get("shell_scripter")
        assert agent is not None

    def test_python_developer_exists(self):
        from chat_app.agent_catalog import get_agent_catalog
        cat = get_agent_catalog()
        agent = cat.get("python_developer")
        assert agent is not None


class TestAgentQuality:
    def test_record_quality(self):
        from chat_app.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher.__new__(AgentDispatcher)
        d._agent_quality = {}
        d.record_quality("test_agent", "test_intent", 0.8)
        assert "test_agent" in d._agent_quality
        assert d._agent_quality["test_agent"]["test_intent"] == [0.8]

    def test_quality_clamp(self):
        from chat_app.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher.__new__(AgentDispatcher)
        d._agent_quality = {}
        d.record_quality("agent", "intent", 1.5)
        assert d._agent_quality["agent"]["intent"] == [1.0]
        d.record_quality("agent", "intent", -0.5)
        assert d._agent_quality["agent"]["intent"][-1] == 0.0

    def test_quality_history_limit(self):
        from chat_app.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher.__new__(AgentDispatcher)
        d._agent_quality = {}
        for i in range(60):
            d.record_quality("agent", "intent", 0.5)
        assert len(d._agent_quality["agent"]["intent"]) == 30
