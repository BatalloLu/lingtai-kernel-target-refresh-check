"""Composition for the bound external-Project action exchange only.

Registration owner: add ``project lifecycle`` and dispatch to
``run_project_lifecycle()``. There is deliberately no standalone filesystem or
process fallback: the caller must supply the live, construction-bound port.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import TextIO

from lingtai.adapters.project_lifecycle_exchange import (
    JsonProjectLifecycleAdapter, decode_lifecycle_object,
)
from lingtai.kernel.project.external_lifecycle import ExternalLifecycleUseCase


def run_project_lifecycle(incoming: TextIO | None = None, outgoing: TextIO | None = None) -> int:
    incoming = incoming if incoming is not None else sys.stdin
    outgoing = outgoing if outgoing is not None else sys.stdout
    # Any abnormal/unknown exchange has no accepted terminal and no restored
    # native error. Static stderr only; never expose native exception text.
    try:
        line = incoming.readline()
        if not line.endswith("\n"):
            raise ValueError("incomplete request")
        request = decode_lifecycle_object(line)
        if request.get("action") == "resolve_preset":
            if (set(request) != {"request_id", "action", "query_nonempty"}
                    or not isinstance(request["request_id"], str) or not request["request_id"]
                    or type(request["query_nonempty"]) is not bool):
                raise ValueError("preset request")
            from lingtai.adapters.project_lifecycle_exchange import JsonExternalPresetResolutionAdapter
            from lingtai.kernel.project.external_lifecycle import resolve_external_preset
            native = JsonExternalPresetResolutionAdapter(request["request_id"], incoming, outgoing)
            resolution = resolve_external_preset(query_nonempty=request["query_nonempty"], native=native)
            terminal = dict(status="project_preset_resolved", request_id=request["request_id"],
                            **asdict(resolution), candidates=native.observed)
            outgoing.write(json.dumps(terminal, sort_keys=True) + "\n")
            outgoing.flush()
            return 0
        if set(request) != {"request_id", "action", "all_targets", "selected", "explicit_preset", "force"}:
            raise ValueError("request fields")
        if (not isinstance(request["request_id"], str) or not request["request_id"]
                or request["action"] not in {"sleep", "suspend", "refresh", "revive", "cpr", "clear", "clean", "nirvana"}
                or any(type(request[key]) is not bool for key in ("all_targets", "selected", "explicit_preset", "force"))):
            raise ValueError("request values")
        action = request["action"]
        if ((request["all_targets"] and action not in {"sleep", "suspend", "refresh", "cpr"})
                or (request["explicit_preset"] and (action != "refresh" or request["all_targets"]))
                or (request["force"] and action != "clean")):
            raise ValueError("request variants")
        native = JsonProjectLifecycleAdapter(request["request_id"], incoming, outgoing)
        core = ExternalLifecycleUseCase(native)
        if action in {"sleep", "suspend"}:
            result = core.signal(action, all_targets=request["all_targets"], selected=request["selected"])
        elif action == "refresh":
            result = core.refresh_all() if request["all_targets"] else core.refresh(explicit=request["explicit_preset"])
        elif action == "revive":
            result = core.revive()
        elif action == "cpr":
            result = core.cpr(all_targets=request["all_targets"], selected=request["selected"])
        elif action == "clear":
            result = core.clear()
        elif action == "clean":
            result = core.clean(force=request["force"])
        else:
            result = core.nirvana()
        terminal = {"status": "project_lifecycle_complete", "request_id": request["request_id"],
                    "action": action, "result": asdict(result), "transcript": native.transcript}
        outgoing.write(json.dumps(terminal, sort_keys=True) + "\n")
        outgoing.flush()
        return 0  # known native failure/refusal is still a completed exchange
    except Exception:
        sys.stderr.write("Project lifecycle exchange stopped; native effects may remain\n")
        return 1
