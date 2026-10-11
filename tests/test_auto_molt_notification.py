"""Inactivity auto-molt reminder: one notification per IDLE/ASLEEP period."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from lingtai.kernel.base_agent import BaseAgent
from lingtai.kernel.base_agent import lifecycle as lifecycle_mod
from lingtai.kernel import config as config_mod
from lingtai.kernel.state import AgentState
from lingtai.tools.registry import INTRINSICS as _TEST_INTRINSICS
from tests._agent_presence_helpers import make_test_presence_store
from tests._lifecycle_clock_helpers import FakeLifecycleClock
from tests._notification_store_helpers import FakeNotificationStore
from tests._service_helpers import make_tool_result_mock_service
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._workdir_lease_helpers import make_test_lease

_SOURCE = "system.auto_molt"


def _make_agent(tmp_path, clock, store) -> BaseAgent:
    return BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_tool_result_mock_service(),
        agent_name="auto-molt-agent",
        working_dir=tmp_path / "auto_molt_agent",
        workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(),
        agent_presence=make_test_presence_store(),
        lifecycle_clock=clock,
        source_revision_port=make_test_source_revision_port(),
        notification_store=store,
    )


def _events(store: FakeNotificationStore) -> list[dict]:
    data = store.snapshot(lambda _channel: True).get("system", {}).get("data", {})
    return [e for e in data.get("events", []) if e.get("source") == _SOURCE]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", raising=False)
    clock = FakeLifecycleClock(wall=1_000.0, monotonic=0.0)
    store = FakeNotificationStore()
    return _make_agent(tmp_path, clock, store), clock, store


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, 1800.0),
        ("", 1800.0),
        ("   ", 1800.0),
        ("soon", 1800.0),
        ("nan", 1800.0),
        ("inf", 1800.0),
        ("0", 1800.0),
        ("-5", 1800.0),
        ("60", 60.0),
        (" 0.5 ", 0.5),
    ],
)
def test_threshold_defaults_to_1800_and_accepts_only_finite_positive(
    monkeypatch, raw, expected
):
    assert config_mod.DEFAULT_AUTO_MOLT_IDLE_SECONDS == 1800.0
    if raw is None:
        monkeypatch.delenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", raising=False)
    else:
        monkeypatch.setenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", raw)
    assert config_mod.auto_molt_idle_seconds() == expected


def test_idle_asleep_switch_keeps_one_period_and_reminds_once(setup):
    agent, clock, store = setup
    notify = lifecycle_mod._maybe_notify_auto_molt

    clock.set_monotonic(1_000.0)
    agent._set_state(AgentState.ASLEEP, reason="test")  # IDLE -> ASLEEP
    clock.set_monotonic(1_799.0)
    notify(agent)
    assert _events(store) == []

    clock.set_monotonic(1_800.0)  # threshold is inclusive, measured from t=0
    notify(agent)
    assert len(_events(store)) == 1

    clock.set_monotonic(9_000.0)
    agent._set_state(AgentState.IDLE, reason="test")  # still the same period
    notify(agent)
    assert len(_events(store)) == 1


@pytest.mark.parametrize(
    "away", [AgentState.ACTIVE, AgentState.STUCK, AgentState.SUSPENDED]
)
def test_leaving_inactivity_resets_suppresses_and_rearms(setup, away):
    agent, clock, store = setup
    notify = lifecycle_mod._maybe_notify_auto_molt

    clock.set_monotonic(1_700.0)
    agent._set_state(away, reason="test")
    clock.set_monotonic(20_000.0)
    notify(agent)  # not inactive: nothing, however long
    assert _events(store) == []

    agent._set_state(AgentState.IDLE, reason="test")  # new period from 20_000
    clock.set_monotonic(21_799.0)
    notify(agent)
    assert _events(store) == []
    clock.set_monotonic(21_800.0)
    notify(agent)
    assert len(_events(store)) == 1

    agent._set_state(AgentState.ACTIVE, reason="test")  # re-arm after work
    clock.set_monotonic(30_000.0)
    agent._set_state(AgentState.ASLEEP, reason="test")
    clock.set_monotonic(31_800.0)
    notify(agent)
    assert len(_events(store)) == 2


def test_failed_publish_does_not_latch_and_is_retried(setup):
    agent, clock, store = setup
    clock.set_monotonic(1_800.0)

    with patch(
        "lingtai.kernel.base_agent.messaging._enqueue_system_notification",
        side_effect=OSError("store unavailable"),
    ):
        lifecycle_mod._maybe_notify_auto_molt(agent)
    assert agent._auto_molt_notified_since is None
    assert _events(store) == []

    lifecycle_mod._maybe_notify_auto_molt(agent)
    assert agent._auto_molt_notified_since == 0.0
    assert len(_events(store)) == 1


def test_env_threshold_is_read_live(setup, monkeypatch):
    agent, clock, store = setup
    monkeypatch.setenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", "30")
    clock.set_monotonic(29.0)
    lifecycle_mod._maybe_notify_auto_molt(agent)
    assert _events(store) == []
    clock.set_monotonic(30.0)
    lifecycle_mod._maybe_notify_auto_molt(agent)
    assert len(_events(store)) == 1


def test_heartbeat_publishes_without_molting_and_existing_sync_wakes_asleep(setup):
    agent, clock, store = setup
    agent._set_state(AgentState.ASLEEP, reason="test")
    agent._asleep.set()
    clock.set_monotonic(1_800.0)

    def stop_after_one_tick(_seconds):
        agent._heartbeat_thread = None

    agent._heartbeat_thread = object()
    with patch.object(
        agent._heartbeat_stop, "wait", side_effect=stop_after_one_tick
    ), patch.object(lifecycle_mod, "_write_heartbeat_tick"), patch(
        "lingtai.kernel.nudge.run_checks_nonblocking"
    ), patch(
        "lingtai.kernel.nudge.run_system_notifications"
    ), patch.object(agent, "_perform_refresh") as refresh:
        lifecycle_mod._heartbeat_loop(agent)

    assert len(_events(store)) == 1
    assert agent._molt_count == 0
    assert not agent._cancel_event.is_set()
    refresh.assert_not_called()
    # The reminder itself never changes state; the pre-existing notification
    # sync in the same tick performed the ASLEEP -> IDLE wake.
    assert agent._state == AgentState.IDLE


def test_publish_for_old_period_does_not_latch_a_new_period(setup, monkeypatch):
    agent, clock, store = setup
    monkeypatch.setenv("LINGTAI_AUTO_MOLT_IDLE_SECONDS", "0.0001")
    enqueue = agent._enqueue_system_notification

    def enter_new_period_before_publish(**kwargs):
        agent._set_state(AgentState.ACTIVE, reason="work arrived")
        clock.set_monotonic(0.0002)
        agent._set_state(AgentState.ASLEEP, reason="new period")
        return enqueue(**kwargs)

    clock.set_monotonic(0.0001)
    with patch.object(agent, "_enqueue_system_notification", side_effect=enter_new_period_before_publish):
        lifecycle_mod._maybe_notify_auto_molt(agent)
    clock.set_monotonic(0.00031)
    lifecycle_mod._maybe_notify_auto_molt(agent)
    assert len(_events(store)) == 2
    assert len({event["ref_id"] for event in _events(store)}) == 2
