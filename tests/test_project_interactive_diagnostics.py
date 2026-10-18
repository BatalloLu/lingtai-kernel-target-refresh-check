"""Authored-only actual CLI regression for selected-preset diagnostic containment."""
from __future__ import annotations

import copy
import io
import json
import logging
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mismatch", [False, True], ids=["legacy-root-success", "persisted-mismatch"])
def test_actual_interactive_cli_legacy_preset_stderr_is_protocol_only(tmp_path, monkeypatch, mismatch):
    from lingtai import cli
    from lingtai.kernel.presets import log

    selected = tmp_path / "selected DO-NOT-EMIT.json"
    reviewed = {"llm": {"provider": "openai", "model": "selected-model", "context_limit": 8192},
                "capabilities": {"shell": {"yolo": False}}}
    raw = copy.deepcopy(reviewed)
    raw["context_limit"] = raw["llm"].pop("context_limit")
    if mismatch:
        raw["llm"]["model"] = "changed-model"
    payload = {"project_dir": str(tmp_path), "approved_root": str(tmp_path),
               "agent_name": "Display", "directory_name": "orch-dir",
               "preset_ref": str(selected), "preset_manifest": reviewed,
               "options": {"language": "en", "covenant": "approved covenant"},
               "recipe": "", "process_evidence": "clean"}
    outgoing, errors = io.StringIO(), io.StringIO()

    class Exchange(io.StringIO):
        acknowledged = False
        def readline(self, size=-1):
            if self.tell() and not self.acknowledged:
                self.acknowledged = True
                ready = json.loads(outgoing.getvalue())
                assert ready["status"] == "ready_for_prerequisites"
                assert not selected.exists()  # no persistence before actual ready
                selected.write_text(json.dumps({"description": {"summary": "legacy fixture"},
                                                "manifest": raw}), encoding="utf-8")
                return json.dumps({"status": "prerequisites_acknowledged",
                                   "attempt_id": ready["attempt_id"], "preset_ref": str(selected),
                                   "accepted": True}) + "\n"
            return super().readline(size)

    monkeypatch.setattr(sys, "stdin", Exchange(json.dumps(payload) + "\n"))
    monkeypatch.setattr(sys, "stdout", outgoing)
    monkeypatch.setattr(sys, "stderr", errors)
    monkeypatch.setattr(sys, "argv", ["lingtai-agent", "project", "create-interactive"])
    monkeypatch.setattr(log, "disabled", False)
    # Route the actual normalizer logger to protocol stderr explicitly: without
    # containment this emits its path/legacy-context warning even in a test host.
    diagnostic_handler = logging.StreamHandler(errors)
    diagnostic_handler.setLevel(logging.WARNING)
    log.addHandler(diagnostic_handler)
    try:
        if mismatch:
            with pytest.raises(SystemExit) as terminal:
                cli.main()
            assert terminal.value.code == 1
            assert len(outgoing.getvalue().splitlines()) == 1
            assert json.loads(errors.getvalue()) == {
                "status": "error", "committed": False, "code": "preset_dependency_mismatch",
                "error": "interactive Project creation could not complete",
            }
            assert not (tmp_path / ".lingtai").exists()
        else:
            cli.main()
            objects = [json.loads(line) for line in outgoing.getvalue().splitlines()]
            assert [value["status"] for value in objects] == ["ready_for_prerequisites", "created"]
            assert objects[-1]["committed"] is True
            assert errors.getvalue() == ""
        assert log.disabled is False  # finally restores even persisted mismatch
        assert json.loads(selected.read_text())["manifest"] == raw  # no preset rewrite
        assert "DO-NOT-EMIT" not in errors.getvalue()
        assert "manifest.context_limit" not in errors.getvalue()
        log.warning("ordinary logger restored")
        assert "ordinary logger restored" in errors.getvalue()
    finally:
        log.removeHandler(diagnostic_handler)
