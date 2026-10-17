"""Running Project inventory policy over native observations, without native I/O.

Identity and collation keys are opaque bytes supplied by the observing adapter.
In particular Core must not normalize paths or repeat a platform's case mapping.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunningMemberObservation:
    row: int
    directory: bytes
    project: bytes
    project_order: bytes
    name_order: bytes
    directory_order: bytes
    pid: int
    duplicate_runtime_pid: int
    admin_null: bool
    admin_flags: tuple[bool, ...]
    manifest_failed: bool


@dataclass(frozen=True, slots=True)
class RunningProjectObservation:
    identity: bytes
    container_missing: bool


@dataclass(frozen=True, slots=True)
class InventoryObservation:
    members: tuple[RunningMemberObservation, ...]
    projects: tuple[RunningProjectObservation, ...]
    include_human: bool


@dataclass(frozen=True, slots=True)
class RunningMemberDecision:
    row: int
    directory: bytes
    pid: int
    role: str
    human: bool
    orchestrator: bool
    phantom: bool
    reason: str


@dataclass(frozen=True, slots=True)
class InventoryDecision:
    members: tuple[RunningMemberDecision, ...]
    groups: tuple[tuple[int, ...], ...]
    phantom_projects: tuple[int, ...]


def classify_member(member: RunningMemberObservation, phantom: bool) -> RunningMemberDecision:
    orchestrator = any(member.admin_flags)
    human = member.admin_null and not orchestrator
    role = "MAIN" if orchestrator else "HUMAN" if human else "?" if member.manifest_failed else "AGENT"
    if not member.directory:
        reason = "agent_dir_missing"
    elif not member.project:
        reason = "path_not_under_project"
    elif phantom:
        reason = "phantom_project"
    elif member.manifest_failed:
        reason = "manifest_unreadable"
    elif human:
        reason = "human_target"
    elif not orchestrator:
        reason = "non_admin_target"
    else:
        reason = ""
    return RunningMemberDecision(member.row, member.directory, member.pid, role, human, orchestrator, phantom, reason)


def query_inventory(observation: InventoryObservation) -> InventoryDecision:
    """Collapse in discovery order, classify, then stable-sort and group.

    Each duplicate's runtime PID is the observation made at that duplicate, not
    a later shared status read. First wins unless that later candidate matches
    its own nonzero advertised runtime PID, exactly as the native inventory did.
    Heartbeat freshness is deliberately not an eligibility observation.
    """
    selected: list[RunningMemberObservation] = []
    by_directory: dict[bytes, int] = {}
    for member in observation.members:
        previous = by_directory.get(member.directory) if member.directory else None
        if previous is None:
            if member.directory:
                by_directory[member.directory] = len(selected)
            selected.append(member)
        elif member.duplicate_runtime_pid != 0 and member.pid == member.duplicate_runtime_pid:
            selected[previous] = member

    phantom_projects = tuple(sorted(
        (i for i, project in enumerate(observation.projects) if project.container_missing),
        key=lambda i: observation.projects[i].identity,
    ))
    missing = {observation.projects[i].identity for i in phantom_projects}
    classified = [(member, classify_member(member, member.project in missing)) for member in selected]
    if not observation.include_human:
        classified = [(member, decision) for member, decision in classified if not decision.human]
    role_order = {"MAIN": 0, "AGENT": 1, "?": 2, "HUMAN": 3}
    classified.sort(key=lambda pair: (
        pair[0].project_order, role_order[pair[1].role], pair[0].name_order,
        pair[0].directory_order, pair[0].pid,
    ))
    groups: list[list[int]] = []
    by_project: dict[bytes, int] = {}
    for member, decision in classified:
        group = by_project.get(member.project)
        if group is None:
            group = len(groups)
            by_project[member.project] = group
            groups.append([])
        groups[group].append(decision.row)
    return InventoryDecision(tuple(decision for _, decision in classified),
                             tuple(tuple(group) for group in groups), phantom_projects)
