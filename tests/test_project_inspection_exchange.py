"""Thin inspection transport contracts; source authored, execution parent-owned."""
from __future__ import annotations

from dataclasses import replace
import argparse
import base64
import io
import json
import os
from pathlib import Path

import pytest

from lingtai.adapters.project_inspection import FilesystemProjectInspectionAdapter
from lingtai.adapters.project_inspection_exchange import (
    JsonProjectInspectionAdapter, read_inspection_request,
)
from lingtai.kernel.agent_presence import ManifestObservation
from lingtai.kernel.project import ProjectCreationError
from lingtai.kernel.project.inspection import (
    ProjectDirectoryObservation, ProjectInspectionPort, ProjectInspectionUseCase,
    ProjectMemberEvidence,
)


def _name(name: str) -> str:
    return base64.b64encode(os.fsencode(name)).decode("ascii")


def _ack(sequence: int, name: str, presence: str = "absent", failure=None) -> dict:
    return {"status": "init_presence_observed", "sequence": sequence,
            "directory_name_b64": _name(name), "presence": presence, "failure": failure}


class _Directory(ProjectInspectionPort):
    def __init__(self, names=("b", "a", "c", "d", ".helper", "human")):
        self.names = names
        self.scans = 0

    def observe_members(self):
        self.scans += 1
        return ProjectDirectoryObservation(True, tuple(
            ProjectMemberEvidence(name, ManifestObservation.valid(
                {"admin": None if name == "human" else {"x": name == "a"}}
            )) for name in self.names
        ))

    def observe_init_presence(self, directory_name):
        raise AssertionError("callback must never delegate native init stat")


class _FlushedInput(io.StringIO):
    def __init__(self, text, outgoing):
        super().__init__(text)
        self.outgoing = outgoing
        self.flushes_seen = 0

    def readline(self, *args):
        assert self.outgoing.flushes == self.flushes_seen + 1
        self.flushes_seen += 1
        return super().readline(*args)


class _Output(io.StringIO):
    flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


def test_exchange_order_stop_flush_and_terminal_binding():
    directory, output = _Directory(), _Output()
    facts = {"path_b64": _name("original/native/c/init.json"),
             "native_errno": None, "native_winerror": 5}
    acks = [_ack(1, "a", "present"), _ack(2, "b"), _ack(3, "c", "stat_failed", facts)]
    incoming = _FlushedInput("".join(json.dumps(ack) + "\n" for ack in acks), output)
    adapter = JsonProjectInspectionAdapter(directory, incoming, output)
    result = ProjectInspectionUseCase(adapter).inspect()
    payload = adapter.to_payload(result)
    frames = [json.loads(line) for line in output.getvalue().splitlines()]
    assert frames == [{"status": "observe_init_presence", "sequence": n,
                       "directory_name_b64": _name(name)} for n, name in enumerate("abc", 1)]
    assert directory.scans == 1 and incoming.tell() == len(incoming.getvalue())
    readiness = payload["startup_readiness"]
    assert readiness["reason"] == "cannot_stat_init"  # beats mixed and all later decisions
    assert readiness["agents_b64"] == [_name(name) for name in "abcd"]
    assert readiness["orchestrators_b64"] == [_name("a")]
    for item, ack in zip(readiness["init_evidence"], acks):
        assert {key: item[key] for key in ack if key != "status"} == {key: val for key, val in ack.items() if key != "status"}
    assert readiness["init_evidence"][-1]["failure"] == facts
    changed = replace(result, startup_readiness=replace(result.startup_readiness,
                      init_evidence=result.startup_readiness.init_evidence[:-1]))
    with pytest.raises(ProjectCreationError):
        adapter.to_payload(changed)
    reordered = replace(result, startup_readiness=replace(result.startup_readiness,
                        init_evidence=tuple(reversed(result.startup_readiness.init_evidence))))
    with pytest.raises(ProjectCreationError):
        adapter.to_payload(reordered)  # same count, wrong final identity/order
    last = result.startup_readiness.init_evidence[-1]
    forged = replace(last, observation=replace(last.observation,
                     failure=replace(last.observation.failure, native_winerror=32)))
    changed = replace(result, startup_readiness=replace(result.startup_readiness,
                      init_evidence=result.startup_readiness.init_evidence[:-1] + (forged,)))
    with pytest.raises(ProjectCreationError):
        adapter.to_payload(changed)  # same identity/sequence, wrong failure facts


@pytest.mark.parametrize("text", [
    "", json.dumps(_ack(1, "a")),  # EOF or no newline
    json.dumps(_ack(2, "a")) + "\n",  # reordered/replayed sequence
    json.dumps(_ack(True, "a")) + "\n",  # bool is not integer
    json.dumps(_ack(1, "b")) + "\n",  # forged directory
    json.dumps({**_ack(1, "a"), "secret": "PRIVATE"}) + "\n",
    json.dumps(_ack(1, "a", "unknown")) + "\n",
    json.dumps(_ack(1, "a", "present", {})) + "\n",
    json.dumps(_ack(1, "a", "stat_failed", {"path_b64": "YR==", "native_errno": 13, "native_winerror": None})) + "\n",
    json.dumps(_ack(1, "a", "stat_failed", {"path_b64": "YQ==", "native_errno": True, "native_winerror": None})) + "\n",
    '{"status":"init_presence_observed","sequence":1,"sequence":1,"directory_name_b64":"YQ==","presence":"absent","failure":null}\n',
])
def test_exchange_rejects_distinct_protocol_errors_without_fallback(text):
    output = _Output()
    adapter = JsonProjectInspectionAdapter(_Directory(("a",)), io.StringIO(text), output)
    with pytest.raises(ProjectCreationError) as error:
        ProjectInspectionUseCase(adapter).inspect()
    assert error.value.error.code == "invalid_project_exchange"
    assert "PRIVATE" not in error.value.error.message
    assert output.flushes == 1
    with pytest.raises(ProjectCreationError):
        adapter.observe_init_presence("a")
    assert output.flushes == 1  # stopped exchange is never retried


def test_lossless_native_identity_and_default_request_compatibility():
    name = "bad\udcff"
    output = _Output()
    adapter = JsonProjectInspectionAdapter(_Directory((name,)),
        io.StringIO(json.dumps(_ack(1, name)) + "\n"), output)
    result = ProjectInspectionUseCase(adapter).inspect()
    payload = adapter.to_payload(result)
    assert payload["members"][0]["directory_name_b64"] == _name(name)
    assert payload["startup_readiness"]["agents_b64"] == [_name(name)]
    assert "\\udcff" in json.dumps(payload, ensure_ascii=True)
    for text in ('{"project_dir":"r"}', '{\n"project_dir":"r"\n}',
                 '{"project_dir":"old","project_dir":"r"}'):
        assert read_inspection_request(io.StringIO(text)).project_dir == "r"
    native = read_inspection_request(io.StringIO('{"project_dir":"r","init_observation_mode":"native"}'))
    assert native.init_observation_mode == "native"
    for text in ('{"project_dir":"r","init_observation_mode":"callback"}',
                 '{\n"project_dir":"r","init_observation_mode":"callback"\n}',
                 '{"project_dir":"r","init_observation_mode":"native","project_dir":"s"}'):
        with pytest.raises(ProjectCreationError):
            read_inspection_request(io.StringIO(text))


def test_callback_cli_never_stats_init_and_has_one_structured_terminal(
    tmp_path: Path, monkeypatch, capsys,
):
    from lingtai.cli_project import handle_project_command
    member = tmp_path / ".lingtai" / "a"
    member.mkdir(parents=True)
    (member / ".agent.json").write_text('{"admin":{"x":true},"secret":"PRIVATE"}', encoding="utf-8")
    def forbidden(*args):
        raise AssertionError("native init stat forbidden")
    monkeypatch.setattr(FilesystemProjectInspectionAdapter, "observe_init_presence", forbidden)
    request = {"project_dir": str(tmp_path), "init_observation_mode": "callback"}
    for ack, succeeds in [(json.dumps(_ack(1, "a")) + "\n", True), ("", False)]:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request) + "\n" + ack))
        if succeeds:
            handle_project_command(argparse.Namespace(project_command="inspect"))
        else:
            with pytest.raises(SystemExit) as error:
                handle_project_command(argparse.Namespace(project_command="inspect"))
            assert error.value.code == 1
        output = capsys.readouterr()
        assert "PRIVATE" not in output.out + output.err
        frames = [json.loads(line) for line in output.out.splitlines()]
        assert frames[0]["status"] == "observe_init_presence"
        if succeeds:
            assert len(frames) == 2 and frames[-1]["startup_readiness"]["reason"] == "ready"
            assert output.err == ""
        else:
            assert len(frames) == 1
            assert json.loads(output.err)["code"] == "invalid_project_exchange"
    assert sorted(path.name for path in member.iterdir()) == [".agent.json"]


def test_callback_absent_and_empty_members_need_no_ack(tmp_path: Path, monkeypatch, capsys):
    from lingtai.cli_project import handle_project_command
    for initialized, reason in [(False, "not_initialized"), (True, "no_agents")]:
        if initialized:
            (tmp_path / ".lingtai").mkdir()
        request = {"project_dir": str(tmp_path), "init_observation_mode": "callback"}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request) + "\n"))
        handle_project_command(argparse.Namespace(project_command="inspect"))
        output = capsys.readouterr()
        assert output.err == "" and len(output.out.splitlines()) == 1
        payload = json.loads(output.out)
        assert payload["initialized"] is initialized and payload["members"] == []
        assert payload["startup_readiness"] == {
            "reason": reason, "needs_rehydration": False, "agents": [], "orchestrators": [],
            "init_evidence": [], "agents_b64": [], "orchestrators_b64": [],
        }
