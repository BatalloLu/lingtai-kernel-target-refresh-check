"""Project membership contract fixtures. Authored here; execution is a separate gate."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from lingtai.adapters.project_inspection import FilesystemProjectInspectionAdapter
from lingtai.kernel.agent_presence import ManifestObservation
from lingtai.kernel.project import ProjectCreationError
from lingtai.kernel.project.inspection import (
    ProjectDirectoryObservation,
    ProjectInspectionPort,
    ProjectInspectionUseCase,
    ProjectMemberEvidence,
    ProjectInitObservation,
    ProjectInitPresence,
    ProjectInitStatFailure,
)


# Shared domain cases also written through the production adapter below.
_MANIFESTS = {
    "human": {"agent_name": "Human", "admin": None},
    "worker-dir": {"agent_name": "Different display name", "admin": {}, "agent_id": "stable-id", "address": "worker-address"},
    "orchestrator": {"admin": {"create": True, "other": False}},
    "not-truthy": {"admin": {"create": 1, "text": "true"}},
    "legacy-human": {},
}


class _Directory(ProjectInspectionPort):
    def observe_init_presence(self, directory_name: str) -> ProjectInitObservation:
        return ProjectInitObservation(ProjectInitPresence.ABSENT)

    def observe_members(self) -> ProjectDirectoryObservation:
        candidates = [
            ProjectMemberEvidence(name, ManifestObservation.valid(manifest))
            for name, manifest in _MANIFESTS.items()
        ]
        candidates += [
            ProjectMemberEvidence("broken", ManifestObservation.malformed()),
            ProjectMemberEvidence("no-manifest", ManifestObservation.absent()),
        ]
        return ProjectDirectoryObservation(True, tuple(candidates))


@pytest.fixture(params=["fake", "filesystem"])
def directory(request: pytest.FixtureRequest, tmp_path: Path) -> ProjectInspectionPort:
    if request.param == "fake":
        return _Directory()
    target = tmp_path / ".lingtai"
    for name, manifest in _MANIFESTS.items():
        member = target / name
        member.mkdir(parents=True)
        (member / ".agent.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "broken").mkdir()
    (target / "broken" / ".agent.json").write_text("[", encoding="utf-8")
    (target / "no-manifest").mkdir()
    return FilesystemProjectInspectionAdapter(tmp_path)


def test_shared_member_classification_and_identity(directory: ProjectInspectionPort) -> None:
    payload = ProjectInspectionUseCase(directory).inspect().to_payload()
    assert payload["status"] == "inspected"
    assert payload["initialized"] is True
    members = {member["directory_name"]: member for member in payload["members"]}
    assert list(members) == sorted(members)
    assert "no-manifest" not in members
    assert members["human"]["role"] == "human"
    assert members["legacy-human"]["role"] == "human"
    assert members["orchestrator"]["role"] == "orchestrator"
    assert members["not-truthy"]["role"] == "worker"
    assert members["broken"]["manifest_kind"] == "malformed"
    assert members["broken"]["role"] == "unknown"
    worker = members["worker-dir"]
    assert worker["agent_name"] == "Different display name"
    assert worker["agent_id"] == "stable-id"
    assert worker["address"] == "worker-address"
    assert "admin" not in worker


def test_inspect_absent_project_is_read_only(tmp_path: Path) -> None:
    assert ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect().to_payload() == {
        "status": "inspected", "initialized": False, "members": [],
        "startup_readiness": {
            "reason": "not_initialized", "needs_rehydration": False,
            "agents": [], "orchestrators": [], "init_evidence": [],
        },
    }
    assert list(tmp_path.iterdir()) == []


def test_inspect_does_not_hide_invalid_project_container(tmp_path: Path) -> None:
    (tmp_path / ".lingtai").write_text("not a directory", encoding="utf-8")
    with pytest.raises(ProjectCreationError) as exc:
        ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect()
    assert exc.value.error.code == "project_inspect_failed"


def test_non_object_and_non_file_manifests_remain_repair_targets(tmp_path: Path) -> None:
    for name in ("array", "directory"):
        member = tmp_path / ".lingtai" / name
        member.mkdir(parents=True)
        if name == "array":
            (member / ".agent.json").write_text("[]", encoding="utf-8")
        else:
            (member / ".agent.json").mkdir()
    members = ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect().members
    assert len(members) == 2
    assert all(member.manifest_kind.value == "malformed" for member in members)


def test_inspection_cli_uses_json_stdin_and_does_not_expose_raw_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from lingtai.cli_project import handle_project_command

    member = tmp_path / ".lingtai" / "different-directory"
    member.mkdir(parents=True)
    manifest = member / ".agent.json"
    raw = json.dumps({"agent_name": "display", "admin": {}, "secret": "must-not-emit"})
    manifest.write_text(raw, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"project_dir": str(tmp_path)})))
    handle_project_command(argparse.Namespace(project_command="inspect"))
    output = capsys.readouterr()
    assert output.err == ""
    assert "must-not-emit" not in output.out
    assert json.loads(output.out)["members"][0]["agent_name"] == "display"
    assert manifest.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize("request_text", ["[]", "{}", '{"project_dir":1}', '{"project_dir":"x","unknown":true}'])
def test_inspection_cli_rejects_invalid_request_without_reading_project(
    request_text: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from lingtai.cli_project import handle_project_command

    monkeypatch.setattr("sys.stdin", io.StringIO(request_text))
    with pytest.raises(SystemExit) as exc:
        handle_project_command(argparse.Namespace(project_command="inspect"))
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["code"] == "invalid_project_request"


class _ReadinessDirectory(ProjectInspectionPort):
    def __init__(self, manifests: dict[str, object], present: set[str], failure_at: str = "") -> None:
        self.manifests = manifests
        self.present = present
        self.failure_at = failure_at
        self.calls: list[str] = []

    def observe_members(self) -> ProjectDirectoryObservation:
        return ProjectDirectoryObservation(True, tuple(
            ProjectMemberEvidence(name, ManifestObservation.malformed() if value == "malformed"
                                  else ManifestObservation.valid(value))
            for name, value in reversed(list(self.manifests.items()))
        ))

    def observe_init_presence(self, directory_name: str) -> ProjectInitObservation:
        self.calls.append(directory_name)
        if directory_name == self.failure_at:
            return ProjectInitObservation(ProjectInitPresence.STAT_FAILED,
                                          ProjectInitStatFailure("cGF0aA==", 13, None))
        return ProjectInitObservation(ProjectInitPresence.PRESENT if directory_name in self.present
                                      else ProjectInitPresence.ABSENT)


@pytest.mark.parametrize("backend", ["fake", "filesystem"])
@pytest.mark.parametrize("manifests,present,reason,rehydrate", [
    ({}, set(), "no_agents", False),
    ({"w": {"admin": {}}}, set(), "no_orchestrator", True),
    ({"a": {"admin": {"x": True}}, "b": {"admin": {"x": True}}}, set(), "multiple_orchestrators", True),
    ({"a": {"admin": {}}, "b": {"admin": {}}}, {"a"}, "mixed_init", False),
    ({"a": {"admin": {"x": True}}, "b": {"admin": {"x": True}}}, {"a"}, "mixed_init", False),
    ({"a": {"admin": {"x": True}}, "b": {"admin": "non-map"}}, set(), "ready", True),
    ({"a": {"admin": {"x": True}}, "b": {"admin": [True]}}, {"a", "b"}, "ready", False),
    ({"a": {"admin": {"x": 1, "y": "true"}}}, {"a"}, "no_orchestrator", False),
    ({".helper": {"admin": {"x": True}}, "human": {"admin": None},
      "legacy": {}, "broken": "malformed"}, set(), "no_agents", False),
])
def test_readiness_shared_distinct_invariants(
    tmp_path: Path, backend: str, manifests: dict[str, object], present: set[str],
    reason: str, rehydrate: bool,
) -> None:
    if backend == "fake":
        port = _ReadinessDirectory(manifests, present)
    else:
        target = tmp_path / ".lingtai"
        target.mkdir()
        for name, value in manifests.items():
            member = target / name
            member.mkdir()
            (member / ".agent.json").write_text("[" if value == "malformed" else json.dumps(value), encoding="utf-8")
            if name in present:
                # A directory is present just like a regular/invalid init file.
                (member / "init.json").mkdir()
        port = FilesystemProjectInspectionAdapter(tmp_path)
    result = ProjectInspectionUseCase(port).inspect()
    readiness = result.startup_readiness.to_payload()
    assert readiness["reason"] == reason
    assert readiness["needs_rehydration"] is rehydrate
    expected = sorted(name for name, value in manifests.items()
                      if not name.startswith(".") and isinstance(value, dict)
                      and value.get("admin") is not None)
    assert readiness["agents"] == expected
    assert [item["directory_name"] for item in readiness["init_evidence"]] == expected
    assert [item["directory_name"] for item in readiness["init_evidence"] if item["presence"] == "present"] == sorted(present)
    assert all(item["failure"] is None for item in readiness["init_evidence"])
    # Startup filtering never removes humans, malformed or dotdir members.
    assert len(result.members) == len(manifests)


@pytest.mark.parametrize("backend", ["fake", "filesystem"])
def test_readiness_first_stat_failure_beats_mixed_and_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    import base64
    import errno
    import os

    manifests = {name: {"admin": {}} for name in ("a", "b", "c", "d")}
    if backend == "fake":
        port = _ReadinessDirectory(manifests, {"a"}, "c")
    else:
        for name, value in manifests.items():
            member = tmp_path / ".lingtai" / name
            member.mkdir(parents=True)
            (member / ".agent.json").write_text(json.dumps(value), encoding="utf-8")
        (tmp_path / ".lingtai" / "a" / "init.json").write_text("not valid JSON", encoding="utf-8")
        original = Path.stat
        calls: list[str] = []
        def stat(path: Path, *args: object, **kwargs: object) -> object:
            if path.name == "init.json":
                calls.append(path.parent.name)
                if path.parent.name == "c":
                    raise PermissionError(errno.EACCES, "PRIVATE-EXCEPTION-CONTENT", str(path))
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "stat", stat)
        port = FilesystemProjectInspectionAdapter(tmp_path)
    readiness = ProjectInspectionUseCase(port).inspect().startup_readiness.to_payload()
    assert readiness["reason"] == "cannot_stat_init"
    assert readiness["needs_rehydration"] is False
    assert [item["presence"] for item in readiness["init_evidence"]] == ["present", "absent", "stat_failed"]
    assert (port.calls if backend == "fake" else calls) == ["a", "b", "c"]
    failure = readiness["init_evidence"][-1]["failure"]
    assert set(failure) == {"path_b64", "native_errno", "native_winerror"}
    assert failure["native_errno"] == 13
    assert "PRIVATE-EXCEPTION-CONTENT" not in json.dumps(readiness)
    if backend == "filesystem":
        assert base64.b64decode(failure["path_b64"]) == os.fsencode(tmp_path / ".lingtai" / "c" / "init.json")


def test_readiness_skips_symlink_members_and_stats_symlink_init(tmp_path: Path) -> None:
    target = tmp_path / ".lingtai"
    orch = target / "orch"
    orch.mkdir(parents=True)
    (orch / ".agent.json").write_text('{"admin":{"x":true}}', encoding="utf-8")
    (target / "ordinary-file").write_text("not member", encoding="utf-8")
    try:
        (target / "symlink-member").symlink_to(orch, target_is_directory=True)
        (orch / "init.json").symlink_to(orch, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink fixture creation")
    readiness = ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect().startup_readiness
    assert readiness.reason.value == "ready"
    assert readiness.needs_rehydration is False
    assert readiness.agents == ("orch",)
    (orch / "init.json").unlink()
    (orch / "init.json").symlink_to(orch / "missing")
    readiness = ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect().startup_readiness
    assert readiness.reason.value == "ready"
    assert readiness.needs_rehydration is True


def test_inspection_cli_reports_readiness_refusal_as_successful_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from lingtai.cli_project import handle_project_command

    (tmp_path / ".lingtai").mkdir()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"project_dir": str(tmp_path)})))
    handle_project_command(argparse.Namespace(project_command="inspect"))
    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert set(payload) == {"status", "initialized", "members", "startup_readiness"}
    assert payload["startup_readiness"] == {
        "reason": "no_agents", "needs_rehydration": False,
        "agents": [], "orchestrators": [], "init_evidence": [],
    }
    assert list((tmp_path / ".lingtai").iterdir()) == []


@pytest.mark.parametrize("native_errno", [13, 20, 40, 5])
def test_init_nonmissing_stat_errors_never_become_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_errno: int,
) -> None:
    original = Path.stat
    def stat(path: Path, *args: object, **kwargs: object) -> object:
        if path.name == "init.json":
            raise OSError(native_errno, "DO-NOT-EMIT", str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", stat)
    observed = FilesystemProjectInspectionAdapter(tmp_path).observe_init_presence("a")
    assert observed.presence is ProjectInitPresence.STAT_FAILED
    assert observed.failure.native_errno == native_errno
    assert "DO-NOT-EMIT" not in json.dumps(observed.failure.to_payload())


def test_inspection_enumeration_failure_is_not_empty_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".lingtai").mkdir()
    original = Path.iterdir
    def iterdir(path: Path):
        if path.name == ".lingtai":
            raise PermissionError(13, "DO-NOT-EMIT", str(path))
        return original(path)
    monkeypatch.setattr(Path, "iterdir", iterdir)
    with pytest.raises(ProjectCreationError) as exc:
        ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect()
    assert exc.value.error.code == "project_inspect_failed"
    assert "DO-NOT-EMIT" not in exc.value.error.message


def test_unreadable_manifest_remains_member_but_is_not_startup_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = tmp_path / ".lingtai" / "unreadable"
    member.mkdir(parents=True)
    (member / ".agent.json").write_text('{"admin":{"x":true}}', encoding="utf-8")
    original = Path.read_text
    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == ".agent.json":
            raise PermissionError(13, "DO-NOT-EMIT", str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read_text)
    result = ProjectInspectionUseCase(FilesystemProjectInspectionAdapter(tmp_path)).inspect()
    assert result.members[0].manifest_kind.value == "malformed"
    assert result.startup_readiness.reason.value == "no_agents"
    assert result.startup_readiness.init_evidence == ()
