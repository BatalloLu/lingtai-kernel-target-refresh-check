"""Synchronous init-presence exchange for inspection; no transport in Core."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import json
import os
from typing import TextIO

from lingtai.kernel.project import ProjectCreationError, ProjectError
from lingtai.kernel.project.inspection import (
    ProjectDirectoryObservation, ProjectInspectionPort, ProjectInspectionResult,
    ProjectInitObservation, ProjectInitPresence, ProjectInitStatFailure,
)


def _error(code: str, message: str = "inspect requires a bound init observation exchange") -> ProjectCreationError:
    return ProjectCreationError(ProjectError(code, message))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate field")
        value[key] = item
    return value


def _decode(text: str) -> dict[str, object]:
    value = json.loads(text, object_pairs_hook=_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _identity(name: str) -> str:
    return _b64(os.fsencode(name))


def _canonical_bytes(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("base64 string required")
    decoded = base64.b64decode(value, validate=True)
    if _b64(decoded) != value:
        raise ValueError("canonical base64 required")
    return decoded


@dataclass(frozen=True, slots=True)
class InspectionRequest:
    project_dir: str
    init_observation_mode: str = "native"


def read_inspection_request(stream: TextIO) -> InspectionRequest:
    """Complete callback first line only; ordinary JSON keeps its old EOF grammar."""
    try:
        first = stream.readline()
        # Detect the selector without weakening the new closed decoder. Legacy
        # duplicate-key/nonfinite behavior remains that of the original json.load.
        try:
            selected = json.loads(first)
        except ValueError:
            selected = None
        callback = (isinstance(selected, dict)
                    and selected.get("init_observation_mode") == "callback")
        if callback:
            if not first.endswith("\n"):
                raise ValueError("complete request line required")
            value = _decode(first)
        else:
            text = first + stream.read()
            value = json.load(io.StringIO(text))
        if (not isinstance(value, dict)
                or set(value) not in ({"project_dir"}, {"project_dir", "init_observation_mode"})
                or not isinstance(value["project_dir"], str) or not value["project_dir"]):
            raise _error("invalid_project_request", "inspect requires only a nonempty project_dir string")
        mode = value.get("init_observation_mode", "native")
        if mode not in ("native", "callback") or (mode == "callback" and not callback):
            raise ValueError("request mode")
        # An explicit native selector is new syntax too: require its closed JSON
        # semantics, but retain ordinary EOF/multiline and extra-value rejection.
        if "init_observation_mode" in value and not callback:
            value = _decode(text)
        return InspectionRequest(value["project_dir"], mode)
    except (ValueError, TypeError, UnicodeError, OSError):
        raise _error("invalid_project_request", "inspect requires a JSON object on stdin") from None


@dataclass(frozen=True, slots=True)
class _ObservedInit:
    sequence: int
    directory_name: str
    directory_name_b64: str
    observation: ProjectInitObservation


class JsonProjectInspectionAdapter(ProjectInspectionPort):
    """Decorate membership discovery, replacing only construction-bound init I/O."""
    def __init__(self, directory: ProjectInspectionPort, incoming: TextIO, outgoing: TextIO) -> None:
        self._directory = directory
        self._incoming = incoming
        self._outgoing = outgoing
        self._observed: list[_ObservedInit] = []
        self._pending = False
        self._stopped = False

    def observe_members(self) -> ProjectDirectoryObservation:
        return self._directory.observe_members()

    def observe_init_presence(self, directory_name: str) -> ProjectInitObservation:
        if self._stopped or self._pending:
            self._stopped = True
            raise _error("invalid_project_exchange") from None
        self._pending = True
        sequence = len(self._observed) + 1
        try:
            identity = _identity(directory_name)
            frame = {"status": "observe_init_presence", "sequence": sequence,
                     "directory_name_b64": identity}
            self._outgoing.write(json.dumps(frame, sort_keys=True) + "\n")
            self._outgoing.flush()
            line = self._incoming.readline()
            if not line.endswith("\n"):
                raise ValueError("incomplete observation")
            ack = _decode(line)
            if set(ack) != {"status", "sequence", "directory_name_b64", "presence", "failure"}:
                raise ValueError("observation fields")
            if (ack["status"] != "init_presence_observed" or type(ack["sequence"]) is not int
                    or ack["sequence"] != sequence or ack["directory_name_b64"] != identity):
                raise ValueError("observation binding")
            presence = ProjectInitPresence(ack["presence"])
            failure = None
            if presence is ProjectInitPresence.STAT_FAILED:
                facts = ack["failure"]
                if not isinstance(facts, dict) or set(facts) != {"path_b64", "native_errno", "native_winerror"}:
                    raise ValueError("failure fields")
                _canonical_bytes(facts["path_b64"])
                for key in ("native_errno", "native_winerror"):
                    if facts[key] is not None and type(facts[key]) is not int:
                        raise ValueError("native code")
                failure = ProjectInitStatFailure(**facts)
            elif ack["failure"] is not None:
                raise ValueError("unexpected failure")
            observation = ProjectInitObservation(presence, failure)
            self._observed.append(_ObservedInit(sequence, directory_name, identity, observation))
            self._pending = False
            return observation
        except Exception:
            self._stopped = True
            raise _error("invalid_project_exchange") from None

    def to_payload(self, result: ProjectInspectionResult) -> dict[str, object]:
        """Project the actual immutable result, binding every final item to its ack."""
        evidence = result.startup_readiness.init_evidence
        if (self._stopped or self._pending or len(evidence) != len(self._observed)
                or any(item.directory_name != seen.directory_name or item.observation != seen.observation
                       for item, seen in zip(evidence, self._observed))):
            raise _error("invalid_project_exchange") from None
        payload = result.to_payload()
        for member in payload["members"]:
            member["directory_name_b64"] = _identity(member["directory_name"])
        readiness = payload["startup_readiness"]
        readiness["agents_b64"] = [_identity(name) for name in result.startup_readiness.agents]
        readiness["orchestrators_b64"] = [_identity(name) for name in result.startup_readiness.orchestrators]
        for item, seen in zip(readiness["init_evidence"], self._observed):
            item.update(sequence=seen.sequence, directory_name_b64=seen.directory_name_b64)
        return payload
