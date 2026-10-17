"""Closed, synchronous external-Project native exchange (not a general RPC)."""
from __future__ import annotations

import json
from typing import TextIO

from lingtai.kernel.project.external_lifecycle import LifecycleMember, LifecycleObservation


class LifecycleExchangeStopped(Exception):
    """Unknown partial native effects; no retry, rollback, repair or fallback."""


def decode_lifecycle_object(text: str) -> dict:
    def closed(pairs: list[tuple[str, object]]) -> dict:
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate lifecycle field")
            value[key] = item
        return value
    def nonfinite(_: str) -> None:
        raise ValueError("nonfinite lifecycle number")
    value = json.loads(text, object_pairs_hook=closed, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("lifecycle object required")
    return value


class JsonProjectLifecycleAdapter:
    def __init__(self, request_id: str, incoming: TextIO, outgoing: TextIO) -> None:
        self.request_id = request_id
        self.incoming = incoming
        self.outgoing = outgoing
        self.transcript: list[dict] = []
        self.stopped = False
        self.pending = False

    def _exchange(self, operation: str, target: int = -1, argument: str = "") -> LifecycleObservation:
        if self.stopped or self.pending:
            self.stopped = True
            raise LifecycleExchangeStopped()
        self.pending = True
        sequence = len(self.transcript) + 1
        frame = {"status": "project_lifecycle_native", "request_id": self.request_id,
                 "sequence": sequence, "operation": operation,
                 "target": target, "argument": argument}
        try:
            self.outgoing.write(json.dumps(frame, sort_keys=True) + "\n")
            self.outgoing.flush()
            line = self.incoming.readline()
            if not line.endswith("\n"):
                raise ValueError("incomplete lifecycle acknowledgement")
            ack = decode_lifecycle_object(line)
            if set(ack) != set(frame) | {"flag", "failed", "ownership_changed", "members"}:
                raise ValueError("lifecycle acknowledgement fields")
            expected = dict(frame, status="project_lifecycle_observed")
            if any(type(ack[key]) is not type(value) or ack[key] != value
                   for key, value in expected.items()):
                raise ValueError("lifecycle acknowledgement binding")
            if any(type(ack[key]) is not bool for key in ("flag", "failed", "ownership_changed")):
                raise ValueError("lifecycle acknowledgement facts")
            if not isinstance(ack["members"], list):
                raise ValueError("lifecycle members")
            members = []
            for item in ack["members"]:
                if (not isinstance(item, dict) or set(item) != {"target", "human"}
                        or type(item["target"]) is not int or item["target"] < 1
                        or type(item["human"]) is not bool):
                    raise ValueError("lifecycle member")
                members.append(LifecycleMember(**item))
            if operation != "discover" and members:
                raise ValueError("unexpected lifecycle members")
            if ack["ownership_changed"] and (operation != "terminate" or not ack["failed"]):
                raise ValueError("lifecycle ownership evidence")
            self.transcript.append(ack)
            self.pending = False
            return LifecycleObservation(sequence, ack["flag"], ack["failed"],
                                        ack["ownership_changed"], tuple(members))
        except Exception:
            self.stopped = True
            raise LifecycleExchangeStopped() from None

    def discover(self): return self._exchange("discover")
    def alive(self, target, *, clear=False): return self._exchange("alive", target, "clear" if clear else "standard")
    def external_owner(self, target): return self._exchange("external_owner", target)
    def write_signal(self, target, signal): return self._exchange("write_signal", target, signal)
    def probe_lock(self, target): return self._exchange("probe_lock", target)
    def sleep(self, milliseconds): return self._exchange("sleep", argument=str(milliseconds))
    def remove_handshake(self, target, name): return self._exchange("remove_handshake", target, name)
    def running(self, target): return self._exchange("running", target)
    def terminate(self, target): return self._exchange("terminate", target)
    def preset(self, target, *, explicit): return self._exchange("preset", target, "explicit" if explicit else "default")
    def launch(self, target, *, force): return self._exchange("launch", target, "force" if force else "normal")
    def heartbeat(self, target): return self._exchange("heartbeat", target)
    def revive_for_clear(self, target): return self._exchange("revive_for_clear", target)
    def clear_alive_wait(self, target): return self._exchange("clear_alive_wait", target)
    def clear_capture(self, target): return self._exchange("clear_capture", target)
    def clear_completion_wait(self, target): return self._exchange("clear_completion_wait", target)
    def clear_suspend(self, target): return self._exchange("clear_suspend", target)
    def clean_wait_start(self, count): return self._exchange("clean_wait_start", argument=str(count))
    def clean_before_deadline(self): return self._exchange("clean_before_deadline")
    def clean_survivor_notice(self, count): return self._exchange("clean_survivor_notice", argument=str(count))
    def suspend_wait(self, target): return self._exchange("suspend_wait", target)
    def reset_barrier(self): return self._exchange("reset_barrier")
    def remove_tree(self): return self._exchange("remove_tree")


class JsonExternalPresetResolutionAdapter:
    """One read-only native allowed-list observation, no native paths on wire."""
    def __init__(self, request_id: str, incoming: TextIO, outgoing: TextIO) -> None:
        self.request_id, self.incoming, self.outgoing = request_id, incoming, outgoing
        self.observed: list[dict] = []
        self.attempted = False

    def candidates(self):
        from lingtai.kernel.project.external_lifecycle import PresetCandidate
        if self.attempted:
            raise LifecycleExchangeStopped()
        self.attempted = True
        frame = dict(status="project_preset_candidates", request_id=self.request_id, sequence=1)
        self.outgoing.write(json.dumps(frame, sort_keys=True) + "\n")
        self.outgoing.flush()
        line = self.incoming.readline()
        if not line.endswith("\n"):
            raise LifecycleExchangeStopped()
        ack = decode_lifecycle_object(line)
        if (set(ack) != {"status", "request_id", "sequence", "candidates"}
                or ack["status"] != "project_preset_observed" or ack["request_id"] != self.request_id
                or type(ack["sequence"]) is not int or ack["sequence"] != 1
                or not isinstance(ack["candidates"], list)):
            raise LifecycleExchangeStopped()
        for item in ack["candidates"]:
            if (not isinstance(item, dict) or set(item) != {"exact", "stem"}
                    or type(item["exact"]) is not bool or type(item["stem"]) is not bool):
                raise LifecycleExchangeStopped()
        self.observed = ack["candidates"]
        return tuple(PresetCandidate(**item) for item in self.observed)
