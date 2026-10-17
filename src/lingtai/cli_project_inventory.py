"""One read-only native-inventory query; no Agent, filesystem or process scan."""
from __future__ import annotations

import base64
from dataclasses import asdict
import json
import sys

from lingtai.kernel.project.inventory import (
    InventoryObservation, RunningMemberObservation, RunningProjectObservation, query_inventory,
)


def _object(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError("invalid inventory observation")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _bytes(value):
    if type(value) is not str:
        raise ValueError("invalid identity")
    decoded = base64.b64decode(value, validate=True)
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("noncanonical identity")
    return decoded


def _bool(value):
    if type(value) is not bool:
        raise ValueError("invalid boolean")
    return value


def _int(value):
    if type(value) is not int:
        raise ValueError("invalid integer")
    return value


def execute(value):
    _object(value, "members projects include_human")
    if type(value["members"]) is not list or type(value["projects"]) is not list:
        raise ValueError("invalid observations")
    members = []
    for row, member in enumerate(value["members"]):
        _object(member, "row directory project project_order name_order directory_order pid duplicate_runtime_pid admin_null admin_flags manifest_failed")
        if _int(member["row"]) != row or type(member["admin_flags"]) is not list:
            raise ValueError("invalid row")
        members.append(RunningMemberObservation(
            row, *(_bytes(member[key]) for key in ("directory", "project", "project_order", "name_order", "directory_order")),
            _int(member["pid"]), _int(member["duplicate_runtime_pid"]), _bool(member["admin_null"]),
            tuple(_bool(flag) for flag in member["admin_flags"]), _bool(member["manifest_failed"]),
        ))
    projects = []
    seen = set()
    for project in value["projects"]:
        _object(project, "identity container_missing")
        identity = _bytes(project["identity"])
        if identity in seen:
            raise ValueError("duplicate project")
        seen.add(identity)
        projects.append(RunningProjectObservation(identity, _bool(project["container_missing"])))
    result = query_inventory(InventoryObservation(tuple(members), tuple(projects), _bool(value["include_human"])))
    decisions = []
    for member in result.members:
        decision = asdict(member)
        decision["directory"] = base64.b64encode(member.directory).decode("ascii")
        decisions.append(decision)
    return {"status": "inventory_queried", "members": decisions,
            "groups": result.groups, "phantom_projects": result.phantom_projects}


def run_inventory(args=None) -> int:
    """Composition callable registered by cli_project.add_project_parser."""
    try:
        value = json.load(sys.stdin, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = execute(value)
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        sys.stderr.write('{"status":"error","code":"invalid_inventory_observation"}\n')
        return 1
