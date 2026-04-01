"""Tests for chat_app.user_profiles — Adaptive user intelligence profiles."""

import pytest
from datetime import datetime

from chat_app.user_profiles import (
    UserProfile,
    UserProfileManager,
    get_profile_manager,
)


# ---------------------------------------------------------------------------
# UserProfile tests
# ---------------------------------------------------------------------------

class TestUserProfile:
    def test_creation(self):
        p = UserProfile(user_id="user1")
        assert p.user_id == "user1"
        assert p.query_count == 0
        assert p.expertise == {}
        assert p.preferred_verbosity == "normal"

    def test_expertise_level_beginner(self):
        p = UserProfile(user_id="user1")
        assert p.expertise_level == "beginner"

    def test_expertise_level_intermediate(self):
        p = UserProfile(user_id="user1", expertise={"spl": 0.5, "config": 0.5})
        assert p.expertise_level == "intermediate"

    def test_expertise_level_expert(self):
        p = UserProfile(user_id="user1", expertise={"spl": 0.9, "admin": 0.8})
        assert p.expertise_level == "expert"

    def test_reformulation_rate_zero(self):
        p = UserProfile(user_id="user1")
        assert p.reformulation_rate == 0.0

    def test_reformulation_rate_nonzero(self):
        p = UserProfile(user_id="user1", query_count=10, reformulation_count=3)
        assert abs(p.reformulation_rate - 0.3) < 1e-9

    def test_get_personalization_prompt_expert(self):
        p = UserProfile(user_id="user1", expertise={"spl": 0.9, "admin": 0.8})
        prompt = p.get_personalization_prompt()
        assert "expert" in prompt.lower()
        assert "concise" in prompt.lower()

    def test_get_personalization_prompt_beginner(self):
        p = UserProfile(user_id="user1")
        prompt = p.get_personalization_prompt()
        assert "learning" in prompt.lower()

    def test_get_personalization_prompt_code_first(self):
        p = UserProfile(user_id="user1", preferred_format="code_first")
        prompt = p.get_personalization_prompt()
        assert "code" in prompt.lower()

    def test_get_personalization_prompt_terse(self):
        p = UserProfile(user_id="user1", preferred_verbosity="terse")
        prompt = p.get_personalization_prompt()
        assert "brief" in prompt.lower()

    def test_to_dict(self):
        p = UserProfile(user_id="user1", query_count=5,
                        expertise={"spl": 0.6})
        d = p.to_dict()
        assert d["user_id"] == "user1"
        assert d["query_count"] == 5
        assert d["expertise_level"] == "intermediate"
        assert "reformulation_rate" in d


# ---------------------------------------------------------------------------
# UserProfileManager tests
# ---------------------------------------------------------------------------

class TestUserProfileManager:
    def test_get_profile_creates_new(self):
        mgr = UserProfileManager()
        p = mgr.get_profile("user1")
        assert p.user_id == "user1"
        assert p.query_count == 0

    def test_get_profile_returns_existing(self):
        mgr = UserProfileManager()
        p1 = mgr.get_profile("user1")
        p1.query_count = 5
        p2 = mgr.get_profile("user1")
        assert p2.query_count == 5
        assert p1 is p2

    def test_record_query_increments_count(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "test query", "general_qa")
        p = mgr.get_profile("user1")
        assert p.query_count == 1

    def test_record_query_updates_last_active(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "test query", "general_qa")
        p = mgr.get_profile("user1")
        assert p.last_active != ""

    def test_record_query_tracks_intents(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "q1", "spl_generation")
        mgr.record_query("user1", "q2", "spl_generation")
        mgr.record_query("user1", "q3", "config_lookup")
        p = mgr.get_profile("user1")
        assert p.frequent_intents["spl_generation"] == 2
        assert p.frequent_intents["config_lookup"] == 1

    def test_record_query_tracks_topics(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "q1", "general_qa", topics=["spl", "stats"])
        p = mgr.get_profile("user1")
        assert p.frequent_topics["spl"] == 1
        assert p.frequent_topics["stats"] == 1

    def test_record_query_updates_response_time(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "q1", "general_qa", response_time_ms=100)
        mgr.record_query("user1", "q2", "general_qa", response_time_ms=200)
        p = mgr.get_profile("user1")
        assert p.avg_response_time_ms > 0

    def test_expertise_detection_spl_advanced(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "use tstats with datamodel acceleration",
                         "spl_generation")
        p = mgr.get_profile("user1")
        assert "spl" in p.expertise
        assert p.expertise["spl"] > 0

    def test_expertise_detection_config(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "show me props.conf stanza settings",
                         "config_lookup")
        p = mgr.get_profile("user1")
        assert "splunk_config" in p.expertise

    def test_expertise_detection_cribl(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "configure cribl pipeline for syslog",
                         "cribl_config")
        p = mgr.get_profile("user1")
        assert "cribl" in p.expertise

    def test_detect_reformulation(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "first query", "general_qa")
        mgr.detect_reformulation("user1",
                                  "show me failed logins by src_ip",
                                  "show failed logins by src_ip address")
        p = mgr.get_profile("user1")
        assert p.reformulation_count == 1

    def test_detect_reformulation_no_match(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "first query", "general_qa")
        mgr.detect_reformulation("user1",
                                  "configure props.conf",
                                  "show me failed logins")
        p = mgr.get_profile("user1")
        assert p.reformulation_count == 0

    def test_list_profiles(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "q1", "general_qa")
        mgr.record_query("user2", "q2", "spl_generation")
        profiles = mgr.list_profiles()
        assert len(profiles) == 2
        assert all("user_id" in p for p in profiles)

    def test_verbosity_detection_terse(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "briefly explain stats command", "general_qa")
        p = mgr.get_profile("user1")
        assert p.preferred_verbosity == "terse"

    def test_verbosity_detection_detailed(self):
        mgr = UserProfileManager()
        mgr.record_query("user1", "explain in detail how tstats works", "general_qa")
        p = mgr.get_profile("user1")
        assert p.preferred_verbosity == "detailed"


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_profile_manager_singleton(self):
        import chat_app.user_profiles as mod
        mod._manager = None  # Reset
        m1 = get_profile_manager()
        m2 = get_profile_manager()
        assert m1 is m2
        mod._manager = None  # Cleanup
