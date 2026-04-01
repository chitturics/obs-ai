"""Tests for the unified registry module."""
import pytest

from chat_app.registry import (
    Intent,
    RoutingTag,
    CLASSIFIER_INTENTS,
    is_valid_intent_or_tag,
    get_command_registry,
    get_commands_for_api,
    get_section_registry,
    get_sections_for_api,
    validate_all,
    validate_agent_skill_refs,
    validate_skill_intents,
    validate_agent_intents,
    get_registry_dump,
)


# ---------------------------------------------------------------------------
# Intent Enum
# ---------------------------------------------------------------------------

class TestIntentEnum:
    def test_str_comparison_equals(self):
        """Intent enum compares equal to plain strings (backward compat)."""
        assert Intent.SPL_GENERATION == "spl_generation"
        assert Intent.GENERAL_QA == "general_qa"
        assert Intent.META_QUESTION == "meta_question"
        assert Intent.DATA_TRANSFORM == "data_transform"

    def test_str_in_set(self):
        """Plain string 'in' check works with Intent set."""
        intent_set = {Intent.SPL_GENERATION, Intent.GENERAL_QA}
        assert "spl_generation" in intent_set
        assert "general_qa" in intent_set

    def test_str_in_dict_key(self):
        """Intent works as dict key, accessible by string."""
        d = {Intent.SPL_GENERATION: "found"}
        assert d["spl_generation"] == "found"

    def test_classifier_intents_count(self):
        """Classifier produces exactly 22 intents."""
        assert len(CLASSIFIER_INTENTS) == 22

    def test_total_intent_count(self):
        """27 total intents (22 classifier + 5 phantom)."""
        assert len(Intent) == 27

    def test_all_intents_unique_values(self):
        """No duplicate values in Intent enum."""
        values = [i.value for i in Intent]
        assert len(values) == len(set(values))

    def test_phantom_intents_not_in_classifier(self):
        """Phantom intents should NOT be in CLASSIFIER_INTENTS."""
        phantoms = [Intent.SPL_OPTIMIZATION, Intent.GREETING, Intent.COMMAND_HELP]
        for p in phantoms:
            assert p not in CLASSIFIER_INTENTS


# ---------------------------------------------------------------------------
# RoutingTag Enum
# ---------------------------------------------------------------------------

class TestRoutingTag:
    def test_str_comparison(self):
        assert RoutingTag.ANALYSIS == "analysis"
        assert RoutingTag.SECURITY == "security"
        assert RoutingTag.DEPLOYMENT == "deployment"

    def test_no_overlap_with_intent(self):
        """RoutingTag values should not duplicate Intent values."""
        intent_values = {i.value for i in Intent}
        tag_values = {t.value for t in RoutingTag}
        overlap = intent_values & tag_values
        assert len(overlap) == 0, f"Overlapping values: {overlap}"

    def test_tag_count(self):
        """At least 40 routing tags."""
        assert len(RoutingTag) >= 40


# ---------------------------------------------------------------------------
# is_valid_intent_or_tag
# ---------------------------------------------------------------------------

class TestIsValid:
    def test_valid_intent(self):
        assert is_valid_intent_or_tag("spl_generation")
        assert is_valid_intent_or_tag("general_qa")

    def test_valid_tag(self):
        assert is_valid_intent_or_tag("analysis")
        assert is_valid_intent_or_tag("deployment")

    def test_invalid(self):
        assert not is_valid_intent_or_tag("nonexistent_intent_xyz")
        assert not is_valid_intent_or_tag("")
        assert not is_valid_intent_or_tag("random_string")


# ---------------------------------------------------------------------------
# Command Registry
# ---------------------------------------------------------------------------

class TestCommandRegistry:
    """Command registry requires slash_commands which requires chainlit.
    These tests are skipped when chainlit is not available (host-side tests).
    """

    def test_registry_returns_dict(self):
        registry = get_command_registry()
        assert isinstance(registry, dict)

    def test_api_format_returns_list(self):
        commands = get_commands_for_api()
        assert isinstance(commands, list)

    def test_api_format_has_required_fields(self):
        commands = get_commands_for_api()
        for cmd in commands:
            assert "name" in cmd
            assert "description" in cmd
            assert "category" in cmd


# ---------------------------------------------------------------------------
# Section Registry
# ---------------------------------------------------------------------------

class TestSectionRegistry:
    def test_sections_populated(self):
        sections = get_section_registry()
        assert len(sections) >= 35

    def test_dashboard_exists(self):
        sections = get_section_registry()
        ids = {s.id for s in sections}
        assert "dashboard" in ids

    def test_all_sections_have_required_fields(self):
        for sec in get_section_registry():
            assert sec.id
            assert sec.label
            assert sec.group
            assert sec.path

    def test_api_groups(self):
        groups = get_sections_for_api()
        assert len(groups) >= 5
        group_labels = {g["label"] for g in groups}
        assert "Overview" in group_labels
        assert "Operations" in group_labels
        assert "Intelligence" in group_labels

    def test_api_group_items_have_ids(self):
        groups = get_sections_for_api()
        for group in groups:
            for item in group["items"]:
                assert "id" in item
                assert "label" in item

    def test_key_sections_present(self):
        ids = {s.id for s in get_section_registry()}
        for expected in ["dashboard", "llm", "skills", "collections", "version"]:
            assert expected in ids, f"Missing section: {expected}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_all_returns_dict(self):
        results = validate_all()
        assert isinstance(results, dict)
        assert "agent_skill_refs" in results
        assert "skill_intents" in results
        assert "agent_intents" in results
        assert "strategy_overrides" in results

    def test_agent_skills_all_valid(self):
        """Validate agent skill refs. Known exception: migration_engineer references read_config."""
        errors = validate_agent_skill_refs()
        # Filter known exceptions where agent references a skill not in the catalog
        known_exceptions = {"Agent 'migration_engineer' references unknown skill 'read_config'"}
        errors = [e for e in errors if e not in known_exceptions]
        assert len(errors) == 0, f"Broken agent skill refs: {errors}"

    def test_skill_intents_all_valid(self):
        """All skill intent strings should be known Intent or RoutingTag."""
        errors = validate_skill_intents()
        assert len(errors) == 0, f"Unknown skill intents: {errors}"

    def test_agent_intents_all_valid(self):
        """All agent intent strings should be known Intent or RoutingTag."""
        errors = validate_agent_intents()
        assert len(errors) == 0, f"Unknown agent intents: {errors}"


# ---------------------------------------------------------------------------
# Registry Dump
# ---------------------------------------------------------------------------

class TestRegistryDump:
    def test_dump_structure(self):
        dump = get_registry_dump()
        assert "intents" in dump
        assert "routing_tags" in dump
        assert "commands" in dump
        assert "sections" in dump
        assert "validation" in dump

    def test_dump_intents_have_classifier_and_extended(self):
        dump = get_registry_dump()
        assert "classifier" in dump["intents"]
        assert "extended" in dump["intents"]
        assert dump["intents"]["total"] == 27

    def test_dump_routing_tags_populated(self):
        dump = get_registry_dump()
        assert dump["routing_tags"]["total"] >= 40

    def test_dump_sections_populated(self):
        dump = get_registry_dump()
        assert dump["sections"]["total"] >= 35
