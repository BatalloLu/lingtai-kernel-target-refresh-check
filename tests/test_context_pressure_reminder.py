"""Small numeric and canonical-owner context-pressure boundary regressions."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from lingtai.kernel.config import (
    CONTEXT_PRESSURE_HIGH_RATIO,
    CONTEXT_PRESSURE_FORCED_REBUILD_RATIO,
    CONTEXT_PRESSURE_RECONSTRUCTION_RATIO,
    CONTEXT_PRESSURE_RECOVERY_TARGET,
    CONTEXT_PRESSURE_WARN_AFTER_ROUNDS,
)
from lingtai.kernel.reminders.context_pressure import (
    ContextPressureReminder,
    CURRENT_MOLT_EVENT,
    RECONSTRUCTION_MOLT_EVENT,
    RECONSTRUCTION_MOLT_TARGET_PATH,
    TRANSITION_DUPLICATE,
    TRANSITION_HIGH_ROUND,
    TRANSITION_INITIAL,
    TRANSITION_RELIEVED,
    TRANSITION_UNKNOWN_USAGE,
    TRANSITION_WARNING_ACTIVE,
    current_molt_emission_descriptor,
    reconstruction_molt_emission_descriptor,
    reminder_message_hash,
    render_current_molt_context,
    render_reconstruction_molt,
)

def test_defaults_match_kernel_constants():
    r = ContextPressureReminder()
    assert r.reconstruction_ratio == CONTEXT_PRESSURE_HIGH_RATIO == 0.85
    assert CONTEXT_PRESSURE_FORCED_REBUILD_RATIO == 1.0
    # back-compat alias now points at the 1.0 hard forced-rebuild boundary
    assert CONTEXT_PRESSURE_RECONSTRUCTION_RATIO == CONTEXT_PRESSURE_FORCED_REBUILD_RATIO == 1.0
    assert r.warn_after_rounds == CONTEXT_PRESSURE_WARN_AFTER_ROUNDS == 3
    assert r.recovery_target == CONTEXT_PRESSURE_RECOVERY_TARGET == 0.75


def test_duplicate_round_id_is_noop():
    r = ContextPressureReminder()
    r.note_round(0.90, round_id=7)
    r.note_round(0.90, round_id=7)
    r.note_round(0.90, round_id=7)
    assert r.streak == 1 and r.active is False


def test_drop_below_ratio_resets_streak():
    r = ContextPressureReminder()
    r.note_round(0.90, round_id=1)
    r.note_round(0.90, round_id=2)
    r.note_round(0.50, round_id=3)  # relieved
    assert r.streak == 0 and r.active is False

    # Relief restarts the consecutive-high requirement from scratch.
    r.note_round(0.90, round_id=4)
    r.note_round(0.90, round_id=5)
    assert r.streak == 2 and r.active is False
    r.note_round(0.90, round_id=6)
    assert r.streak == 3 and r.active is True


def test_threshold_is_inclusive_at_ratio():
    r = ContextPressureReminder()
    r.note_round(0.85, round_id=1)
    assert r.streak == 1
    r.note_round(0.8499, round_id=2)
    assert r.streak == 0


def test_unknown_usage_sentinel_leaves_streak_untouched():
    r = ContextPressureReminder()
    r.note_round(0.90, round_id=1)
    r.note_round(0.90, round_id=2)
    r.note_round(-1.0, round_id=3)  # sentinel: not high, not a real relief
    assert r.streak == 2
    r.note_round(0.90, round_id=4)
    assert r.active is True


def test_unparseable_usage_leaves_streak_untouched():
    r = ContextPressureReminder()
    r.note_round(0.90, round_id=1)
    r.note_round("not-a-number", round_id=2)
    assert r.streak == 1
    assert r.last_transition_reason == TRANSITION_UNKNOWN_USAGE


def test_annotate_reconstruction_none_below_recovery_target():
    r = ContextPressureReminder()
    assert r.annotate_reconstruction(0.40) is None


def test_annotate_reconstruction_inclusive_at_recovery_target():
    r = ContextPressureReminder()
    assert r.annotate_reconstruction(0.75) is not None


def test_annotate_reconstruction_still_above_ratio_says_stop_looping():
    r = ContextPressureReminder()
    molt = r.annotate_reconstruction(0.90)
    assert "90%" in molt
    assert "above the 85% high-context threshold" in molt
    assert "substantially hurt token efficiency" in molt
    assert "stop repeating summarize" in molt
    assert "molt deliberately" in molt


def _make_session_manager():
    from unittest.mock import MagicMock

    from lingtai.kernel.config import AgentConfig
    from lingtai.kernel.session import SessionManager

    svc = MagicMock()
    svc.model = "test-model"
    return SessionManager(
        llm_service=svc,
        config=AgentConfig(),
        agent_name="test",
        streaming=False,
        build_system_prompt_fn=lambda: "test prompt",
        build_tool_schemas_fn=lambda: [],
        logger_fn=None,
    )


def test_session_manager_owns_one_transient_reminder():
    sm = _make_session_manager()
    reminder = sm.context_pressure_reminder
    assert isinstance(reminder, ContextPressureReminder)
    assert sm.context_pressure_reminder is reminder

    reminder.note_round(0.90, round_id=1)
    reminder.note_round(0.90, round_id=2)
    assert reminder.streak == 2
    assert reminder.active is False

    reminder.note_round(0.90, round_id=3)
    assert reminder.active is True
    fresh = _make_session_manager().context_pressure_reminder
    assert fresh is not reminder
    assert fresh.streak == 0
    assert fresh.active is False


def _agent_with_reminder(reminder):
    return SimpleNamespace(
        _intrinsics={"context": object()},
        _session=SimpleNamespace(context_pressure_reminder=reminder),
    )


def test_meta_block_build_molt_context_matches_owner_across_rounds():
    from lingtai.kernel.meta_block import build_molt_context

    reminder = ContextPressureReminder()
    agent = _agent_with_reminder(reminder)
    for rid, usage in enumerate((0.85, 0.90, 0.95, 0.84), start=1):
        reminder.note_round(usage, round_id=rid)
        before = reminder.snapshot()
        assert build_molt_context(agent, usage) == reminder.current_molt_context(usage)
        assert build_molt_context(agent, usage) == reminder.current_molt_context(usage)
        assert reminder.snapshot() == before
        assert reminder.active is (rid == 3)


def test_current_molt_emission_descriptor_fields():
    r = ContextPressureReminder()
    for rid in (1, 2, 3):
        r.note_round(0.90, round_id=rid)
    message = r.current_molt_context(0.90)
    assert message is not None
    desc = current_molt_emission_descriptor(r, usage=0.90, message=message)
    assert desc["event_name"] == CURRENT_MOLT_EVENT
    payload = desc["payload"]
    assert payload["target_path"] == "_meta.agent_meta.agent_state.context.molt"
    assert payload["message_hash"] == reminder_message_hash(message)
    assert payload["threshold_high"] == 0.85
    assert payload["recovery_target"] == 0.75
    assert payload["usage"] == pytest.approx(0.90)
    assert payload["streak"] == 3
    assert payload["last_round_id"] == 3
    assert payload["transition_reason"] == TRANSITION_WARNING_ACTIVE
    # JSON-safe and carries no full reminder prose.
    import json as _json

    encoded = _json.dumps(payload)
    assert message not in encoded
    assert "Context has stayed high" not in encoded


def test_reconstruction_molt_emission_descriptor_still_high_branch():
    event = {
        "type": "delayed_summarize_reconstruction",
        "trigger_threshold": 1.0,
        "recovery_target": 0.75,
        "before": {"usage": 0.85},
        "after": {"usage": 0.90, "source": "provider_input_tokens"},
    }
    message = "the rebuilt context is still at 90%..."
    desc = reconstruction_molt_emission_descriptor(event, message=message)
    assert desc["event_name"] == RECONSTRUCTION_MOLT_EVENT
    payload = desc["payload"]
    assert payload["target_path"] == RECONSTRUCTION_MOLT_TARGET_PATH
    assert payload["target_path"] == "_meta.agent_meta.agent_state.events.reconstruction.molt"
    assert payload["message_hash"] == reminder_message_hash(message)
    assert payload["trigger_threshold"] == 1.0
    assert payload["recovery_target"] == 0.75
    assert payload["before_usage"] == pytest.approx(0.85)
    assert payload["after_usage"] == pytest.approx(0.90)
    assert payload["after_source"] == "provider_input_tokens"
    # >= trigger_threshold -> still_high branch
    assert payload["branch"] == "still_high"
    import json as _json

    _json.dumps(payload)  # JSON-safe


def test_reconstruction_molt_emission_descriptor_above_recovery_branch():
    event = {
        "trigger_threshold": 1.0,
        "recovery_target": 0.75,
        "before": {"usage": 0.85},
        "after": {"usage": 0.80, "source": "local_estimate"},
    }
    payload = reconstruction_molt_emission_descriptor(event, message="text")["payload"]
    # recovery_target <= after < trigger_threshold -> above_recovery branch
    assert payload["branch"] == "above_recovery"
    assert payload["after_usage"] == pytest.approx(0.80)
    assert payload["after_source"] == "local_estimate"
