"""Existing Project configuration policy; filesystem and owner readers stay outside."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import re
from dataclasses import dataclass, field, replace

from . import ProjectCreationError, ProjectError


def configuration_error(code: str) -> ProjectCreationError:
    # Static vocabulary: neither input documents nor caught exceptions escape.
    return ProjectCreationError(ProjectError(code, "Project configuration could not complete"))


def safe_member_name(name: str) -> bool:
    return (isinstance(name, str) and bool(name) and name == name.strip()
            and not name.startswith(".") and name != "human"
            and not any(c in name for c in ("/", "\\", ":", "\x00")))


@dataclass(frozen=True, slots=True)
class ConfigurationOptions:
    language: str = "en"
    karma: bool = True
    nirvana: bool = False
    preserve_active: bool = False
    allowed_presets: tuple[str, ...] = ()
    env_file: str = ""
    venv_path: str = ""
    addons: tuple[str, ...] = ()
    mcp: dict[str, object] = field(default_factory=dict)
    pad: str | None = None
    # These are the existing Go writer inputs, not new runtime settings.
    context_limit: int = 500000
    max_rpm: int = 60
    max_aed_attempts: int = 5


@dataclass(frozen=True, slots=True)
class ConfigureMemberRequest:
    directory_name: str
    agent_name: str
    preset_ref: str  # empty ONLY for Keep current
    keep_current: bool
    preset_manifest: dict[str, object]  # normalized public metadata, not credentials
    options: ConfigurationOptions
    psyche_settings_json: str | None = None  # opaque owner serialization


@dataclass(frozen=True, slots=True)
class MemberDocuments:
    directory_name: str
    init_present: bool
    init_document: dict[str, object] | None
    blueprint_present: bool
    blueprint: dict[str, object] | None
    init_error: bool = False
    blueprint_error: bool = False


@dataclass(frozen=True, slots=True)
class ConfiguredMemberSeed:
    directory_name: str
    init_document: dict[str, object]
    agent_manifest: dict[str, object]
    psyche_settings_json: str | None
    only_absent: bool = False


@dataclass(frozen=True, slots=True)
class ConfigurationWriteReceipt:
    init_written: bool = False
    manifest_written: bool = False
    psyche_written: bool = False
    reader_status: str = "not_read"
    code: str = ""


@dataclass(frozen=True, slots=True)
class ConfigurationResult:
    operation: str
    outcome: str
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    code: str = ""
    source: ConfigurationWriteReceipt = ConfigurationWriteReceipt()

    def to_payload(self) -> dict[str, object]:
        return {"status": "error" if self.code else self.operation,
                "outcome": self.outcome, "updated": self.updated,
                "skipped": self.skipped, "failed": self.failed, "code": self.code,
                "error": "Project configuration could not complete" if self.code else "",
                "source": {"init_written": self.source.init_written,
                           "manifest_written": self.source.manifest_written,
                           "psyche_written": self.source.psyche_written,
                           "reader_status": self.source.reader_status}}


class ProjectConfigurationPort(ABC):
    """One selected Project's documents and ordered, partial configuration writes."""

    @abstractmethod
    def human_manifest_exists(self) -> bool:
        """Observe legacy stat-success early-return evidence, without writing."""

    @abstractmethod
    def save_skeleton(self, human_manifest: dict[str, object],
                      mailboxes: tuple[str, ...], helpers: tuple[str, ...]) -> ConfigurationResult:
        """Write supplied human layout in order; partial writes remain on failure."""

    @abstractmethod
    def observe_member(self, directory_name: str) -> MemberDocuments:
        """Read raw documents with exact integers; do not materialize or repair."""

    @abstractmethod
    def observe_candidates(self) -> tuple[MemberDocuments, ...]:
        """Immediate real directories, sorted; no runtime or fleet observation."""

    @abstractmethod
    def save_configured_member(self, seed: ConfiguredMemberSeed) -> ConfigurationWriteReceipt:
        """Preflight, then init, mailboxes, manifest, optional Psyche; never roll back."""

    @abstractmethod
    def save_member_init(self, directory_name: str, document: dict[str, object],
                         *, only_absent: bool = False) -> ConfigurationWriteReceipt:
        """Write one init and read it using current owners. Absent-only refuses races."""


def _object(value: object) -> dict[str, object]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _reference(value: object) -> str:
    return value if isinstance(value, str) and value else ""


def _strip_explicit_legacy(document: dict[str, object]) -> None:
    # Exactly the retired top fields stripped by the inherited explicit writer.
    document.pop("principle_file", None)
    document.pop("procedures_file", None)


def configuration_seed(request: ConfigureMemberRequest, previous: MemberDocuments) -> ConfiguredMemberSeed:
    if not safe_member_name(request.directory_name) or not request.agent_name.strip():
        raise configuration_error("invalid_project_request")
    if previous.init_error or previous.blueprint_error:
        # Do not erase malformed user data by treating it as fresh.
        raise configuration_error("existing_document_unreadable")
    if not isinstance(request.preset_manifest.get("llm"), dict):
        raise configuration_error("invalid_preset")
    document = _object(previous.init_document)
    manifest = _object(document.get("manifest"))
    old_policy = _object(manifest.get("preset"))
    default = request.preset_ref
    active = default
    opts = request.options
    existing_allowed: list[str] = []
    if request.keep_current:
        if request.preset_ref or not opts.preserve_active:
            raise configuration_error("invalid_project_request")
        default = _reference(old_policy.get("default")) or _reference(old_policy.get("active"))
        if not default:
            raise configuration_error("keep_current_reference_missing")
    elif not default:
        raise configuration_error("invalid_preset")
    if opts.preserve_active:
        active = _reference(old_policy.get("active")) or default
        old_allowed = old_policy.get("allowed")
        if isinstance(old_allowed, list):
            existing_allowed = [v for v in old_allowed if isinstance(v, str) and v]
    if request.keep_current and not active:
        active = default
    allowed = list(dict.fromkeys([*(opts.allowed_presets or existing_allowed), default]))
    if active not in allowed:
        if opts.allowed_presets:
            active = default  # explicit revocation is authoritative
        else:
            allowed.append(active)
    manifest.update({"agent_name": request.agent_name, "language": opts.language or "en",
                     "llm": deepcopy(request.preset_manifest["llm"]),
                     "admin": {"karma": opts.karma, "nirvana": opts.nirvana},
                     "context_limit": opts.context_limit, "max_turns": 500,
                     "max_rpm": opts.max_rpm, "streaming": False,
                     "max_aed_attempts": 5 if opts.max_aed_attempts < 1 else min(100, opts.max_aed_attempts),
                     "preset": {"active": active, "default": default, "allowed": allowed}})
    if "capabilities" in request.preset_manifest:
        manifest["capabilities"] = deepcopy(request.preset_manifest["capabilities"])
    llm = manifest["llm"]
    llm.pop("api_compat", None)
    # This is matching public reference metadata, not provider implementation selection.
    caps = manifest.get("capabilities")
    if isinstance(caps, dict) and llm.get("provider") and llm.get("api_key_env"):
        for cfg in caps.values():
            if isinstance(cfg, dict) and cfg.get("provider") == llm["provider"]:
                cfg["api_key_env"] = llm["api_key_env"]
    _strip_explicit_legacy(document)
    document["manifest"] = manifest
    document["env_file"] = _reference(document.get("env_file")) or opts.env_file
    document["venv_path"] = _reference(document.get("venv_path")) or opts.venv_path
    if opts.pad is not None:
        document["pad"] = opts.pad
    else:
        document.setdefault("pad", "")
    old_addons = document.get("addons")
    if isinstance(old_addons, dict):
        # Go legacy names are identifier-filtered; deterministic order replaces map iteration.
        old_addons = sorted(k for k in old_addons if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", k))
    addons = old_addons if isinstance(old_addons, list) else list(opts.addons)
    if isinstance(old_addons, (dict, list)) or addons:
        document["addons"] = addons
    mcp = _object(document.get("mcp"))
    for name in addons:
        if isinstance(name, str) and name not in mcp and name in opts.mcp:
            mcp[name] = deepcopy(opts.mcp[name])
    if mcp:
        document["mcp"] = mcp
    blueprint = _object(previous.blueprint)
    if not previous.blueprint_present:
        blueprint["state"] = ""
    blueprint.update({"agent_name": request.agent_name, "address": request.directory_name,
                      "admin": {"karma": opts.karma, "nirvana": opts.nirvana}})
    return ConfiguredMemberSeed(request.directory_name, document, blueprint, request.psyche_settings_json)


class ProjectConfigurationUseCase:
    def __init__(self, workspace: ProjectConfigurationPort) -> None:
        self.workspace = workspace

    def initialize(self) -> ConfigurationResult:
        if self.workspace.human_manifest_exists():
            return ConfigurationResult("initialized", "unchanged")
        return self.workspace.save_skeleton(
            {"agent_name": "human", "address": "human", "admin": None},
            ("inbox", "sent", "archive"), (".tui-asset", ".library_shared"),
        )

    def configure(self, request: ConfigureMemberRequest) -> ConfigurationResult:
        if not safe_member_name(request.directory_name):
            raise configuration_error("invalid_project_request")
        seed = configuration_seed(request, self.workspace.observe_member(request.directory_name))
        receipt = self.workspace.save_configured_member(seed)
        outcome = ("rejected" if receipt.code == "configuration_preflight_failed" else "partial") if receipt.code else "complete"
        return ConfigurationResult("configured", outcome,
                                   updated=int(receipt.init_written), failed=int(bool(receipt.code)),
                                   code=receipt.code, source=receipt)

    def propagate_policy(self, selected: str, default: str, allowed: tuple[str, ...]) -> ConfigurationResult:
        if (selected and not safe_member_name(selected)) or not default or default not in allowed:
            raise configuration_error("invalid_project_request")
        updated = skipped = failed = 0
        first_code = ""
        for member in self.workspace.observe_candidates():
            if member.directory_name in {"human", selected} or not member.init_present:
                skipped += 1
                continue
            if member.init_error:
                failed += 1
                first_code = first_code or "member_document_unreadable"
                continue
            document = _object(member.init_document)
            manifest = document.get("manifest")
            policy = manifest.get("preset") if isinstance(manifest, dict) else None
            if not isinstance(policy, dict):
                skipped += 1
                continue
            _strip_explicit_legacy(document)
            policy.update({"active": policy.get("active") if policy.get("active") in allowed else default,
                           "default": default, "allowed": list(allowed)})
            receipt = self.workspace.save_member_init(member.directory_name, document)
            updated += int(receipt.init_written)
            failed += int(bool(receipt.code))
            first_code = first_code or receipt.code
        return ConfigurationResult("policy_propagated", "partial" if failed else "complete",
                                   updated, skipped, failed, first_code)

    def propagate_config(self, selected: str) -> ConfigurationResult:
        if not safe_member_name(selected):
            raise configuration_error("invalid_project_request")
        source = self.workspace.observe_member(selected)
        if source.init_error or not source.init_present:
            raise configuration_error("source_document_unreadable")
        source_manifest = _object(_object(source.init_document).get("manifest"))
        if not isinstance(source_manifest.get("llm"), dict):
            return ConfigurationResult("config_propagated", "unchanged")
        updated = skipped = failed = 0
        first_code = ""
        for member in self.workspace.observe_candidates():
            if member.directory_name in {"human", selected} or not member.init_present or member.init_error:
                skipped += 1
                continue
            document = _object(member.init_document)
            manifest = document.get("manifest")
            if not isinstance(manifest, dict):
                skipped += 1
                continue
            manifest["llm"] = deepcopy(source_manifest["llm"])
            if "capabilities" in source_manifest:
                manifest["capabilities"] = deepcopy(source_manifest["capabilities"])
            else:
                manifest.pop("capabilities", None)
            if "context_limit" in source_manifest:
                manifest["context_limit"] = source_manifest["context_limit"]
            manifest["admin"] = {"karma": False, "nirvana": False}
            document.pop("addons", None)
            if _reference(source.init_document.get("env_file")):
                document["env_file"] = source.init_document["env_file"]
            receipt = self.workspace.save_member_init(member.directory_name, document)
            updated += int(receipt.init_written)
            failed += int(bool(receipt.code))
            first_code = first_code or receipt.code
        return ConfigurationResult("config_propagated", "partial" if failed else "complete",
                                   updated, skipped, failed, first_code)

    def rehydrate(self, request: ConfigureMemberRequest) -> ConfigurationResult:
        """Gate before configuring source: all-present unchanged, mixed refused."""
        members = self.workspace.observe_candidates()
        agents: list[MemberDocuments] = []
        for member in members:
            if member.directory_name.startswith(".") or not member.blueprint_present:
                continue
            if member.blueprint_error:
                raise configuration_error("blueprint_unreadable")
            if member.blueprint is not None and member.blueprint.get("admin") is not None:
                agents.append(member)
        if not agents or request.directory_name not in {m.directory_name for m in agents}:
            raise configuration_error("rehydration_source_missing")
        present = sum(m.init_present for m in agents)
        if present == len(agents):
            return ConfigurationResult("rehydrated", "unchanged", skipped=len(agents))
        if present:
            raise configuration_error("mixed_initialization_state")
        selected = next(m for m in agents if m.directory_name == request.directory_name)
        identity = _reference(selected.blueprint.get("agent_name")) or selected.directory_name
        seed = replace(configuration_seed(replace(request, agent_name=identity), selected), only_absent=True)
        receipt = self.workspace.save_configured_member(seed)
        if receipt.code:
            outcome = "rejected" if receipt.code == "configuration_preflight_failed" else "partial"
            return ConfigurationResult("rehydrated", outcome, int(receipt.init_written), 0, 1,
                                       receipt.code, receipt)
        updated = 1
        for member in agents:
            if member.directory_name == request.directory_name:
                continue
            document = deepcopy(seed.init_document)
            _strip_explicit_legacy(document)
            document["manifest"]["agent_name"] = _reference(member.blueprint.get("agent_name")) or member.directory_name
            document["manifest"]["admin"] = {}
            document.pop("addons", None)
            result = self.workspace.save_member_init(member.directory_name, document, only_absent=True)
            updated += int(result.init_written)
            if result.code:
                return ConfigurationResult("rehydrated", "partial", updated, 0, 1, result.code, receipt)
        return ConfigurationResult("rehydrated", "complete", updated, source=receipt)
