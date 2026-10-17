"""External Project actions, distinct from an Agent's self-lifecycle.

Core chooses eligibility and phase order. The construction-bound native port
observes/effects original targets; target integers are opaque local handles,
never paths. Failed best-effort effects remain in the exchange transcript.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class LifecycleMember:
    target: int
    human: bool


@dataclass(frozen=True)
class LifecycleObservation:
    sequence: int
    flag: bool = False
    failed: bool = False
    ownership_changed: bool = False
    members: tuple[LifecycleMember, ...] = ()


class ExternalLifecyclePort(Protocol):
    """Synchronous once-only native effects; exceptions stop, never retry.

    ``failed`` retains a native error under this observation's sequence. Only
    a validated terminal may return that error to the original caller. Lock
    probes retain native can't-open-as-unlocked behavior. Sleep units are ms;
    the only intervals selected here are the original 500/250 ms intervals.
    Existing launch/heartbeat and clear wait primitives retain native timing.
    """
    def discover(self) -> LifecycleObservation: ...
    def alive(self, target: int, *, clear: bool = False) -> LifecycleObservation: ...
    def external_owner(self, target: int) -> LifecycleObservation: ...
    def write_signal(self, target: int, signal: Literal["sleep", "suspend", "clear"]) -> LifecycleObservation: ...
    def probe_lock(self, target: int) -> LifecycleObservation: ...
    def sleep(self, milliseconds: Literal[250, 500]) -> LifecycleObservation: ...
    def remove_handshake(self, target: int, name: Literal["lock", "refresh", "refresh_taken", "suspend"]) -> LifecycleObservation: ...
    def running(self, target: int) -> LifecycleObservation: ...
    def terminate(self, target: int) -> LifecycleObservation: ...
    def preset(self, target: int, *, explicit: bool) -> LifecycleObservation: ...
    def launch(self, target: int, *, force: bool) -> LifecycleObservation: ...
    def heartbeat(self, target: int) -> LifecycleObservation: ...
    def revive_for_clear(self, target: int) -> LifecycleObservation: ...
    def clear_alive_wait(self, target: int) -> LifecycleObservation: ...
    def clear_capture(self, target: int) -> LifecycleObservation: ...
    def clear_completion_wait(self, target: int) -> LifecycleObservation: ...
    def clear_suspend(self, target: int) -> LifecycleObservation: ...
    def clean_wait_start(self, count: int) -> LifecycleObservation: ...
    def clean_before_deadline(self) -> LifecycleObservation: ...
    def clean_survivor_notice(self, count: int) -> LifecycleObservation: ...
    def suspend_wait(self, target: int) -> LifecycleObservation: ...
    def reset_barrier(self) -> LifecycleObservation: ...
    def remove_tree(self) -> LifecycleObservation: ...


@dataclass(frozen=True)
class LifecycleFailure:
    target: int
    sequence: int


@dataclass
class LifecycleResult:
    code: str = "ok"
    error_sequence: int = 0
    count: int = 0
    completed: bool = False
    already_alive: bool = False
    failures: list[LifecycleFailure] = field(default_factory=list)
    survivors: list[int] = field(default_factory=list)


def _native(observation: LifecycleObservation) -> LifecycleResult:
    return LifecycleResult(code="native", error_sequence=observation.sequence)


class ExternalLifecycleUseCase:
    def __init__(self, native: ExternalLifecyclePort) -> None:
        self.native = native

    def signal(self, signal: Literal["sleep", "suspend"], *, all_targets: bool,
               selected: bool) -> LifecycleResult:
        result = LifecycleResult()
        if all_targets:
            # Discovery errors were ignored, including any returned partial rows.
            for member in self.native.discover().members:
                if not member.human and self.native.alive(member.target).flag:
                    self.native.write_signal(member.target, signal)
                    result.count += 1  # attempted writes, not successful writes
        elif selected:
            self.native.write_signal(0, signal)  # deliberately NO alive/role gate
            result.count = 1
        return result

    def _wait_lock(self, target: int) -> None:
        for _ in range(120):
            if self.native.probe_lock(target).flag:
                return
            self.native.sleep(500)
        self.native.remove_handshake(target, "lock")

    def refresh(self, target: int = 0, *, explicit: bool = False) -> LifecycleResult:
        owner = self.native.external_owner(target)
        if owner.flag:
            return _native(owner)
        self.native.write_signal(target, "suspend")
        self._wait_lock(target)
        if self.native.running(target).flag:
            stopped = self.native.terminate(target)
            if stopped.ownership_changed:
                return _native(stopped)  # preserve the new owner's lock
            # Other termination errors were swallowed by both old refresh paths.
        for name in ("lock", "refresh", "refresh_taken", "suspend"):
            self.native.remove_handshake(target, name)
        self.native.preset(target, explicit=explicit)  # failure STILL relaunches
        launched = self.native.launch(target, force=True)
        self.native.remove_handshake(target, "suspend")  # also on failed launch
        if launched.failed:
            return _native(launched)
        heartbeat = self.native.heartbeat(target)
        return _native(heartbeat) if heartbeat.failed else LifecycleResult()

    def revive(self, target: int = 0) -> LifecycleResult:
        owner = self.native.external_owner(target)
        if owner.flag:
            return _native(owner)
        self._wait_lock(target)
        launched = self.native.launch(target, force=False)
        if launched.failed:
            return _native(launched)
        heartbeat = self.native.heartbeat(target)
        return _native(heartbeat) if heartbeat.failed else LifecycleResult()

    def cpr(self, *, all_targets: bool, selected: bool) -> LifecycleResult:
        result = LifecycleResult()
        if all_targets:
            for member in self.native.discover().members:
                if not member.human and not self.native.alive(member.target).flag:
                    result.count += 1
                    outcome = self.revive(member.target)
                    if outcome.code != "ok":
                        result.failures.append(LifecycleFailure(member.target, outcome.error_sequence))
        elif selected:
            if self.native.alive(0).flag:
                result.already_alive = True
            else:
                return self.revive()
        return result

    def refresh_all(self) -> LifecycleResult:
        result = LifecycleResult()
        for member in self.native.discover().members:
            if not member.human:
                result.count += 1
                outcome = self.refresh(member.target)
                if outcome.code != "ok":
                    result.failures.append(LifecycleFailure(member.target, outcome.error_sequence))
        return result

    def clear(self) -> LifecycleResult:
        if self.native.alive(0, clear=True).flag:
            written = self.native.write_signal(0, "clear")
            return _native(written) if written.failed else LifecycleResult()
        # This child action uses the same Core revive through the bound native
        # caller's existing dependency seam; it is not a new native launch mode.
        revived = self.native.revive_for_clear(0)
        if revived.failed:
            return _native(revived)
        alive = self.native.clear_alive_wait(0)
        if alive.failed:
            self.native.clear_suspend(0)
            return _native(alive)
        self.native.clear_capture(0)  # AFTER revive, before this request's signal
        written = self.native.write_signal(0, "clear")
        if written.failed:
            self.native.clear_suspend(0)
            return _native(written)
        waited = self.native.clear_completion_wait(0)
        suspended = self.native.clear_suspend(0)
        if waited.failed:
            return _native(waited)
        result = _native(suspended) if suspended.failed else LifecycleResult()
        result.completed = True
        return result

    def clean(self, *, force: bool) -> LifecycleResult:
        discovered = self.native.discover()
        if discovered.failed and not force:
            return LifecycleResult(code="discovery", error_sequence=discovered.sequence)
        alive: list[int] = []
        for member in discovered.members:
            if member.human:
                continue
            self.native.write_signal(member.target, "suspend")
            if self.native.alive(member.target).flag:
                alive.append(member.target)
        if alive:
            self.native.clean_wait_start(len(alive))
            while self.native.clean_before_deadline().flag:
                if not any(self.native.alive(target).flag for target in alive):
                    break
                self.native.sleep(250)
        current = self.native.discover()
        if current.failed and not force:
            return LifecycleResult(code="rediscovery", error_sequence=current.sequence)
        guarded = list(alive)
        if not current.failed:
            # Preserve old seen-map quirk: only original-alive rows are marked;
            # duplicate new rows (if discovery ever emits them) stay duplicate.
            seen = set(guarded)
            guarded.extend(member.target for member in current.members
                           if not member.human and member.target not in seen)
        survivors = [target for target in guarded if self.native.alive(target).flag]
        if survivors and not force:
            return LifecycleResult(code="survivors", survivors=survivors)
        if survivors:
            self.native.clean_survivor_notice(len(survivors))
        removed = self.native.remove_tree()
        if removed.failed:
            result = _native(removed)
            result.survivors = survivors
            return result
        return LifecycleResult(survivors=survivors)

    def nirvana(self) -> LifecycleResult:
        # Unlike CLI clean this does NOT rediscover, union or refuse survivors.
        for member in self.native.discover().members:
            if not member.human and self.native.alive(member.target).flag:
                self.native.suspend_wait(member.target)  # sequential, native 5s
        self.native.reset_barrier()  # exact Go mutex; UI already drained Mail
        self.native.remove_tree()  # native failures intentionally ignored
        return LifecycleResult()


@dataclass(frozen=True)
class PresetCandidate:
    exact: bool
    stem: bool


class ExternalPresetResolutionPort(Protocol):
    """Native decode/path spelling only; no already-selected preset result."""
    def candidates(self) -> tuple[PresetCandidate, ...]: ...


@dataclass(frozen=True)
class PresetResolution:
    code: str
    index: int = -1
    matches: int = 0


def resolve_external_preset(*, query_nonempty: bool,
                            native: ExternalPresetResolutionPort) -> PresetResolution:
    # Empty queries never read the native allowed-list, just as before.
    if not query_nonempty:
        return PresetResolution("empty")
    candidates = native.candidates()
    if not candidates:
        return PresetResolution("no_allowed")
    for index, candidate in enumerate(candidates):
        if candidate.exact:
            return PresetResolution("ok", index)
    matches = [index for index, candidate in enumerate(candidates) if candidate.stem]
    if len(matches) == 1:
        return PresetResolution("ok", matches[0])
    return PresetResolution("ambiguous", matches=len(matches)) if matches else PresetResolution("not_allowed")
