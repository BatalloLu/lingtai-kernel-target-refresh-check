"""Heartbeat-only cache-warm cadence: injected clock, no provider sends."""
from types import SimpleNamespace

import pytest

from lingtai.agent import Agent
from lingtai.kernel.base_agent import BaseAgent
from lingtai.kernel.base_agent.lifecycle import _maybe_notify_cache_warm
from lingtai.kernel.llm.interface import ChatInterface
from lingtai.kernel.message import MSG_REQUEST, _make_message
from lingtai.kernel.state import AgentState
from lingtai.tools.system import settings
from tests._agent_presence_helpers import make_test_presence_store
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._notification_store_helpers import FakeNotificationStore
from tests._service_helpers import make_mock_llm_service
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._workdir_lease_helpers import make_test_lease


@pytest.fixture
def warm_agent(tmp_path, monkeypatch):
    monkeypatch.delenv(settings.CACHE_WARM_INTERVAL_ENV, raising=False)
    clock = make_test_lifecycle_clock()
    agent = BaseAgent(
        service=make_mock_llm_service(), agent_name="warm-test", working_dir=tmp_path,
        intrinsics={}, workdir_lease=make_test_lease(),
        notification_store=FakeNotificationStore(),
        agent_presence=make_test_presence_store(), lifecycle_clock=clock,
        snapshot_port=make_test_snapshot_port(),
        source_revision_port=make_test_source_revision_port(),
    )
    agent._heartbeat_runtime_ready = True
    monkeypatch.setattr(agent, "resolve_cache_warm_interval", lambda: settings.resolve_cache_warm_interval(tmp_path))
    monkeypatch.setattr(agent, "_save_chat_history", lambda **kw: None)
    # Sync has a real canonical interface, but cannot reach a provider.
    chat = SimpleNamespace(interface=ChatInterface(), close=lambda: None, context_window=lambda: 128000)
    agent._session._chat = chat
    monkeypatch.setattr(agent._session, "ensure_session", lambda: chat)
    monkeypatch.setattr(agent._session, "send", lambda *a, **kw: pytest.fail("producer/sync sent to provider"))
    yield agent, clock
    agent.stop(timeout=1.0)


def events(agent):
    return agent._notification_store.snapshot(lambda ch: ch == "system").get("system", {}).get("data", {}).get("events", [])


@pytest.mark.parametrize("state", [AgentState.ACTIVE, AgentState.IDLE, AgentState.ASLEEP])
def test_first_tick_waits_then_one_per_cadence_without_catchup(warm_agent, state):
    agent, clock = warm_agent
    agent._set_state(state)
    clock.set_monotonic(10000)  # constructor/host uptime is not the anchor
    _maybe_notify_cache_warm(agent)
    assert not events(agent)
    clock.advance_monotonic(3599)
    clock.set_wall(-1e9)  # wall jumps cannot make it due
    _maybe_notify_cache_warm(agent)
    assert not events(agent)
    clock.advance_monotonic(1)
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 1
    first = events(agent)[0]
    assert first["source"] == "system.cache_warm"
    assert first["ref_id"].startswith("cache_warm:")
    assert "no tools, reply, or molt; go IDLE" in first["body"]
    assert "Real work always wins" in first["body"]
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 1
    clock.advance_monotonic(36000)
    _maybe_notify_cache_warm(agent)
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 1
    assert events(agent)[0]["ref_id"] != first["ref_id"]
    assert agent._state == state  # producer itself never wakes/sleeps/cancels


@pytest.mark.parametrize("gate", ["stuck", "suspended", "shutdown", "not_ready"])
def test_no_dispatch_during_recovery_shutdown_or_boot(warm_agent, gate):
    agent, clock = warm_agent
    _maybe_notify_cache_warm(agent)
    clock.advance_monotonic(3600)
    if gate in ("stuck", "suspended"):
        agent._set_state(AgentState(gate))
    elif gate == "shutdown":
        agent._shutdown.set()
    else:
        agent._heartbeat_runtime_ready = False
    _maybe_notify_cache_warm(agent)
    assert not events(agent)
    if gate == "stuck":
        agent._set_state(AgentState.ACTIVE)
        _maybe_notify_cache_warm(agent)
        assert len(events(agent)) == 1


def test_live_tuning_disable_and_reenable_wait_full_interval(warm_agent, tmp_path):
    agent, clock = warm_agent
    path = tmp_path / settings.SYSTEM_SETTINGS_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    _maybe_notify_cache_warm(agent)
    clock.advance_monotonic(10)
    path.write_text('{"schema_version":2,"cache_warm_interval":10}')
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 1
    first_ref = events(agent)[0]["ref_id"]
    path.write_text('{"schema_version":2,"cache_warm_interval":100}')
    clock.advance_monotonic(20)
    _maybe_notify_cache_warm(agent)
    assert events(agent)[0]["ref_id"] == first_ref  # longer interval defers
    path.write_text('{"schema_version":2,"cache_warm_interval":0}')
    clock.advance_monotonic(10000)
    _maybe_notify_cache_warm(agent)
    assert events(agent)[0]["ref_id"] == first_ref
    path.write_text('{"schema_version":2,"cache_warm_interval":20}')
    _maybe_notify_cache_warm(agent)
    clock.advance_monotonic(19)
    _maybe_notify_cache_warm(agent)
    assert events(agent)[0]["ref_id"] == first_ref
    clock.advance_monotonic(1)
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 1
    assert events(agent)[0]["ref_id"] != first_ref


@pytest.mark.parametrize("after_write", [False, True])
def test_publish_failure_retries_same_identity_and_foreign_ref_cannot_suppress(warm_agent, monkeypatch, after_write):
    agent, clock = warm_agent
    _maybe_notify_cache_warm(agent)
    clock.advance_monotonic(3600)
    enqueue = agent._enqueue_system_notification
    calls = []

    def fail(**kw):
        calls.append(kw)
        if after_write:
            enqueue(**kw)  # ambiguous successful write followed by exception
        raise OSError("test publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(agent, "_enqueue_system_notification", fail)
        _maybe_notify_cache_warm(agent)
    pending = agent._cache_warm_ref_id
    assert pending == calls[0]["ref_id"]
    enqueue(source="real.work", ref_id=pending, body="Do not drop this work")
    _maybe_notify_cache_warm(agent)
    assert agent._cache_warm_ref_id is None
    assert len([e for e in events(agent) if e["source"] == "system.cache_warm"]) == 1
    assert len([e for e in events(agent) if e["source"] == "real.work"]) == 1
    assert next(e for e in events(agent) if e["source"] == "system.cache_warm")["ref_id"] == pending
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 2


def test_active_sync_preserves_busy_wire_and_concurrent_inbox_work(warm_agent):
    agent, clock = warm_agent
    agent._set_state(AgentState.ACTIVE)
    work = _make_message(MSG_REQUEST, "human", "Finish the real task")
    agent.inbox.put(work)
    wire = agent._chat.interface.to_dict()
    _maybe_notify_cache_warm(agent)
    clock.advance_monotonic(3600)
    _maybe_notify_cache_warm(agent)
    agent._sync_notifications()
    assert agent._state == AgentState.ACTIVE
    assert not agent._cancel_event.is_set()
    assert agent._chat.interface.to_dict() == wire
    assert agent.inbox.get_nowait() is work
    assert agent.inbox.empty()
    assert agent._molt_count == 0


def test_asleep_uses_existing_normal_sync_wake(warm_agent):
    agent, clock = warm_agent
    agent._set_state(AgentState.ASLEEP)
    agent._asleep.set()
    _maybe_notify_cache_warm(agent)
    clock.advance_monotonic(3600)
    _maybe_notify_cache_warm(agent)
    assert agent._asleep.is_set()
    agent._sync_notifications()
    assert agent._state == AgentState.IDLE
    assert not agent._asleep.is_set()
    assert not agent.inbox.empty()


@pytest.mark.parametrize("raw", ["-1", "NaN", "Infinity", "true", "off", "", "bad"])
def test_invalid_env_falls_through_and_valid_env_wins(tmp_path, monkeypatch, raw):
    path = tmp_path / settings.SYSTEM_SETTINGS_RELATIVE_PATH
    path.parent.mkdir()
    path.write_text('{"schema_version":2,"cache_warm_interval":12.5}')
    monkeypatch.setenv(settings.CACHE_WARM_INTERVAL_ENV, raw)
    assert settings.resolve_cache_warm_interval(tmp_path) == 12.5
    monkeypatch.setenv(settings.CACHE_WARM_INTERVAL_ENV, "0")
    assert settings.resolve_cache_warm_interval(tmp_path) == 0
    monkeypatch.setenv(settings.CACHE_WARM_INTERVAL_ENV, "1.25")
    assert settings.resolve_cache_warm_interval(tmp_path) == 1.25


@pytest.mark.parametrize("field", ["true", "false", "null", "-1", "NaN", "Infinity", '"10"', "1" + "0" * 400])
def test_invalid_field_rejects_whole_v2(tmp_path, monkeypatch, field):
    monkeypatch.delenv(settings.CACHE_WARM_INTERVAL_ENV, raising=False)
    path = tmp_path / settings.SYSTEM_SETTINGS_RELATIVE_PATH
    path.parent.mkdir()
    path.write_text('{"schema_version":2,"max_rpm":7,"cache_warm_interval":' + field + '}')
    assert settings.read_runtime_policy_document(tmp_path) == {}
    assert settings.resolve_cache_warm_interval(tmp_path) == 3600
    monkeypatch.setenv(settings.CACHE_WARM_INTERVAL_ENV, "15")
    assert settings.resolve_cache_warm_interval(tmp_path) == 15


@pytest.mark.parametrize("text", [
    '{"schema_version":1,"cache_miss_budget":123}',
    '{"schema_version":1,"cache_miss_budget":123,"cache_warm_interval":0}',
    '{"schema_version":2,"cache_warm_interval":0,"cache_warm_interval":1}',
    '{"schema_version":2,"cache_warm_interval":0,"unknown":1}',
    '{"schema_version":2,"cache_warm_interval":0,"max_rpm":false}',
    'not json',
])
def test_v1_not_widened_and_invalid_v2_never_partially_applies(tmp_path, monkeypatch, text):
    monkeypatch.delenv(settings.CACHE_WARM_INTERVAL_ENV, raising=False)
    path = tmp_path / settings.SYSTEM_SETTINGS_RELATIVE_PATH
    path.parent.mkdir()
    path.write_text(text)
    assert settings.resolve_cache_warm_interval(tmp_path) == 3600
    assert settings._parse_settings(text) == (123 if text == '{"schema_version":1,"cache_miss_budget":123}' else None)


def test_default_and_outer_scalar_hook(tmp_path, monkeypatch):
    monkeypatch.delenv(settings.CACHE_WARM_INTERVAL_ENV, raising=False)
    assert settings.resolve_cache_warm_interval(tmp_path) == 3600
    assert BaseAgent.resolve_cache_warm_interval(object()) == 3600
    monkeypatch.setattr(settings, "resolve_cache_warm_interval", lambda root: 17 if root == tmp_path else -1)
    assert Agent.resolve_cache_warm_interval(SimpleNamespace(_working_dir=tmp_path)) == 17


def test_eligible_state_changes_do_not_reset_cadence(warm_agent):
    agent, clock = warm_agent
    _maybe_notify_cache_warm(agent)
    for state in (AgentState.ASLEEP, AgentState.ACTIVE):
        clock.advance_monotonic(1200)
        agent._set_state(state)
        _maybe_notify_cache_warm(agent)
        assert not events(agent)
    clock.advance_monotonic(1200)
    agent._set_state(AgentState.IDLE)
    _maybe_notify_cache_warm(agent)
    assert len(events(agent)) == 1


@pytest.mark.parametrize("real_count", [1, 20])
def test_repeated_warm_ticks_never_evict_real_system_events(warm_agent, monkeypatch, real_count):
    agent, clock = warm_agent
    agent._set_state(AgentState.ACTIVE)
    monkeypatch.setattr(agent, "resolve_cache_warm_interval", lambda: 1)
    for i in range(real_count):
        agent._enqueue_system_notification(source="real.work", ref_id=f"real:{i}", body=f"Real work {i}")
    originals = [e.copy() for e in events(agent)]
    _maybe_notify_cache_warm(agent)
    for _ in range(25):
        clock.advance_monotonic(1)
        _maybe_notify_cache_warm(agent)
    assert [e for e in events(agent) if e["source"] == "real.work"] == originals
    assert len([e for e in events(agent) if e["source"] == "system.cache_warm"]) == (0 if real_count == 20 else 1)
    assert agent._state == AgentState.ACTIVE
    assert not agent._cancel_event.is_set()
