"""Tests for persona skill priorities, approval bypasses, and versioning."""

import pytest


@pytest.fixture(autouse=True)
def reset_personas(monkeypatch):
    """Reset persona state between tests."""
    import chat_app.user_persona as mod
    monkeypatch.setattr(mod, "_loaded", False)
    monkeypatch.setattr(mod, "_personas", {})


class TestSkillPriorityTags:

    def test_technical_expert_priorities(self):
        from chat_app.user_persona import get_skill_priority_tags
        tags = get_skill_priority_tags("technical_expert")
        assert "cognitive" in tags
        assert "io" in tags

    def test_executive_priorities(self):
        from chat_app.user_persona import get_skill_priority_tags
        tags = get_skill_priority_tags("executive_summary")
        assert "communication" in tags

    def test_tutorial_priorities(self):
        from chat_app.user_persona import get_skill_priority_tags
        tags = get_skill_priority_tags("tutorial_mode")
        assert "social" in tags

    def test_unknown_persona_empty(self):
        from chat_app.user_persona import get_skill_priority_tags
        tags = get_skill_priority_tags("nonexistent")
        assert tags == []


class TestApprovalBypass:

    def test_security_analyst_bypass(self):
        from chat_app.user_persona import get_approval_bypass_intents
        intents = get_approval_bypass_intents("security_analyst")
        assert "security" in intents
        assert "config_health_check" in intents

    def test_default_no_bypass(self):
        from chat_app.user_persona import get_approval_bypass_intents
        intents = get_approval_bypass_intents("technical_expert")
        assert intents == []

    def test_unknown_persona_no_bypass(self):
        from chat_app.user_persona import get_approval_bypass_intents
        intents = get_approval_bypass_intents("nonexistent")
        assert intents == []


class TestPersonaVersioning:

    def test_initial_version(self):
        from chat_app.user_persona import get_persona
        persona = get_persona("technical_expert")
        assert persona.version == 1

    def test_bump_version(self):
        from chat_app.user_persona import bump_persona_version, get_persona
        new_version = bump_persona_version("technical_expert")
        assert new_version == 2
        persona = get_persona("technical_expert")
        assert persona.version == 2

    def test_bump_nonexistent(self):
        from chat_app.user_persona import bump_persona_version
        result = bump_persona_version("nonexistent")
        assert result is None


class TestPersonaDataclass:

    def test_persona_has_new_fields(self):
        from chat_app.user_persona import get_persona
        persona = get_persona("technical_expert")
        d = persona.to_dict()
        assert "skill_priority_tags" in d
        assert "approval_bypass_intents" in d
        assert "version" in d

    def test_all_personas_have_priorities(self):
        from chat_app.user_persona import list_personas
        for persona in list_personas():
            assert isinstance(persona.skill_priority_tags, list)
            assert isinstance(persona.approval_bypass_intents, list)
            assert isinstance(persona.version, int)
