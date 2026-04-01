"""Tests for the enterprise agentic framework — capabilities, guardrails, protocol, assessment."""

import pytest


# ---------------------------------------------------------------------------
# Agent Data Model Tests
# ---------------------------------------------------------------------------

class TestAgentCapabilities:

    def test_default_capabilities(self):
        from chat_app.agent_catalog import AgentCapabilities
        cap = AgentCapabilities()
        assert cap.can_ask_clarification is True
        assert cap.can_write is False
        assert cap.max_concurrent_skills == 3

    def test_agent_has_capabilities(self):
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        agents = catalog.get_all_agents() if hasattr(catalog, "get_all_agents") else list(catalog._agents.values())
        for agent in agents[:5]:
            assert hasattr(agent, "capabilities")
            assert hasattr(agent, "guardrails")
            assert hasattr(agent, "data_sources")

    def test_to_dict_includes_enterprise_fields(self):
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        agents = catalog.get_all_agents() if hasattr(catalog, "get_all_agents") else list(catalog._agents.values())
        d = agents[0].to_dict()
        assert "capabilities" in d
        assert "guardrails" in d
        assert "data_sources" in d
        assert "can_ask_clarification" in d["capabilities"]
        assert "read_only" in d["guardrails"]
        assert "collections" in d["data_sources"]

    def test_system_prompt_includes_clarification(self):
        from chat_app.agent_catalog import get_agent_catalog
        catalog = get_agent_catalog()
        agents = catalog.get_all_agents() if hasattr(catalog, "get_all_agents") else list(catalog._agents.values())
        prompt = agents[0].get_system_prompt_fragment()
        assert "Clarification Protocol" in prompt or "clarif" in prompt.lower()


# ---------------------------------------------------------------------------
# Agent Protocol Tests
# ---------------------------------------------------------------------------

class TestBlackboard:

    def test_create_blackboard(self):
        from chat_app.agent_protocol import get_comm_bus
        bus = get_comm_bus()
        board = bus.create_blackboard("run1", "search for errors", "splunk_search")
        assert board.run_id == "run1"
        assert board.user_query == "search for errors"
        assert board.intent == "splunk_search"

    def test_contribute(self):
        from chat_app.agent_protocol import Blackboard
        board = Blackboard(run_id="r1", user_query="test", intent="general_qa")
        board.contribute("spl_expert", "Found 42 errors in index=main")
        assert "spl_expert" in board.agent_contributions
        assert len(board.messages) == 1

    def test_request_clarification(self):
        from chat_app.agent_protocol import Blackboard
        board = Blackboard(run_id="r1", user_query="search", intent="splunk_search")
        msg = board.request_clarification("spl_expert", "Which time range?")
        assert msg.message_type.value == "clarify"
        assert msg.recipient == "user"
        assert board.has_pending_clarifications

    def test_get_context_for_agent(self):
        from chat_app.agent_protocol import Blackboard
        board = Blackboard(run_id="r1", user_query="test query", intent="general_qa")
        board.contribute("agent_a", "Result from A")
        board.contribute("agent_b", "Result from B")
        context = board.get_context_for_agent("agent_a")
        assert "agent_b" in context
        assert "Result from B" in context
        assert "agent_a" not in context  # Shouldn't include own contribution

    def test_blackboard_to_dict(self):
        from chat_app.agent_protocol import Blackboard
        board = Blackboard(run_id="r1", user_query="test", intent="general_qa")
        board.contribute("agent_a", "output")
        d = board.to_dict()
        assert d["run_id"] == "r1"
        assert d["message_count"] == 1


class TestAgentMessage:

    def test_create_message(self):
        from chat_app.agent_protocol import AgentMessage, MessageType
        msg = AgentMessage(
            message_type=MessageType.DELEGATE,
            sender_agent="spl_expert",
            recipient="security_guard",
            content="Check for security incidents",
        )
        assert msg.message_id  # Auto-generated
        assert msg.timestamp   # Auto-generated
        assert msg.message_type == MessageType.DELEGATE

    def test_send_message(self):
        from chat_app.agent_protocol import AgentCommunicationBus, AgentMessage, MessageType
        bus = AgentCommunicationBus()
        board = bus.create_blackboard("r1", "test", "general_qa")
        bus.send(AgentMessage(
            message_type=MessageType.REQUEST,
            sender_agent="agent_a",
            recipient="agent_b",
            content="Please help",
            workflow_run_id="r1",
        ))
        assert len(board.messages) == 1
        assert bus.get_stats()["total_messages"] == 1


# ---------------------------------------------------------------------------
# Self-Assessment Tests
# ---------------------------------------------------------------------------

class TestPreAssessment:

    def _make_agent(self, intents=None, skills=None):
        from chat_app.agent_catalog import AgentPersona, Department, ExpertiseLevel, AgentDataSources
        return AgentPersona(
            role="test", name="test_agent", description="Test",
            department=Department.ENGINEERING,
            intents=intents or ["splunk_search", "general_qa"],
            skills=skills or ["search", "explain", "analyze"],
            data_sources=AgentDataSources(collections=["spl_docs"]),
        )

    def test_high_confidence_specific_query(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()
        agent = self._make_agent()
        result = assessor.assess_pre(agent, "splunk_search",
                                     "index=main sourcetype=syslog ERROR | stats count by host",
                                     retrieved_chunks=10)
        assert result.confidence > 0.5
        assert result.should_ask_user is False

    def test_low_confidence_vague_query(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()
        agent = self._make_agent()
        result = assessor.assess_pre(agent, "general_qa", "help", retrieved_chunks=0)
        assert result.confidence < 0.6  # Vague query scores lower
        assert len(result.clarification_questions) > 0 or len(result.knowledge_gaps) > 0

    def test_intent_mismatch_lowers_confidence(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()
        agent = self._make_agent(intents=["splunk_search"])
        result = assessor.assess_pre(agent, "ansible", "deploy playbook", retrieved_chunks=5)
        assert result.confidence < 0.6


class TestPostAssessment:

    def _make_agent(self):
        from chat_app.agent_catalog import AgentPersona, Department
        return AgentPersona(role="test", name="test_agent", description="Test",
                           department=Department.ENGINEERING)

    def test_all_skills_succeed(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()

        class MockResult:
            success = True
        results = [MockResult(), MockResult(), MockResult()]

        assessment = assessor.assess_post(self._make_agent(), "splunk_search", results)
        assert assessment.confidence > 0.6
        assert assessment.should_delegate is False

    def test_all_skills_fail(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()

        class MockResult:
            success = False
        results = [MockResult(), MockResult()]

        assessment = assessor.assess_post(self._make_agent(), "splunk_search", results)
        assert assessment.confidence < 0.5

    def test_assessment_history(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()

        class MockResult:
            success = True

        from chat_app.agent_catalog import AgentPersona, Department
        agent = AgentPersona(role="t", name="test", description="t", department=Department.ENGINEERING)
        assessor.assess_pre(agent, "general_qa", "test query", 5)
        assessor.assess_post(agent, "general_qa", [MockResult()])

        history = assessor.get_history()
        assert len(history) == 2

    def test_assessment_stats(self):
        from chat_app.agent_self_assessment import AgentSelfAssessor
        assessor = AgentSelfAssessor()
        stats = assessor.get_stats()
        assert "total_assessments" in stats
