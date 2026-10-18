"""CLI composition for one fresh local Project seed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lingtai.adapters.project_workspace import FilesystemProjectWorkspaceAdapter
from lingtai.kernel.project import (
    ProjectCreateRequest,
    ProjectCreationError,
    ProjectCreationUseCase,
    ProjectError,
)


def add_project_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    project = subparsers.add_parser("project", help="Create a fresh local Project seed")
    commands = project.add_subparsers(dest="project_command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect Project members from a JSON stdin request")
    inspect.set_defaults(as_json=True)
    interactive = commands.add_parser(
        "create-interactive", help="Create an approved Project via a JSON-lines stdin exchange"
    )
    interactive.set_defaults(as_json=True)
    from lingtai.cli_project_configuration import OPERATIONS
    for operation in OPERATIONS:
        commands.add_parser(operation, help="Configure an existing Project from JSON stdin").set_defaults(as_json=True)
    from lingtai.cli_project_recipe import OPERATIONS as RECIPE_OPERATIONS
    for operation in RECIPE_OPERATIONS:
        commands.add_parser(operation, help="Observe/apply a local Recipe from JSON stdin").set_defaults(as_json=True)
    commands.add_parser("recipe-materialize", help="Materialize a Recipe via bound native I/O").set_defaults(as_json=True)
    commands.add_parser("inventory-query", help="Query observed running Project inventory").set_defaults(as_json=True)
    commands.add_parser("lifecycle", help="Run bound external Project lifecycle policy").set_defaults(as_json=True)
    create = commands.add_parser("create", help="Create one Project with one initial agent")
    create.add_argument("--dir", required=True, dest="project_dir", help="Existing project root directory")
    create.add_argument("--name", required=True, dest="agent_name", help="Initial agent name")
    create.add_argument("--preset", required=True, help="Preset JSON/JSONC reference")
    create.add_argument("--covenant-file", required=True, dest="covenant_file", help="UTF-8 caller covenant")
    create.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON result or error")


def _error(code: str, message: str) -> ProjectCreationError:
    return ProjectCreationError(ProjectError(code, message))


def _read_covenant(path: str) -> str:
    try:
        value = Path(path).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _error("covenant_file_unreadable", "covenant file must be readable UTF-8 text") from exc
    if not value:
        raise _error("covenant_file_empty", "covenant file must contain caller-supplied text")
    return value


def _request(args: argparse.Namespace) -> ProjectCreateRequest:
    from lingtai.agent import load_preset
    from lingtai.tools.psyche.settings import serialize_prompt_owner_document

    preset_ref = str(Path(args.preset).expanduser().resolve())
    try:
        preset = load_preset(preset_ref)
    except (KeyError, ValueError, OSError) as exc:
        raise _error("invalid_preset", "preset could not be loaded") from exc
    manifest = preset.get("manifest") if isinstance(preset, dict) else None
    if not isinstance(manifest, dict):
        raise _error("invalid_preset", "preset manifest is invalid")
    llm = manifest.get("llm")
    capabilities = manifest.get("capabilities", {})
    if not isinstance(llm, dict) or not isinstance(capabilities, dict):
        raise _error("invalid_preset", "preset LLM and capabilities must be objects")
    llm = dict(llm)
    # Preset-local context-fit metadata must not become a new init runtime input.
    llm.pop("context_limit", None)
    return ProjectCreateRequest(
        agent_name=args.agent_name,
        preset_ref=preset_ref,
        llm=llm,
        capabilities=dict(capabilities),
        psyche_settings_json=serialize_prompt_owner_document(
            covenant=_read_covenant(args.covenant_file)
        ),
    )


def _validate_agent(agent_dir: Path) -> None:
    from lingtai.agent import load_preset
    from lingtai.init_reader import InitReadStatus, read_init, reader_callbacks

    materialize, prepare = reader_callbacks(agent_dir, load_preset=load_preset)
    outcome = read_init(agent_dir, materialize=materialize, prepare=prepare, failure_behavior="STOP")
    if outcome.status is InitReadStatus.READ_FAILED:
        raise _error("init_preflight_failed", "generated init could not be read")
    try:
        from lingtai.tools.psyche.settings import read_resolved_prompt_inputs

        read_resolved_prompt_inputs(agent_dir)
    except Exception as exc:
        raise _error(
            "psyche_preflight_failed",
            "generated Psyche settings could not be read",
        ) from exc


def _emit_error(error: ProjectError, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"status": "error", "code": error.code, "error": error.message}, sort_keys=True), file=sys.stderr)
    else:
        print(f"error[{error.code}]: {error.message}", file=sys.stderr)


def _inspect_project() -> None:
    from lingtai.adapters.project_inspection import FilesystemProjectInspectionAdapter
    from lingtai.kernel.project.inspection import ProjectInspectionUseCase
    from lingtai.adapters.project_inspection_exchange import (
        JsonProjectInspectionAdapter, read_inspection_request,
    )

    try:
        request = read_inspection_request(sys.stdin)
        root = Path(request.project_dir).expanduser().resolve()
        directory = FilesystemProjectInspectionAdapter(root)
        exchange = (JsonProjectInspectionAdapter(directory, sys.stdin, sys.stdout)
                    if request.init_observation_mode == "callback" else None)
        result = ProjectInspectionUseCase(exchange if exchange is not None else directory).inspect()
        payload = exchange.to_payload(result) if exchange is not None else result.to_payload()
    except ProjectCreationError as exc:
        _emit_error(exc.error, as_json=True)
        raise SystemExit(1) from None
    except Exception:
        _emit_error(ProjectError("project_inspect_failed", "project members could not be observed"), as_json=True)
        raise SystemExit(1) from None
    # New-mode ASCII escaping preserves surrogate-bearing labels; base64 identity
    # is authoritative. Ordinary-mode serialization remains exactly as before.
    print(json.dumps(payload, ensure_ascii=exchange is not None, sort_keys=True), flush=True)


def _create_interactive() -> None:
    from lingtai.agent import load_preset
    from lingtai.tools.psyche.settings import serialize_prompt_owner_document
    from lingtai.adapters.project_creation_exchange import (
        JsonCreationPrerequisiteAdapter, decode_creation_request, read_exchange_line,
    )
    from lingtai.adapters.project_creation_recipe import FilesystemCreationRecipeAdapter
    from lingtai.adapters.project_interactive_workspace import FilesystemInteractiveWorkspaceAdapter
    from lingtai.kernel.project.interactive_creation import InteractiveCreationUseCase

    def selected_preset_loader(*args, **kwargs):
        # Ordinary preset reads log legacy normalization paths/values. This one
        # machine-protocol invocation must not leak them into stderr. Only this
        # logger and actual load are scoped; Agent/other commands stay unchanged.
        from lingtai.kernel.presets import log
        disabled = log.disabled
        try:
            log.disabled = True
            return load_preset(*args, **kwargs)
        finally:
            log.disabled = disabled

    try:
        request = decode_creation_request(read_exchange_line(sys.stdin))
        workspace = FilesystemInteractiveWorkspaceAdapter(
            Path(request.project_dir).resolve(), load_preset=selected_preset_loader,
            serialize_psyche=serialize_prompt_owner_document,
        )
        result = InteractiveCreationUseCase(
            workspace, FilesystemCreationRecipeAdapter(workspace),
            JsonCreationPrerequisiteAdapter(sys.stdin, sys.stdout),
        ).create(request)
    except ProjectCreationError as exc:
        payload = {"status": "error", "committed": False,
                   "code": exc.error.code, "error": exc.error.message}
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # No operation retries, raw exceptions, preset payloads or credentials.
        print(json.dumps({"status": "error", "committed": False,
                          "code": "interactive_create_failed",
                          "error": "interactive Project creation could not complete"}), file=sys.stderr)
        raise SystemExit(1) from None
    # This is outside the rollback region: broken stdout after commit is an
    # unknown transport outcome for the consumer, never a failed transaction.
    print(json.dumps(result.to_payload(), ensure_ascii=False, sort_keys=True), flush=True)


def handle_project_command(args: argparse.Namespace) -> None:
    if args.project_command == "lifecycle":
        from lingtai.cli_project_lifecycle import run_project_lifecycle
        raise SystemExit(run_project_lifecycle())
    if args.project_command == "inventory-query":
        from lingtai.cli_project_inventory import run_inventory
        raise SystemExit(run_inventory(args))
    if args.project_command == "recipe-materialize":
        from lingtai.cli_project_bundle import handle_bundle_command
        handle_bundle_command()
        return
    from lingtai.cli_project_configuration import OPERATIONS, handle_configuration_command
    if args.project_command in OPERATIONS:
        handle_configuration_command(args.project_command)
        return
    from lingtai.cli_project_recipe import OPERATIONS as RECIPE_OPERATIONS, handle_recipe_command
    if args.project_command in RECIPE_OPERATIONS:
        handle_recipe_command(args.project_command)
        return
    if args.project_command == "create-interactive":
        _create_interactive()
        return
    if args.project_command == "inspect":
        _inspect_project()
        return
    if args.project_command != "create":
        raise SystemExit(2)
    try:
        root = Path(args.project_dir).expanduser().resolve()
        result = ProjectCreationUseCase(
            FilesystemProjectWorkspaceAdapter(root, validate_agent=_validate_agent)
        ).create(_request(args))
    except ProjectCreationError as exc:
        _emit_error(exc.error, as_json=args.as_json)
        raise SystemExit(1) from None
    except Exception:
        _emit_error(ProjectError("project_create_failed", "project creation could not be completed"), as_json=args.as_json)
        raise SystemExit(1) from None

    payload = result.to_payload()
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Project created for agent {payload['agent_name']}.")


__all__ = ["add_project_parser", "handle_project_command"]
