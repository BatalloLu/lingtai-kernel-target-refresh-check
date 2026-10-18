"""Thin running-inventory policy/transport contracts; no filesystem/process I/O."""
from dataclasses import replace
import base64
import io
import json

from lingtai.cli_project_inventory import execute, run_inventory
from lingtai.kernel.project.inventory import (
    InventoryObservation, RunningMemberObservation, RunningProjectObservation, query_inventory,
)


def member(row, name, *, flags=(), human=False, failed=False, pid=None, runtime=0):
    directory = b"/project/.lingtai/" + name
    return RunningMemberObservation(row, directory, b"/project", b"/project", name, directory,
                                    row + 10 if pid is None else pid, runtime, human, flags, failed)


def test_process_visible_members_include_broken_and_human_difference():
    rows = (member(0, b"worker"), member(1, b"main", flags=(False, True)),
            member(2, b"human", human=True), member(3, b"broken", failed=True))
    observation = InventoryObservation(rows, (RunningProjectObservation(b"/project", False),), False)
    result = query_inventory(observation)
    assert [(m.row, m.role, m.reason) for m in result.members] == [
        (1, "MAIN", ""), (0, "AGENT", "non_admin_target"), (3, "?", "manifest_unreadable")]
    assert result.groups == ((1, 0, 3),)
    included = query_inventory(replace(observation, include_human=True))
    assert included.members[-1].role == "HUMAN"
    assert included.members[-1].reason == "human_target"
    # A native typed-read error and raw true-admin observation can coexist.
    race = query_inventory(replace(observation, members=(replace(rows[1], manifest_failed=True),)))
    assert race.members[0].role == "MAIN" and race.members[0].reason == "manifest_unreadable"
    phantom = query_inventory(replace(observation, projects=(RunningProjectObservation(b"/project", True),)))
    assert all(m.reason == "phantom_project" for m in phantom.members)
    assert phantom.phantom_projects == (0,)


def test_duplicate_pid_selection_keeps_discovery_slot_and_native_identity():
    first = member(0, b"same", flags=(True,), pid=111)
    other = member(1, b"worker")
    current = replace(first, row=2, pid=222, duplicate_runtime_pid=222)
    stale = replace(first, row=3, pid=333, duplicate_runtime_pid=222)
    result = query_inventory(InventoryObservation((first, other, current, stale), (), False))
    assert [m.row for m in result.members] == [2, 1]
    assert result.members[0].directory == first.directory and result.members[0].pid == 222
    replaced = query_inventory(InventoryObservation((replace(current, pid=444, duplicate_runtime_pid=0),), (), False))
    assert (replaced.members[0].directory, replaced.members[0].pid) != (result.members[0].directory, result.members[0].pid)


def test_closed_query_preserves_bytes_without_roundtripping_native_labels(monkeypatch):
    encoded = lambda value: base64.b64encode(value).decode("ascii")
    row = {"row": 0, "directory": encoded(b"/p/.lingtai/\xff"), "project": encoded(b"/p"),
           "project_order": encoded(b"/p"), "name_order": encoded(b"native-Go-key"),
           "directory_order": encoded(b"native-Go-key"), "pid": 42, "duplicate_runtime_pid": 0,
           "admin_null": False, "admin_flags": [True], "manifest_failed": False}
    request = {"members": [row], "projects": [{"identity": encoded(b"/p"), "container_missing": False}], "include_human": False}
    result = execute(request)
    assert result["members"][0]["directory"] == row["directory"]
    assert result["members"][0]["pid"] == 42 and result["groups"] == ((0,),)
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", stderr)
    assert run_inventory() == 0
    assert json.loads(stdout.getvalue())["status"] == "inventory_queried" and not stderr.getvalue()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"members":[],"members":[],"projects":[],"include_human":false}'))
    assert run_inventory() == 1
    assert "invalid_inventory_observation" in stderr.getvalue()
