"""Read-only Project membership policy; presence remains the evidence owner."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from lingtai.kernel.agent_presence import ManifestKind, ManifestObservation, is_agent, is_human


class ProjectMemberRole(str, Enum):
    HUMAN = "human"
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProjectMemberEvidence:
    directory_name: str
    manifest: ManifestObservation


@dataclass(frozen=True, slots=True)
class ProjectDirectoryObservation:
    initialized: bool
    candidates: tuple[ProjectMemberEvidence, ...]


class ProjectInitPresence(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    STAT_FAILED = "stat_failed"


@dataclass(frozen=True, slots=True)
class ProjectInitStatFailure:
    """Opaque outer-owned native facts; Core never interprets native codes."""
    path_b64: str
    native_errno: int | None
    native_winerror: int | None

    def to_payload(self) -> dict[str, object]:
        return {
            "path_b64": self.path_b64,
            "native_errno": self.native_errno,
            "native_winerror": self.native_winerror,
        }


@dataclass(frozen=True, slots=True)
class ProjectInitObservation:
    presence: ProjectInitPresence
    failure: ProjectInitStatFailure | None = None


@dataclass(frozen=True, slots=True)
class ProjectMemberInitEvidence:
    directory_name: str
    observation: ProjectInitObservation

    def to_payload(self) -> dict[str, object]:
        return {
            "directory_name": self.directory_name,
            "presence": self.observation.presence.value,
            "failure": self.observation.failure.to_payload() if self.observation.failure else None,
        }


class ProjectStartupReason(str, Enum):
    NOT_INITIALIZED = "not_initialized"
    READY = "ready"
    CANNOT_STAT_INIT = "cannot_stat_init"
    MIXED_INIT = "mixed_init"
    NO_AGENTS = "no_agents"
    NO_ORCHESTRATOR = "no_orchestrator"
    MULTIPLE_ORCHESTRATORS = "multiple_orchestrators"


@dataclass(frozen=True, slots=True)
class ProjectStartupReadiness:
    reason: ProjectStartupReason
    needs_rehydration: bool
    agents: tuple[str, ...]
    orchestrators: tuple[str, ...]
    init_evidence: tuple[ProjectMemberInitEvidence, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "reason": self.reason.value,
            "needs_rehydration": self.needs_rehydration,
            "agents": list(self.agents),
            "orchestrators": list(self.orchestrators),
            "init_evidence": [item.to_payload() for item in self.init_evidence],
        }


class ProjectInspectionPort(ABC):
    """Construction-bound directory discovery, not a generic storage interface."""

    @abstractmethod
    def observe_members(self) -> ProjectDirectoryObservation:
        """Observe immediate member candidates without mutating Project state.

        An absent Project returns initialized=False, candidates=(). Enumeration
        failure raises ProjectCreationError; a malformed member stays evidence.
        This is a sequential observation, not a consistent snapshot or lock.
        """

    @abstractmethod
    def observe_init_presence(self, directory_name: str) -> ProjectInitObservation:
        """Stat one observed member's init, without reading/validating its contents.

        Successful stat of any target is PRESENT; missing is ABSENT; other
        failures return STAT_FAILED with minimal opaque native facts. Called
        sequentially in directory-name order only for startup-eligible members.
        """


@dataclass(frozen=True, slots=True)
class ProjectMemberObservation:
    directory_name: str
    manifest_kind: ManifestKind
    role: ProjectMemberRole
    agent_name: str
    address: str
    agent_id: str

    def to_payload(self) -> dict[str, object]:
        # Never return the complete manifest: it can contain arbitrary fields.
        return {
            "directory_name": self.directory_name,
            "manifest_kind": self.manifest_kind.value,
            "role": self.role.value,
            "agent_name": self.agent_name,
            "address": self.address,
            "agent_id": self.agent_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectInspectionResult:
    initialized: bool
    members: tuple[ProjectMemberObservation, ...]
    startup_readiness: ProjectStartupReadiness

    def to_payload(self) -> dict[str, object]:
        return {
            "status": "inspected",
            "initialized": self.initialized,
            "members": [member.to_payload() for member in self.members],
            "startup_readiness": self.startup_readiness.to_payload(),
        }


def _text(observation: ManifestObservation, key: str) -> str:
    value = observation.data.get(key)
    return value if isinstance(value, str) else ""


def observe_member(evidence: ProjectMemberEvidence) -> ProjectMemberObservation:
    """Classify identity independently of directory spelling and display name."""
    manifest = evidence.manifest
    if manifest.kind is not ManifestKind.VALID:
        role = ProjectMemberRole.UNKNOWN
    elif is_human(manifest):
        role = ProjectMemberRole.HUMAN
    else:
        admin = manifest.data.get("admin")
        # Only literal booleans grant privileges, matching the Go detector.
        role = (
            ProjectMemberRole.ORCHESTRATOR
            if isinstance(admin, dict) and any(value is True for value in admin.values())
            else ProjectMemberRole.WORKER
        )
    return ProjectMemberObservation(
        directory_name=evidence.directory_name,
        manifest_kind=manifest.kind,
        role=role,
        agent_name=_text(manifest, "agent_name"),
        address=_text(manifest, "address"),
        agent_id=_text(manifest, "agent_id"),
    )


class ProjectInspectionUseCase:
    def __init__(self, directory: ProjectInspectionPort) -> None:
        self._directory = directory

    def inspect(self) -> ProjectInspectionResult:
        observation = self._directory.observe_members()
        members = tuple(
            observe_member(candidate)
            for candidate in sorted(observation.candidates, key=lambda member: member.directory_name)
            if is_agent(candidate.manifest)
        )
        readiness = self._startup_readiness(observation.initialized, members)
        return ProjectInspectionResult(observation.initialized, members, readiness)

    def _startup_readiness(
        self, initialized: bool, members: tuple[ProjectMemberObservation, ...],
    ) -> ProjectStartupReadiness:
        # This is the startup subset, not global Agent Presence membership.
        eligible = tuple(member for member in members
                         if not member.directory_name.startswith(".")
                         and member.manifest_kind is ManifestKind.VALID
                         and member.role in (ProjectMemberRole.WORKER, ProjectMemberRole.ORCHESTRATOR))
        agents = tuple(member.directory_name for member in eligible)
        orchestrators = tuple(member.directory_name for member in eligible
                              if member.role is ProjectMemberRole.ORCHESTRATOR)
        evidence: list[ProjectMemberInitEvidence] = []
        if not initialized:
            return ProjectStartupReadiness(ProjectStartupReason.NOT_INITIALIZED, False, (), (), ())
        for name in agents:
            init = self._directory.observe_init_presence(name)
            evidence.append(ProjectMemberInitEvidence(name, init))
            if init.presence is ProjectInitPresence.STAT_FAILED:
                return ProjectStartupReadiness(ProjectStartupReason.CANNOT_STAT_INIT, False,
                                               agents, orchestrators, tuple(evidence))
        with_init = any(item.observation.presence is ProjectInitPresence.PRESENT for item in evidence)
        without_init = any(item.observation.presence is ProjectInitPresence.ABSENT for item in evidence)
        if with_init and without_init:
            return ProjectStartupReadiness(ProjectStartupReason.MIXED_INIT, False,
                                           agents, orchestrators, tuple(evidence))
        needs_rehydration = not with_init and without_init
        if not agents:
            reason = ProjectStartupReason.NO_AGENTS
        elif not orchestrators:
            reason = ProjectStartupReason.NO_ORCHESTRATOR
        elif len(orchestrators) > 1:
            reason = ProjectStartupReason.MULTIPLE_ORCHESTRATORS
        else:
            reason = ProjectStartupReason.READY
        return ProjectStartupReadiness(reason, needs_rehydration, agents, orchestrators, tuple(evidence))
