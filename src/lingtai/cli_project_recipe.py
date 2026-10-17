"""Strict JSON stdin composition for existing local Recipe operations."""
from __future__ import annotations

from dataclasses import asdict
import io
import json
import logging
from pathlib import Path
import sys

from lingtai.cli_project_configuration import read_request, _keys
from lingtai.kernel.project import ProjectCreationError
from lingtai.kernel.project.recipe import (
    ProjectRecipeUseCase, RecipeApplyRequest, RecipeApplyResult, RecipeObservation,
    RecipeRendering, RecipeState, RecipeExchangeStopped, RecipeOperationError, recipe_error,
)

OPERATIONS = ("recipe-observe", "recipe-apply", "recipe-layer")


def observation_payload(result: RecipeObservation, code: str = "") -> dict:
    return {"status": "error" if code else "recipe_observed", "state": result.state.value,
            "needs_apply": result.needs_apply, "code": code,
            "error": "Project Recipe operation could not complete" if code else ""}


def apply_payload(result: RecipeApplyResult, *, interactive: bool = False) -> dict:
    from lingtai.adapters.project_recipe_exchange import encode_bytes
    members = []
    for member in result.members:
        value = asdict(member)
        identity = value.pop("directory_identity")
        if interactive:
            value["directory_name_b64"] = encode_bytes(identity)
        members.append(value)
    snapshot = asdict(result.snapshot)
    snapshot.pop("failure")
    payload = {"status": "error" if result.code else "recipe_applied", "outcome": result.outcome,
               "members": members, "snapshot": snapshot, "greet_status": result.greet_status,
               "applied": sum(not member.code for member in result.members),
               "legacy_applied": sum(member.legacy_counted for member in result.members),
               "failed": sum(bool(member.code) for member in result.members), "code": result.code,
               "error": "Project Recipe operation could not complete" if result.code else ""}
    if interactive:
        payload["legacy_failure"] = asdict(result.legacy_failure) if result.legacy_failure else None
    return payload


def stopped_payload(exc: RecipeExchangeStopped) -> dict:
    from lingtai.adapters.project_recipe_exchange import encode_bytes
    payload = apply_payload(exc.result, interactive=True)
    payload.update(status="recipe_exchange_stopped", code="recipe_exchange_failed",
                   error="Project Recipe rendering exchange stopped",
                   legacy_code=exc.result.code, pending_sequence=exc.pending.sequence,
                   pending_directory_name_b64=encode_bytes(exc.pending.directory_name))
    return payload


def read_recipe_request(stream) -> tuple[dict, bool]:
    from lingtai.adapters.project_recipe_exchange import decode_object
    # Only a complete new-form first line can bypass the legacy EOF reader.
    # Growing readline is intentional for the new ABI, not a Scanner cap.
    first = stream.readline()
    try:
        value = decode_object(first)
    except Exception:
        value = None
    if isinstance(value, dict) and "rendering_mode" in value:
        if not first.endswith("\n"):
            raise recipe_error("invalid_project_request")
        return value, True
    # Valid old requests retain exactly their total character cap and can be
    # pretty-printed/multiline or EOF-delimited. No extra read beyond old bound.
    limit = 1024 * 1024
    if len(first) > limit:
        raise recipe_error("invalid_project_request")
    return read_request(io.StringIO(first + stream.read(limit + 1 - len(first)))), False


def execute(operation: str, value: dict, *, rendering_port=None) -> dict:
    interactive = operation == "recipe-apply" and "rendering_mode" in value
    if operation == "recipe-observe":
        _keys(value, {"project_dir"})
    elif operation == "recipe-apply":
        fields = {"project_dir", "lingtai_dir", "language", "rendering_mode"} if interactive else {"project_dir", "language", "rendering"}
        if interactive and "owner_mode" in value:
            fields.add("owner_mode")
            if value["owner_mode"] != "native":
                raise recipe_error("invalid_project_request")
        _keys(value, fields)
    else:
        raise recipe_error("invalid_project_request")
    if not isinstance(value["project_dir"], str):
        raise recipe_error("invalid_project_request")
    request = None
    if operation == "recipe-apply":
        if not value["project_dir"] or not isinstance(value["language"], str):
            raise recipe_error("invalid_project_request")
        if interactive:
            if (not isinstance(value["lingtai_dir"], str) or not value["lingtai_dir"]
                    or value["rendering_mode"] not in ("callback", "identity")):
                raise recipe_error("invalid_project_request")
            rendering = None
            if value["rendering_mode"] == "callback" and rendering_port is None:
                from lingtai.adapters.project_recipe_exchange import JsonRecipeRenderingAdapter
                rendering_port = JsonRecipeRenderingAdapter(sys.stdin, sys.stdout)
            elif value["rendering_mode"] == "identity":
                rendering_port = None
        else:
            rendering = value["rendering"]
        if rendering is not None:
            if not isinstance(rendering, dict):
                raise recipe_error("invalid_project_request")
            _keys(rendering, {"time", "address", "location", "commands"})
            if not all(isinstance(item, str) for item in rendering.values()):
                raise recipe_error("invalid_project_request")
            rendering = RecipeRendering(**rendering)
        request = RecipeApplyRequest(value["language"], rendering)
    elif value["project_dir"] == "":
        # Explicit legacy empty-root observation, never resolve it as cwd.
        return observation_payload(RecipeObservation(RecipeState.ABSENT, False))
    from lingtai.agent import load_preset
    from lingtai.adapters.project_recipe import FilesystemProjectRecipeAdapter
    root = Path(value["project_dir"])  # retain caller path; adapter uses Go lexical cleaning
    port = FilesystemProjectRecipeAdapter(root, load_preset=load_preset,
                                         lingtai_dir=Path(value["lingtai_dir"]) if interactive else None)
    if interactive and value.get("owner_mode") == "native":
        from lingtai.adapters.project_recipe_native import NativeFilesystemProjectRecipeAdapter, NativeRecipeExchange
        port = NativeFilesystemProjectRecipeAdapter(root, load_preset=load_preset,
                lingtai_dir=Path(value["lingtai_dir"]), exchange=NativeRecipeExchange(sys.stdin, sys.stdout))
    usecase = ProjectRecipeUseCase(port, rendering_port if interactive else None)
    try:
        return (observation_payload(usecase.observe()) if request is None
                else apply_payload(usecase.apply(request), interactive=interactive))
    except RecipeExchangeStopped as exc:
        return stopped_payload(exc)
    except RecipeOperationError as exc:
        # Metadata/enumeration failures precede traversal: known no apply writes.
        return apply_payload(RecipeApplyResult("rejected", code=exc.error.code,
                                               legacy_failure=exc.failure), interactive=interactive)


def handle_recipe_command(operation: str) -> None:
    previous_disable = logging.root.manager.disable
    interactive = False
    try:
        logging.disable(logging.CRITICAL)
        if operation == "recipe-layer":
            handle_recipe_layer()
            return
        if operation == "recipe-apply":
            value, interactive = read_recipe_request(sys.stdin)
        else:
            value = read_request(sys.stdin)
        payload = execute(operation, value)
    except ProjectCreationError as exc:
        if operation == "recipe-observe":
            payload = observation_payload(RecipeObservation(RecipeState.READ_FAILURE, False), exc.error.code)
        else:
            payload = apply_payload(RecipeApplyResult("rejected", code=exc.error.code), interactive=interactive)
    except Exception:
        if operation == "recipe-observe":
            payload = observation_payload(RecipeObservation(RecipeState.READ_FAILURE, False), "recipe_request_failed")
        else:
            payload = apply_payload(RecipeApplyResult("unknown", code="recipe_request_failed"), interactive=interactive)
    finally:
        logging.disable(previous_disable)
    # A broken output pipe after writes is unknown transport, never rollback.
    stream = sys.stderr if payload["code"] else sys.stdout
    # ASCII escaping preserves surrogate-bearing display labels in JSON without
    # encoding failure/replacement. New-form base64 identity is authoritative.
    stream.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")
    stream.flush()
    if payload["code"]:
        raise SystemExit(1)


def handle_recipe_layer() -> None:
    from lingtai.adapters.project_recipe_exchange import decode_object, encode_bytes
    from lingtai.adapters.project_recipe_native import NativeRecipeExchange, NativeRecipeLayerAdapter
    from lingtai.kernel.project.recipe import select_recipe_layer
    # Native path construction stays with the bound caller; request fields only
    # declare the closed query. No filesystem operation runs in this handler.
    line = sys.stdin.readline()
    value = decode_object(line)
    _keys(value, {"language", "layer"})
    if (not line.endswith("\n") or not isinstance(value["language"], str)
            or value["layer"] not in ("comment", "covenant")):
        raise recipe_error("invalid_project_request")
    selected = select_recipe_layer(NativeRecipeLayerAdapter(NativeRecipeExchange(sys.stdin, sys.stdout)),
                                   value["layer"], value["language"])
    sys.stdout.write(json.dumps({"status": "recipe_layer_selected", "path_b64": encode_bytes(selected)}) + "\n")
    sys.stdout.flush()
