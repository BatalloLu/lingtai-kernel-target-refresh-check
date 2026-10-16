"""Context-agnostic inactivity reminder; fake provider and injected clock.

No live providers or background Agent loops. Historical episode coverage is
retired, not preserved as an alternative runtime policy.
"""
from types import SimpleNamespace

import pytest

from lingtai.kernel.base_agent import BaseAgent
from lingtai.kernel.base_agent.lifecycle import _maybe_notify_auto_molt
from lingtai.kernel.config import auto_molt_idle_seconds
from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock
from lingtai.kernel.state import AgentState
from lingtai.tools.context._molt import _context_molt
from tests._agent_presence_helpers import make_test_presence_store
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._molt_helpers import write_session_journal
from tests._notification_store_helpers import notification_store_for
from tests._service_helpers import make_mock_llm_service
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._workdir_lease_helpers import make_test_lease


@pytest.fixture
def idle_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", "1000")
    clock = make_test_lifecycle_clock()
    service = make_mock_llm_service()
    service.provider, service.model = "openai", "test-model"
    agent = BaseAgent(
        service=service, agent_name="idle-test", working_dir=tmp_path,
        intrinsics={}, workdir_lease=make_test_lease(),
        notification_store=notification_store_for(tmp_path),
        agent_presence=make_test_presence_store(), lifecycle_clock=clock,
        snapshot_port=make_test_snapshot_port(),
        source_revision_port=make_test_source_revision_port(),
    )

    def ensure_chat():
        if agent._session._chat is None:
            agent._session._chat = SimpleNamespace(
                interface=ChatInterface(), close=lambda: None,
                context_window=lambda: 128_000,
            )
        return agent._session._chat

    monkeypatch.setattr(agent._session, "ensure_session", ensure_chat)
    ensure_chat()
    # Keep canonical wire state without provider adapter persistence.
    monkeypatch.setattr(agent, "_save_chat_history", lambda **kw: None)
    yield agent, clock
    agent.stop(timeout=1.0)


def _events(agent):
    payload = agent._notification_store.snapshot(lambda ch: ch == "system")
    return [
        event for event in payload.get("system", {}).get("data", {}).get("events", [])
        if event["source"] == "system.auto_molt"
    ]


@pytest.mark.parametrize("tokens,elapsed,eligible", [
    (0, 1000, True), (99999, 1000, True), (100000, 1000, True),
    (100001, 999, False), (100001, 1000, True),
])
def test_context_agnostic_time_boundary(idle_agent, monkeypatch, tokens, elapsed, eligible):
    agent, clock = idle_agent
    # Neither current context nor spending/provider snapshots own publication.
    agent._session._total_input_tokens = 9000000
    agent._session._latest_input_tokens = 9000000
    monkeypatch.setattr(agent._chat.interface, "estimate_context_tokens", lambda: tokens)
    clock.advance_monotonic(elapsed)
    _maybe_notify_auto_molt(agent)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == int(eligible)
    assert agent._molt_count == 0


def test_asleep_continuity_and_existing_sync_wake(idle_agent, monkeypatch):
    agent, clock = idle_agent
    monkeypatch.setattr(agent._chat.interface, "estimate_context_tokens", lambda: 100001)
    since = agent._inactive_since_monotonic
    clock.advance_monotonic(500)
    agent._set_state(AgentState.ASLEEP)
    agent._set_state(AgentState.IDLE)
    agent._set_state(AgentState.ASLEEP)
    agent._asleep.set()
    clock.advance_monotonic(500)
    _maybe_notify_auto_molt(agent)
    assert agent._inactive_since_monotonic == since
    assert len(_events(agent)) == 1
    agent._sync_notifications()
    assert not agent._asleep.is_set()
    agent._set_state(AgentState.ACTIVE)
    assert agent._inactive_since_monotonic is None
    assert agent._auto_molt_notified_since is None


@pytest.mark.parametrize("unknown", ["unloaded", "error", None])
def test_unknown_context_does_not_create_session(idle_agent, monkeypatch, unknown):
    agent, clock = idle_agent
    def forbidden():
        pytest.fail("heartbeat created a session")
    monkeypatch.setattr(agent._session, "ensure_session", forbidden)
    if unknown == "unloaded":
        agent._session._chat = None
    else:
        def estimate():
            if unknown == "error":
                pytest.fail("producer must not estimate context")
            return None
        monkeypatch.setattr(agent._chat.interface, "estimate_context_tokens", estimate)
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    assert agent._auto_molt_notified_since == agent._inactive_since_monotonic
    agent.service.create_session.assert_not_called()
    agent.service.generate.assert_not_called()


@pytest.mark.parametrize("state", [AgentState.ACTIVE, AgentState.STUCK])
def test_busy_state_suppresses_reminder(idle_agent, state):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    agent._set_state(state)
    _maybe_notify_auto_molt(agent)
    assert not _events(agent)
    assert agent._inactive_since_monotonic is None
    assert agent._auto_molt_notified_since is None


def test_failed_publish_retries_and_journal_is_still_required(idle_agent, monkeypatch):
    agent, clock = idle_agent
    monkeypatch.setattr(agent._chat.interface, "estimate_context_tokens", lambda: 100001)
    before = agent._chat.interface.to_dict()
    clock.advance_monotonic(1000)
    with monkeypatch.context() as patch:
        def fail(**kwargs):
            raise OSError("test failure")
        patch.setattr(agent, "_enqueue_system_notification", fail)
        _maybe_notify_auto_molt(agent)
    assert agent._auto_molt_notified_since is None
    _maybe_notify_auto_molt(agent)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    assert agent._auto_molt_notified_since == agent._inactive_since_monotonic
    assert "valid session journal" in _events(agent)[0]["body"]
    assert "defer the molt" in _events(agent)[0]["body"]
    result = _context_molt(agent, {"summary": "idle", "_tc_id": "missing"})
    assert "error" in result
    assert agent._molt_count == 0
    assert agent._chat.interface.to_dict() == before


def test_actual_molt_below_boundary_still_gets_later_reminder(idle_agent, monkeypatch):
    agent, clock = idle_agent
    # Exercise the existing canonical estimator deterministically, not a new one.
    monkeypatch.setattr("lingtai.kernel.token_counter.count_tokens", len)
    old_chat = agent._chat
    old_chat.interface.add_user_blocks([TextBlock(text="x" * 100001)])
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    agent._set_state(AgentState.ACTIVE)
    args = {"summary": "Wait for real input.", "session_journal_path": write_session_journal(agent),
            "_tc_id": "idle_molt", "keep_last": 0}
    old_chat.interface.add_assistant_message([ToolCallBlock(id="idle_molt", name="context", args=args)])
    assert _context_molt(agent, args).get("status") == "ok"
    assert agent._chat is not old_chat
    assert agent._chat.interface.estimate_context_tokens() < 100000
    # Small replacement context still gets a vanilla reminder in the next period.
    agent._session._latest_input_tokens = 9000000
    agent._set_state(AgentState.IDLE)
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2
    assert agent._auto_molt_notified_since == agent._inactive_since_monotonic
    body = _events(agent)[-1]["body"]
    assert "strictly above 100000" in body
    assert "no tools, external reply, or molt" in body
    assert agent._molt_count == 1


@pytest.mark.parametrize("raw,expected", [(None, 1800), ("1000", 1000), ("1800", 1800),
    ("", 1800), ("bad", 1800), ("0", 1800), ("-1", 1800), ("nan", 1800),
    ("inf", 1800), ("-inf", 1800)])
def test_positive_finite_threshold_and_default_unchanged(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", raising=False)
    else:
        monkeypatch.setenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", raw)
    assert auto_molt_idle_seconds() == expected


def test_real_agent_startup_and_complete_prompt_build_load_idle_guidance(tmp_path):
    import json
    from unittest.mock import patch
    from lingtai.agent import Agent
    from lingtai.init_reader import read_init

    (tmp_path / "init.json").write_text(json.dumps({
        "manifest": {"llm": {"provider": "openai", "model": "gpt-6.1-sol"}},
        "pad": "", "addons": [],
    }))
    assert read_init(tmp_path).status.name == "FULLY_EFFECTIVE"
    service = make_mock_llm_service()
    service.provider, service.model = "openai", "gpt-6.1-sol"
    agent = Agent(service=service, agent_name="idle-guidance", working_dir=tmp_path,
                  capabilities=[], addons=[])
    try:
        with patch("lingtai.agent.LLMService", return_value=service):
            agent._setup_from_init()
        prompt = agent._build_system_prompt()
        assert isinstance(prompt, str) and prompt.strip()
        principle = agent._prompt_manager.read_section("principle")
        guidance = agent._prompt_manager.read_section("meta_guidance")
        assert "system.auto_molt" in principle
        assert "valid session journal" in principle
        assert "remain IDLE" in principle
        for loaded in (principle, guidance):
            assert "CURRENT context >100000" in loaded
            assert "no tools, external reply, or molt" in loaded
            assert "Real work always" in loaded
        assert guidance.count("system.auto_molt") >= 2
        assert "defer the molt" in guidance
        service.create_session.assert_not_called()
        service.generate.assert_not_called()
    finally:
        agent.stop(timeout=1.0)
