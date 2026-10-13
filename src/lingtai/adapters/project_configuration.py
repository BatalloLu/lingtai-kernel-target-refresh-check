"""Project-local configuration filesystem and current init/Psyche owner seams."""
from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
from pathlib import Path
from collections.abc import Callable

from lingtai.kernel.project.configuration import (
    ConfigurationResult, ConfigurationWriteReceipt, ConfiguredMemberSeed,
    MemberDocuments, ProjectConfigurationPort, configuration_error,
)


def _regular_or_absent(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise configuration_error("nonregular_project_document")
    return True


def _read_object(path: Path) -> tuple[bool, dict | None, bool]:
    try:
        if not _regular_or_absent(path):
            return False, None, False
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return True, None, True
        return True, value, False
    except Exception:
        return True, None, True


def _atomic_text(path: Path, content: str, *, only_absent: bool = False) -> None:
    # Individual replacement only; no multi-document rollback/atomicity promise.
    path.parent.mkdir(parents=True, exist_ok=True)
    _regular_or_absent(path)
    fd, temporary = tempfile.mkstemp(prefix=".project-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        if only_absent:
            os.link(temporary, path)  # destination MUST remain absent
        else:
            os.replace(temporary, path)
    finally:
        # Only this call's newly allocated temp, never a prefix sweep.
        try:
            os.unlink(temporary)
        except OSError:
            # Temp removal is best effort; never convert known publication into
            # a false unwritten receipt. A retained owned temp is not swept later.
            pass


def _atomic_json(path: Path, document: dict, *, only_absent: bool = False) -> None:
    _atomic_text(path, json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                 only_absent=only_absent)


class FilesystemProjectConfigurationAdapter(ProjectConfigurationPort):
    def __init__(self, root: Path, *, load_preset: Callable[..., dict]) -> None:
        self.root = root
        self.base = root / ".lingtai"
        self.load_preset = load_preset
        self.normalize_source: str | None = None
        if not root.is_dir() or root.is_symlink():
            raise configuration_error("invalid_project_root")
        if os.path.lexists(self.base) and (self.base.is_symlink() or not self.base.is_dir()):
            raise configuration_error("invalid_project_root")

    def _member(self, name: str) -> Path:
        if not name or name in {".", ".."} or any(c in name for c in ("/", "\\", ":", "\x00")):
            raise configuration_error("invalid_project_request")
        path = self.base / name
        if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
            raise configuration_error("invalid_member_directory")
        # Prevent writes via existing nested symlink directories.
        return path

    def human_manifest_exists(self) -> bool:
        human = self._member("human")
        return (human / ".agent.json").exists()

    def save_skeleton(self, human_manifest: dict, mailboxes: tuple[str, ...],
                      helpers: tuple[str, ...]) -> ConfigurationResult:
        wrote = False
        try:
            self.base.mkdir(exist_ok=True)
            human = self._member("human")
            for sub in mailboxes:
                self._safe_parent(human / "mailbox" / sub)
            _atomic_json(human / ".agent.json", human_manifest)
            wrote = True
            _atomic_text(human / "mailbox" / "contacts.json", "[]")
            for helper in helpers:
                self._safe_parent(self.base / helper)
            return ConfigurationResult("initialized", "complete", updated=1)
        except Exception:
            return ConfigurationResult("initialized", "partial", int(wrote), failed=1,
                                       code="skeleton_initialization_failed")

    def _safe_parent(self, path: Path) -> None:
        current = self.base
        if self.base.is_symlink():
            raise configuration_error("invalid_project_root")
        self.base.mkdir(exist_ok=True)
        for part in path.relative_to(self.base).parts:
            current = current / part
            if current.is_symlink():
                raise configuration_error("nonregular_project_document")
            current.mkdir(exist_ok=True)

    def observe_member(self, directory_name: str) -> MemberDocuments:
        path = self._member(directory_name)
        present, document, error = _read_object(path / "init.json")
        if directory_name == self.normalize_source and document is not None:
            from lingtai.tools.registry import normalize_capabilities
            manifest = document.get("manifest")
            if isinstance(manifest, dict) and "capabilities" in manifest:
                try:
                    manifest["capabilities"] = normalize_capabilities(manifest["capabilities"])
                except (TypeError, ValueError):
                    raise configuration_error("source_document_unreadable") from None
        blueprint_present, blueprint, blueprint_error = _read_object(path / ".agent.json")
        return MemberDocuments(directory_name, present, document, blueprint_present, blueprint,
                               error, blueprint_error)

    def observe_candidates(self) -> tuple[MemberDocuments, ...]:
        try:
            entries = sorted(p for p in self.base.iterdir() if p.is_dir() and not p.is_symlink())
            return tuple(self.observe_member(p.name) for p in entries)
        except Exception:
            raise configuration_error("project_observation_failed") from None

    def _preflight(self, path: Path, document: dict) -> None:
        from lingtai.init_reader import reader_callbacks
        from lingtai.init_schema import validate_init

        candidate = copy.deepcopy(document)
        materialize, prepare = reader_callbacks(path, load_preset=self.load_preset)
        materialize(candidate)
        prepare(candidate)
        validate_init(candidate)

    def _read_status(self, path: Path) -> str:
        from lingtai.init_reader import read_init, reader_callbacks, InitReadStatus
        from lingtai.tools.psyche.settings import read_resolved_prompt_inputs

        materialize, prepare = reader_callbacks(path, load_preset=self.load_preset)
        outcome = read_init(path, materialize=materialize, prepare=prepare, failure_behavior="STOP")
        if outcome.status is InitReadStatus.READ_FAILED:
            return outcome.status.value
        read_resolved_prompt_inputs(path)
        return outcome.status.value

    def save_configured_member(self, seed: ConfiguredMemberSeed) -> ConfigurationWriteReceipt:
        init_written = manifest_written = psyche_written = False
        phase = "configuration_preflight_failed"
        reader_status = "not_read"
        try:
            path = self._member(seed.directory_name)
            self._preflight(path, seed.init_document)
            if seed.psyche_settings_json is not None:
                # Serialization already used the owning writer; existing strict owner is
                # read by the composition edge, then actual written bytes read below.
                from lingtai.tools.psyche.settings import read_prompt_owner_values
                read_prompt_owner_values(path)
            phase = "init_write_failed"
            self._safe_parent(path)
            _atomic_json(path / "init.json", seed.init_document, only_absent=seed.only_absent)
            init_written = True
            phase = "manifest_write_failed"
            for sub in ("inbox", "sent", "archive"):
                self._safe_parent(path / "mailbox" / sub)
            _atomic_json(path / ".agent.json", seed.agent_manifest)
            manifest_written = True
            if seed.psyche_settings_json is not None:
                phase = "psyche_write_failed"
                self._safe_parent(path / "settings")
                _atomic_text(path / "settings" / "psyche.json", seed.psyche_settings_json)
                psyche_written = True
            phase = "configuration_reader_failed"
            reader_status = self._read_status(path)
            if reader_status == "READ_FAILED":
                raise configuration_error(phase)
            return ConfigurationWriteReceipt(True, True, psyche_written, reader_status)
        except Exception:
            return ConfigurationWriteReceipt(init_written, manifest_written, psyche_written,
                                             reader_status, phase)

    def save_member_init(self, directory_name: str, document: dict,
                         *, only_absent: bool = False) -> ConfigurationWriteReceipt:
        written = False
        phase = "configuration_preflight_failed"
        reader_status = "not_read"
        try:
            path = self._member(directory_name)
            self._preflight(path, document)
            phase = "init_write_failed"
            self._safe_parent(path)
            _atomic_json(path / "init.json", document, only_absent=only_absent)
            written = True
            phase = "configuration_reader_failed"
            reader_status = self._read_status(path)
            if reader_status == "READ_FAILED":
                raise configuration_error(phase)
            return ConfigurationWriteReceipt(True, reader_status=reader_status)
        except Exception:
            return ConfigurationWriteReceipt(written, reader_status=reader_status, code=phase)
