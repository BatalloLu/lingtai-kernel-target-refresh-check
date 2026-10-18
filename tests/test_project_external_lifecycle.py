"""Thin real Core/exchange traces; author-only, not native acceptance evidence."""
import io
import json

import pytest

from lingtai.adapters.project_lifecycle_exchange import (
    JsonProjectLifecycleAdapter, LifecycleExchangeStopped,
)
from lingtai.kernel.project.external_lifecycle import ExternalLifecycleUseCase


def exchange(steps):
    """Predeclare peer observations, then use the REAL strict port and Core."""
    frames = []
    acks = []
    for sequence, (operation, target, argument, facts) in enumerate(steps, 1):
        frame = dict(status="project_lifecycle_native", request_id="one",
                     sequence=sequence, operation=operation, target=target, argument=argument)
        frames.append(frame)
        ack = dict(frame, status="project_lifecycle_observed", flag=False,
                   failed=False, ownership_changed=False, members=[])
        ack.update(facts)
        acks.append(ack)
    incoming = io.StringIO("".join(json.dumps(ack) + "\n" for ack in acks))
    outgoing = io.StringIO()
    port = JsonProjectLifecycleAdapter("one", incoming, outgoing)
    def verify():
        assert [json.loads(line) for line in outgoing.getvalue().splitlines()] == frames
        assert port.transcript == acks
        assert incoming.read() == ""
    return ExternalLifecycleUseCase(port), verify


def step(op, target=-1, argument="", **facts):
    return op, target, argument, facts


def member(target, human=False):
    return dict(target=target, human=human)


def refresh_prefix(explicit=False):
    return [step("external_owner", 0), step("write_signal", 0, "suspend"),
            step("probe_lock", 0, flag=True), step("running", 0),
            *[step("remove_handshake", 0, name) for name in ("lock", "refresh", "refresh_taken", "suspend")],
            step("preset", 0, "explicit" if explicit else "default", failed=True)]


def test_direct_signal_has_no_new_alive_gate_and_counts_failed_attempt():
    core, verify = exchange([step("write_signal", 0, "sleep", failed=True)])
    assert core.signal("sleep", all_targets=False, selected=True).count == 1
    verify()


def test_all_signal_skips_human_and_dead_but_counts_failed_write():
    core, verify = exchange([
        step("discover", members=[member(1, True), member(2), member(3)]),
        step("alive", 2, "standard"), step("alive", 3, "standard", flag=True),
        step("write_signal", 3, "suspend", failed=True),
    ])
    assert core.signal("suspend", all_targets=True, selected=True).count == 1
    verify()


@pytest.mark.parametrize("explicit", [False, True])
def test_refresh_failed_preset_still_force_launches_and_defensively_sweeps(explicit):
    core, verify = exchange(refresh_prefix(explicit) + [
        step("launch", 0, "force"), step("remove_handshake", 0, "suspend"),
        step("heartbeat", 0),
    ])
    assert core.refresh(explicit=explicit).code == "ok"
    verify()


def test_refresh_launch_error_returns_after_defensive_cleanup_without_heartbeat():
    core, verify = exchange(refresh_prefix() + [
        step("launch", 0, "force", failed=True), step("remove_handshake", 0, "suspend"),
    ])
    result = core.refresh()
    assert (result.code, result.error_sequence) == ("native", 10)
    verify()


def test_refresh_ownership_change_preserves_new_owner_lock():
    core, verify = exchange([
        step("external_owner", 0), step("write_signal", 0, "suspend"),
        step("probe_lock", 0, flag=True), step("running", 0, flag=True),
        step("terminate", 0, failed=True, ownership_changed=True),
    ])
    assert core.refresh().error_sequence == 5
    verify()


def test_revive_lock_timeout_removes_only_lock_then_normal_launch():
    core, verify = exchange([step("external_owner", 0)] + [
        item for _ in range(120) for item in (step("probe_lock", 0), step("sleep", argument="500"))
    ] + [step("remove_handshake", 0, "lock"), step("launch", 0, "normal"), step("heartbeat", 0)])
    assert core.revive().code == "ok"
    verify()


def test_cpr_all_only_dead_nonhumans_and_preserves_failure_count():
    core, verify = exchange([
        step("discover", members=[member(1, True), member(2), member(3)]),
        step("alive", 2, "standard", flag=True), step("alive", 3, "standard"),
        step("external_owner", 3, flag=True, failed=True),
    ])
    result = core.cpr(all_targets=True, selected=False)
    assert result.count == 1
    assert [(failure.target, failure.sequence) for failure in result.failures] == [(3, 4)]
    verify()


def test_temporary_clear_capture_after_revive_wait_failure_wins_over_suspend():
    core, verify = exchange([
        step("alive", 0, "clear"), step("revive_for_clear", 0),
        step("clear_alive_wait", 0), step("clear_capture", 0),
        step("write_signal", 0, "clear"), step("clear_completion_wait", 0, failed=True),
        step("clear_suspend", 0, failed=True),
    ])
    result = core.clear()
    assert (result.completed, result.error_sequence) == (False, 6)
    verify()


def test_clean_rechecks_new_members_before_delete_not_only_original_alive():
    core, verify = exchange([
        step("discover", members=[member(1)]), step("write_signal", 1, "suspend", failed=True),
        step("alive", 1, "standard", flag=True), step("clean_wait_start", argument="1"),
        step("clean_before_deadline"),
        step("discover", members=[member(1), member(2)]),
        step("alive", 1, "standard"), step("alive", 2, "standard", flag=True),
    ])
    result = core.clean(force=False)
    assert result.code == "survivors" and result.survivors == [2]
    verify()


def test_force_discovery_failure_does_not_skip_partial_members_suspend():
    core, verify = exchange([
        step("discover", failed=True, members=[member(1)]),
        step("write_signal", 1, "suspend"), step("alive", 1, "standard"),
        step("discover", failed=True), step("remove_tree"),
    ])
    assert core.clean(force=True).code == "ok"
    verify()


def test_nirvana_sequential_native_wait_then_exact_barrier_ignores_remove_failure():
    core, verify = exchange([
        step("discover", members=[member(1), member(2, True), member(3)]),
        step("alive", 1, "standard", flag=True), step("suspend_wait", 1),
        step("alive", 3, "standard", flag=True), step("suspend_wait", 3),
        step("reset_barrier", failed=True), step("remove_tree", failed=True),
    ])
    assert core.nirvana().code == "ok"
    verify()


def test_wrong_ack_stops_once_without_second_request_or_fallback():
    incoming, outgoing = io.StringIO('{"status":"forged"}\n'), io.StringIO()
    port = JsonProjectLifecycleAdapter("one", incoming, outgoing)
    with pytest.raises(LifecycleExchangeStopped):
        port.write_signal(0, "sleep")
    with pytest.raises(LifecycleExchangeStopped):
        port.write_signal(0, "sleep")
    assert len(outgoing.getvalue().splitlines()) == 1
    assert port.transcript == []


@pytest.mark.parametrize("nonempty,candidates,expected", [
    (False, [(True, True)], ("empty", -1, 0)),
    (True, [], ("no_allowed", -1, 0)),
    (True, [(False, True), (True, False)], ("ok", 1, 0)),
    (True, [(False, True), (False, True)], ("ambiguous", -1, 2)),
    (True, [(False, False)], ("not_allowed", -1, 0)),
])
def test_external_preset_core_owns_exact_first_and_empty_query_no_read(nonempty, candidates, expected):
    from lingtai.kernel.project.external_lifecycle import PresetCandidate, resolve_external_preset
    class Native:
        calls = 0
        def candidates(self):
            self.calls += 1
            return tuple(PresetCandidate(*item) for item in candidates)
    native = Native()
    result = resolve_external_preset(query_nonempty=nonempty, native=native)
    assert (result.code, result.index, result.matches) == expected
    assert native.calls == int(nonempty)


def test_real_cli_composes_read_only_preset_core_with_bound_native_evidence():
    from lingtai.cli_project_lifecycle import run_project_lifecycle
    incoming = io.StringIO(
        json.dumps(dict(request_id="query-one", action="resolve_preset", query_nonempty=True)) + "\n" +
        json.dumps(dict(status="project_preset_observed", request_id="query-one", sequence=1,
                        candidates=[dict(exact=False, stem=True), dict(exact=True, stem=False)])) + "\n"
    )
    outgoing = io.StringIO()
    assert run_project_lifecycle(incoming, outgoing) == 0
    frame, terminal = map(json.loads, outgoing.getvalue().splitlines())
    assert frame == dict(status="project_preset_candidates", request_id="query-one", sequence=1)
    assert (terminal["code"], terminal["index"], terminal["matches"]) == ("ok", 1, 0)
    assert terminal["candidates"] == [dict(exact=False, stem=True), dict(exact=True, stem=False)]
