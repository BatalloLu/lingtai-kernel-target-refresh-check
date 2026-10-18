"""Thin real Core/codec/resource/CLI contracts; native Go I/O proof is separate."""
from __future__ import annotations

import io
import json
import sys

import pytest

from lingtai.adapters.project_bundle import PackagedRecipeBundleAdapter
from lingtai.adapters.project_bundle_exchange import (
    BundleExchangeStopped, JsonRecipeBundleAdapter, read_bundle_request,
)
from lingtai.adapters.project_recipe_exchange import encode_bytes as b64
from lingtai.kernel.project.bundle import RecipeBundleUseCase


def _drive(binding, phases):
    request, _ = read_bundle_request(io.StringIO(json.dumps(binding) + "\n"))
    acks = [{"status": "bundle_io_result", "sequence": n, "operation": operation, "result": result}
            for n, (operation, result) in enumerate(phases, 1)]
    outgoing = io.StringIO()

    class Input(io.StringIO):
        def readline(self, *args):
            # Each synchronous observation sees its own emitted request already.
            assert len(outgoing.getvalue().splitlines()) == self.getvalue()[:self.tell()].count("\n") + 1
            return super().readline(*args)

    incoming = Input("".join(json.dumps(ack) + "\n" for ack in acks))
    port = JsonRecipeBundleAdapter(binding, incoming, outgoing)
    result = RecipeBundleUseCase(port, PackagedRecipeBundleAdapter()).materialize(request)
    terminal = port.terminal(result)
    assert terminal["transcript"] == [{key: value for key, value in ack.items() if key != "status"} for ack in acks]
    assert incoming.tell() == len(incoming.getvalue())
    return terminal, [json.loads(line) for line in outgoing.getvalue().splitlines()]


def _disk():
    return {"kind": "disk", "source_b64": b64(b"src"), "destination_b64": b64(b"dst")}


def _metadata(name=b"Fixture", library=None):
    return {"name_b64": b64(name), "library_b64": None if library is None else b64(library)}


def test_metadata_validation_precedes_same_path_and_abs_failure_does_not_refuse():
    terminal, frames = _drive(_disk(), [("load_metadata", _metadata(name=b""))])
    assert terminal["code"] == "source_empty_name" and terminal["failure"] is None
    assert [frame["operation"] for frame in frames] == ["load_metadata"]
    terminal, _ = _drive(_disk(), [("load_metadata", _metadata()),
                                  ("absolute_locations", {"source_b64": b64(b"same"), "destination_b64": b64(b"same")})])
    assert terminal["outcome"] == "unchanged"
    terminal, frames = _drive(_disk(), [
        ("load_metadata", _metadata(library=b"../literal-library")),
        ("absolute_locations", {"source_b64": None, "destination_b64": b64(b"dst")}),
        ("remove_recipe", {"ok": True}), ("copy_recipe", {"ok": True}),
        ("observe_library", {"kind": "directory"}), ("copy_library", {"failed": True}),
    ])
    assert terminal["code"] == "copy_library_failed"
    assert terminal["failure"] == {"sequence": 6, "operation": "copy_library"}
    assert frames[-1]["arguments"]["library_b64"] == b64(b"../literal-library")
    assert all(frame["operation"] != "observe_network" for frame in frames)


def test_optional_stat_failures_are_tolerated_after_recipe_copy():
    terminal, _ = _drive(_disk(), [
        ("load_metadata", _metadata(library=b"lib")),
        ("absolute_locations", {"source_b64": None, "destination_b64": None}),
        ("remove_recipe", {"ok": True}), ("copy_recipe", {"ok": True}),
        ("observe_library", {"kind": "stat_failed"}), ("observe_network", {"kind": "not_directory"}),
    ])
    assert terminal["outcome"] == "complete" and terminal["code"] == ""


def test_wizard_local_authority_and_found_invalid_global_never_falls_back():
    binding = {"kind": "wizard", "recipe_name_b64": "", "destination_b64": b64(b"dst"), "global_dir_b64": ""}
    terminal, _ = _drive(binding, [("observe_local_recipe", {"kind": "directory"}),
                                   ("load_metadata", _metadata())])
    assert terminal["source"] == "local" and terminal["outcome"] == "unchanged"
    binding["recipe_name_b64"] = b64(b"adaptive")
    terminal, frames = _drive(binding, [("observe_local_recipe", {"kind": "directory"}),
                                      ("load_metadata", _metadata(name=b"")),
                                      ("find_global", {"found": True}),
                                      ("load_metadata", {"failed": True})])
    assert terminal["source"] == "global" and terminal["code"] == "source_invalid"
    assert frames[-1]["arguments"] == {"source": "global"}


def test_cold_plain_delivery_and_all_installed_resource_projections():
    resources = PackagedRecipeBundleAdapter()
    root = b"recipe_assets/intrinsic/plain"
    binding = {"kind": "packaged", "recipe_name_b64": b64(b"plain"), "destination_b64": b64(b"dst")}
    terminal, frames = _drive(binding, [
        ("packaged_candidates", {"roots_b64": [b64(b"recipe_assets/recommended/plain"), b64(root), b64(b"recipe_assets/examples/plain")]}),
        ("decode_packaged_metadata", _metadata()), ("remove_recipe", {"ok": True}),
        ("prepare_packaged_file", {"ok": True}), ("write_packaged_file", {"ok": True}),
    ])
    assert terminal["outcome"] == "complete" and terminal["source"] == "packaged"
    assert frames[1]["arguments"]["content_b64"] == b64(resources.metadata(root))
    assert frames[-1]["arguments"] == {"relative_b64": b64(b".recipe/recipe.json"),
                                       "content_b64": b64(resources.metadata(root))}
    assert resources.has_directory(b".") and resources.metadata(b"recipe_assets") is None
    for category, name, count in [("recommended", "adaptive", 7), ("intrinsic", "greeter", 7),
                                  ("intrinsic", "plain", 1), ("examples", "tutorial", 7)]:
        root = f"recipe_assets/{category}/{name}".encode()
        assert json.loads(resources.metadata(root))["id"] == name
        members = resources.members(root)
        assert len(members) == count
        for member in members:
            content = resources.read(root, member)
            assert content and not content.startswith(b"---")


def test_bad_ack_stops_without_another_operation_or_terminal():
    binding = _disk()
    request, _ = read_bundle_request(io.StringIO(json.dumps(binding) + "\n"))
    output = io.StringIO()
    port = JsonRecipeBundleAdapter(binding, io.StringIO(
        '{"status":"bundle_io_result","sequence":true,"operation":"load_metadata","result":{"failed":true}}\n'), output)
    with pytest.raises(BundleExchangeStopped):
        RecipeBundleUseCase(port, PackagedRecipeBundleAdapter()).materialize(request)
    assert len(output.getvalue().splitlines()) == 1
    with pytest.raises(BundleExchangeStopped):
        port.remove_recipe()


def test_actual_root_cli_registration_and_empty_request_policy(monkeypatch):
    from lingtai import cli

    binding = _disk()
    binding["source_b64"] = ""
    output, errors = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(binding) + "\n"))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    monkeypatch.setattr(sys, "argv", ["lingtai-agent", "project", "recipe-materialize"])
    cli.main()
    assert errors.getvalue() == ""
    terminal = json.loads(output.getvalue())
    assert terminal == {"status": "bundle_materialized", "binding": binding, "source": "explicit",
                        "outcome": "rejected", "code": "empty_paths", "failure": None, "transcript": []}
