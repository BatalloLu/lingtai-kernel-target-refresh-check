"""Idle-episode regressions: real state/wake/molt owners, fake provider only.

No sleeps, live providers, or background Agent threads. The serialized run loop
is driven synchronously for one turn; the injected lifecycle clock owns time.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from lingtai.kernel.base_agent import BaseAgent, turn
from lingtai.kernel.base_agent.lifecycle import _maybe_notify_auto_molt
from lingtai.kernel.config import auto_molt_idle_seconds
from lingtai.kernel.llm.base import LLMResponse
from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock, ToolResultBlock
from lingtai.kernel.message import Message, MSG_REQUEST, MSG_TC_WAKE, MSG_USER_INPUT
from lingtai.kernel.meta_block import commit_delivered_notification_sources
from lingtai.kernel.state import AgentState
from lingtai.tools.context._molt import _context_molt
from tests._agent_presence_helpers import make_test_presence_store
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._molt_helpers import write_session_journal
from tests._notification_store_helpers import notification_store_for, publish_test_payload
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
    # Session persistence is unrelated to the latch; keep the canonical wire
    # real, without asking this provider-free chat double for adapter history.
    monkeypatch.setattr(agent, "_save_chat_history", lambda **kw: None)
    yield agent, clock
    agent.stop(timeout=1.0)


def _events(agent):
    payload = agent._notification_store.snapshot(lambda ch: ch == "system")
    return [
        event for event in payload.get("system", {}).get("data", {}).get("events", [])
        if event["source"] == "system.auto_molt"
    ]


def _drive_one_turn(agent, monkeypatch):
    """Run the real dequeue/state/admission/handler path with a fake send."""
    sends = []

    def send(payload):
        sends.append(payload)
        agent._chat.interface.add_assistant_message([TextBlock(text="observed")])
        return LLMResponse(text="observed")

    real_handler = turn._handle_message

    def one_handler(owner, msg):
        try:
            return real_handler(owner, msg)
        finally:
            owner._shutdown.set()

    with monkeypatch.context() as patch:
        patch.setattr(agent._session, "send", send)
        patch.setattr(turn, "_handle_message", one_handler)
        agent._shutdown.clear()
        turn._run_loop_body(agent)
        agent._shutdown.clear()
    assert agent.state == AgentState.IDLE
    return sends


def _publish_and_deliver(agent, clock):
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    agent._sync_notifications()
    assert not agent.inbox.empty()


def test_reminder_own_wake_then_idle_never_repeats(idle_agent, monkeypatch):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    episode = agent._auto_molt_episode
    assert _drive_one_turn(agent, monkeypatch) == [None]
    assert agent._auto_molt_episode == episode
    clock.advance_monotonic(2000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    assert agent.inbox.empty()
    assert agent._molt_count == 0
    assert not (agent._working_dir / "knowledge" / "session-journal").exists()


def test_actual_molt_and_post_molt_wake_do_not_rearm(idle_agent, monkeypatch):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    _drive_one_turn(agent, monkeypatch)
    episode = agent._auto_molt_episode
    agent._set_state(AgentState.ACTIVE)
    journal = write_session_journal(agent)
    args = {"summary": "No pending work; wait for real input.",
            "session_journal_path": journal, "_tc_id": "idle_molt", "keep_last": 0}
    agent._chat.interface.add_assistant_message([
        ToolCallBlock(id="idle_molt", name="context", args=args),
    ])
    result = _context_molt(agent, args)
    assert result.get("status") == "ok"
    assert agent._molt_count == 1
    agent._chat.interface.add_tool_results([
        ToolResultBlock(id="idle_molt", name="context", content=result),
    ])
    agent._set_state(AgentState.IDLE)
    agent._sync_notifications()
    assert _drive_one_turn(agent, monkeypatch) == [None]
    assert agent._auto_molt_episode == episode
    clock.advance_monotonic(2000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    assert agent._molt_count == 1


@pytest.mark.parametrize("kind,sender", [(MSG_USER_INPUT, "user"), (MSG_REQUEST, "peer")])
def test_real_new_message_rearms_one_episode(idle_agent, monkeypatch, kind, sender):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    _drive_one_turn(agent, monkeypatch)
    episode = agent._auto_molt_episode
    agent.inbox.put(Message(type=kind, sender=sender, content="new authorized work"))
    assert len(_drive_one_turn(agent, monkeypatch)) == 1
    assert agent._auto_molt_episode == episode + 1
    clock.advance_monotonic(999)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    clock.advance_monotonic(1)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2
    agent._sync_notifications()
    assert _drive_one_turn(agent, monkeypatch) == [None]
    clock.advance_monotonic(2000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2



@pytest.mark.parametrize("kind,sender", [(MSG_USER_INPUT, "user"), (MSG_REQUEST, "peer")])
def test_real_work_behind_system_request_rearms_once(idle_agent, monkeypatch, kind, sender):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    _drive_one_turn(agent, monkeypatch)
    episode = agent._auto_molt_episode
    agent.inbox.put(Message(type=MSG_REQUEST, sender="system", content="internal recovery"))
    agent.inbox.put(Message(type=kind, sender=sender, content="new authorized work"))
    assert len(_drive_one_turn(agent, monkeypatch)) == 1
    assert agent._auto_molt_episode == episode + 1
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2


def test_admitted_correlated_task_rearms(idle_agent, monkeypatch):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    _drive_one_turn(agent, monkeypatch)
    episode = agent._auto_molt_episode
    handle = agent.submit_turn("new task", correlation_id="idle-next-task")
    assert len(_drive_one_turn(agent, monkeypatch)) == 1
    assert handle.done()
    assert agent._auto_molt_episode == episode + 1
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2


def test_internal_system_request_does_not_rearm(idle_agent, monkeypatch):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    _drive_one_turn(agent, monkeypatch)
    episode = agent._auto_molt_episode
    agent.inbox.put(Message(type=MSG_REQUEST, sender="system", content="internal recovery"))
    _drive_one_turn(agent, monkeypatch)
    assert agent._auto_molt_episode == episode
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1


@pytest.mark.parametrize("channel", ["email", "daemon", "bash", "cron", "mcp.telegram", "mcp.peer"])
def test_new_notification_work_rearms_but_unchanged_delivery_does_not(idle_agent, channel):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    episode = agent._auto_molt_episode
    payload = {channel: {"header": "new work", "data": {"count": 1}}}
    commit_delivered_notification_sources(agent, payload)
    assert agent._auto_molt_episode == episode + 1
    commit_delivered_notification_sources(agent, payload)
    assert agent._auto_molt_episode == episode + 1
    agent._set_state(AgentState.ACTIVE)
    agent._set_state(AgentState.IDLE)
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2


def test_old_system_work_does_not_rearm_for_new_maintenance_event(idle_agent):
    agent, clock = idle_agent
    old = {"event_id": "old-mail", "source": "email", "body": "delivered"}
    commit_delivered_notification_sources(agent, {"system": {"data": {"events": [old]}}})
    agent._set_state(AgentState.ACTIVE)
    agent._set_state(AgentState.IDLE)
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    episode = agent._auto_molt_episode
    auto = _events(agent)[0]
    commit_delivered_notification_sources(agent, {"system": {"data": {"events": [old, auto]}}})
    assert agent._auto_molt_episode == episode
    assert agent._auto_molt_notified_since == agent._inactive_since_monotonic


def test_new_human_notification_uses_real_sync_wake_owner(idle_agent, monkeypatch):
    agent, clock = idle_agent
    _publish_and_deliver(agent, clock)
    _drive_one_turn(agent, monkeypatch)
    episode = agent._auto_molt_episode
    publish_test_payload(agent._working_dir, "mcp.telegram", {
        "header": "incoming", "data": {"message_ids": ["new-human-1"]},
    })
    agent._sync_notifications()
    assert agent._auto_molt_episode == episode + 1
    assert _drive_one_turn(agent, monkeypatch) == [None]
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2


@pytest.mark.parametrize("source", ["email", "email.bounce", "mcp.peer", "daemon", "system.sleep_alarm"])
def test_new_system_work_event_rearms(idle_agent, source):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    episode = agent._auto_molt_episode
    commit_delivered_notification_sources(agent, {"system": {"data": {"events": [
        {"event_id": "work-1", "source": source, "body": "new work"},
    ]}}})
    assert agent._auto_molt_episode == episode + 1


def test_failed_notification_splice_does_not_rearm(idle_agent, monkeypatch):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    agent._sync_notifications()
    # Consume the own wake without introducing new work.
    assert agent.inbox.get_nowait().type == MSG_TC_WAKE
    episode = agent._auto_molt_episode
    publish_test_payload(agent._working_dir, "mcp.peer", {"header": "pending work"})
    monkeypatch.setattr(agent, "_inject_notification_pair", lambda payloads: False)
    monkeypatch.setattr(agent, "_heal_pending_tool_calls", lambda **kw: False)
    agent._sync_notifications()
    assert agent._auto_molt_episode == episode


@pytest.mark.parametrize("channel", ["post-molt", "memory-length", "molt", "nudge", "goal", "tool_loop_guard"])
def test_maintenance_notices_do_not_rearm(idle_agent, channel):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    episode = agent._auto_molt_episode
    commit_delivered_notification_sources(agent, {channel: {"header": "maintenance"}})
    assert agent._auto_molt_episode == episode


@pytest.mark.parametrize("state", [AgentState.ACTIVE, AgentState.STUCK, AgentState.SUSPENDED, AgentState.ASLEEP])
def test_state_churn_retains_success_latch(idle_agent, state):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    agent._set_state(state)
    agent._set_state(AgentState.IDLE)
    clock.advance_monotonic(2000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1


def test_idle_asleep_continuity_and_notification_wake(idle_agent, monkeypatch):
    agent, clock = idle_agent
    clock.advance_monotonic(500)
    agent._set_state(AgentState.ASLEEP)
    agent._asleep.set()
    clock.advance_monotonic(500)
    _maybe_notify_auto_molt(agent)
    agent._sync_notifications()
    assert not agent._asleep.is_set()
    assert _drive_one_turn(agent, monkeypatch) == [None]
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1


def test_publish_failure_retries_and_only_success_latches(idle_agent, monkeypatch):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    with monkeypatch.context() as patch:
        def fail(**kwargs):
            raise OSError("test failure")
        patch.setattr(agent, "_enqueue_system_notification", fail)
        _maybe_notify_auto_molt(agent)
    assert agent._auto_molt_notified_since is None
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1
    assert agent._auto_molt_notified_since == agent._inactive_since_monotonic
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 1


def test_old_publish_success_cannot_latch_later_real_episode(idle_agent, monkeypatch):
    agent, clock = idle_agent
    clock.advance_monotonic(1000)
    publish = agent._enqueue_system_notification

    def interleaved_publish(**kwargs):
        result = publish(**kwargs)
        # Model a real inbound delivery interleaving between publish and latch.
        # Reuse the exact monotonic anchor to prove generation, not time, wins.
        commit_delivered_notification_sources(agent, {"mcp.peer": {"header": "new work"}})
        agent._set_state(AgentState.ACTIVE)
        clock.set_monotonic(0)
        agent._set_state(AgentState.IDLE)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(agent, "_enqueue_system_notification", interleaved_publish)
        _maybe_notify_auto_molt(agent)
    assert agent._auto_molt_notified_since is None
    clock.set_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert len(_events(agent)) == 2
    assert len({event["ref_id"] for event in _events(agent)}) == 2


def test_inactivity_never_bypasses_journal_or_forces_shed(idle_agent):
    agent, clock = idle_agent
    before = agent._chat.interface.to_dict()
    clock.advance_monotonic(1000)
    _maybe_notify_auto_molt(agent)
    assert agent._molt_count == 0
    assert agent._chat.interface.to_dict() == before
    result = _context_molt(agent, {"summary": "idle", "_tc_id": "missing"})
    assert "error" in result
    assert agent._molt_count == 0
    assert agent._chat.interface.to_dict() == before
    body = _events(agent)[0]["body"]
    assert "valid actionable molt reason" in body
    assert "valid session journal" in body
    assert "defer the molt" in body
    assert "remain IDLE" in body


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
        assert guidance.count("system.auto_molt") >= 2
        assert "defer the molt" in guidance
        service.create_session.assert_not_called()
        service.generate.assert_not_called()
    finally:
        agent.stop(timeout=1.0)
