"""Operation-specific JSON-lines driver and outer prerequisite acknowledgement."""
from __future__ import annotations

import json
from typing import TextIO

from lingtai.kernel.project.interactive_creation import (
    CreationAttempt, CreationPrerequisitePort, InteractiveCreateRequest,
    InteractiveOptions, ProcessEvidence, creation_error,
)

_MAX_LINE = 1024 * 1024


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate field")
        value[key] = item
    return value


def read_exchange_line(stream: TextIO) -> dict[str, object]:
    try:
        line = stream.readline(_MAX_LINE + 1)
        if not line.endswith("\n") or len(line) > _MAX_LINE:
            raise ValueError("incomplete or oversized exchange")
        value = json.loads(line, object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except (ValueError, UnicodeError, OSError):
        raise creation_error("invalid_project_exchange") from None


def decode_creation_request(value: dict[str, object]) -> InteractiveCreateRequest:
    from lingtai.kernel.workdir import _is_secret_key
    import re

    required = {"project_dir", "approved_root", "agent_name", "directory_name", "preset_ref",
                "preset_manifest", "options", "recipe", "process_evidence"}
    if not required <= value.keys() or value.keys() - required - {"location", "commands"}:
        raise creation_error("invalid_project_request")
    def check_credentials(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if _is_secret_key(key):
                    # The reference itself is public, never the referenced value.
                    if not (key.endswith("_env") and isinstance(child, str)
                            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", child)):
                        raise creation_error("credentials_must_remain_outer")
                check_credentials(child)
        elif isinstance(item, list):
            for child in item:
                check_credentials(child)
    check_credentials(value)
    for key in required - {"preset_manifest", "options"} | {"location", "commands"}:
        if key in value and not isinstance(value[key], str):
            raise creation_error("invalid_project_request")
    if not isinstance(value["preset_manifest"], dict) or not isinstance(value["options"], dict):
        raise creation_error("invalid_project_request")
    options = value["options"]
    allowed = {"language", "covenant", "karma", "nirvana", "pad", "base_prompt", "env_file",
               "venv_path", "addons", "allowed_presets", "mcp"}
    if not {"language", "covenant"} <= options.keys() or options.keys() - allowed:
        raise creation_error("invalid_project_request")
    for key in allowed - {"karma", "nirvana", "addons", "allowed_presets", "mcp"}:
        if key in options and not isinstance(options[key], str):
            raise creation_error("invalid_project_request")
    for key in ("karma", "nirvana"):
        if key in options and type(options[key]) is not bool:
            raise creation_error("invalid_project_request")
    for key in ("addons", "allowed_presets"):
        if key in options and (not isinstance(options[key], list)
                              or not all(isinstance(item, str) and item for item in options[key])):
            raise creation_error("invalid_project_request")
    if "mcp" in options and not isinstance(options["mcp"], dict):
        raise creation_error("invalid_project_request")
    try:
        evidence = ProcessEvidence(value["process_evidence"])
        typed_options = InteractiveOptions(**{
            **options,
            "addons": tuple(options.get("addons", [])),
            "allowed_presets": tuple(options.get("allowed_presets", [])),
        })
        return InteractiveCreateRequest(
            **{key: value[key] for key in required - {"options", "process_evidence"}},
            options=typed_options, process_evidence=evidence,
            location=value.get("location", "unknown"), commands=value.get("commands", ""),
        )
    except (ValueError, TypeError):
        raise creation_error("invalid_project_request") from None


class JsonCreationPrerequisiteAdapter(CreationPrerequisitePort):
    def __init__(self, incoming: TextIO, outgoing: TextIO) -> None:
        self.incoming = incoming
        self.outgoing = outgoing

    def persist_and_verify(self, attempt: CreationAttempt, preset_ref: str) -> bool:
        self.outgoing.write(json.dumps({
            "status": "ready_for_prerequisites", "committed": False,
            "attempt_id": attempt.attempt_id, "preset_ref": preset_ref,
        }, sort_keys=True) + "\n")
        self.outgoing.flush()
        ack = read_exchange_line(self.incoming)
        if (set(ack) != {"status", "attempt_id", "preset_ref", "accepted"}
                or ack["status"] != "prerequisites_acknowledged"
                or ack["attempt_id"] != attempt.attempt_id or ack["preset_ref"] != preset_ref
                or type(ack["accepted"]) is not bool):
            raise creation_error("invalid_prerequisite_acknowledgement")
        return ack["accepted"]
