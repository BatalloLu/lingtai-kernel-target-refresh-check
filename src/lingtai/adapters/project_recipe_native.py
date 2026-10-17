"""Closed native owner observations for the existing Go Recipe consumer only.

No raw metadata/init document crosses this boundary. The native caller retains
one current init owner; Core receives text paths or opaque original entry IDs.
"""
from __future__ import annotations

import base64
import json

from lingtai.adapters.project_recipe import FilesystemProjectRecipeAdapter
from lingtai.adapters.project_recipe_exchange import decode_object, encode_bytes
from lingtai.kernel.project.recipe import (
    GreetLayer, RecipeFailure, RecipeInfo, RecipeLayerPort, RecipeLayerStat,
    RecipeOpaquePath, RecipeOperationError, RecipeSkills, RecipeWrite,
    select_recipe_layer,
)


def _keys(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("native Recipe fields")


def _bytes(value):
    if not isinstance(value, str):
        raise ValueError("native Recipe bytes")
    result = base64.b64decode(value, validate=True)
    if encode_bytes(result) != value:
        raise ValueError("native Recipe bytes")
    return result


class NativeRecipeExchange:
    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing
        self.sequence = 0

    def call(self, operation, arguments):
        self.sequence += 1
        frame = dict(status="recipe_native", sequence=self.sequence,
                     operation=operation, arguments=arguments)
        self.outgoing.write(json.dumps(frame, ensure_ascii=True) + "\n")
        self.outgoing.flush()
        line = self.incoming.readline()  # no inherited request/Scanner cap
        if not line.endswith("\n"):
            raise ValueError("native Recipe transport")
        ack = decode_object(line)
        _keys(ack, "status sequence operation evidence failure")
        if (ack["status"] != "recipe_native_observed" or type(ack["sequence"]) is not int
                or ack["sequence"] != self.sequence or ack["operation"] != operation):
            raise ValueError("native Recipe binding")
        failure = ack["failure"]
        if failure is not None:
            _keys(failure, "phase operation path_b64 errno winerror parse_offset")
            _bytes(failure["path_b64"])
            if (failure["phase"] not in ("metadata", "skills")
                    or failure["operation"] not in ("read", "decode", "normalize", "write")):
                raise ValueError("native Recipe failure")
            for key in ("errno", "winerror", "parse_offset"):
                if failure[key] is not None and (type(failure[key]) is not int or failure[key] < 0):
                    raise ValueError("native Recipe failure")
            if ack["evidence"] is not None:
                raise ValueError("native Recipe failure evidence")
            return None, RecipeFailure(**failure)
        if not isinstance(ack["evidence"], dict):
            raise ValueError("native Recipe evidence")
        return ack["evidence"], None


class NativeRecipeLayerAdapter(RecipeLayerPort):
    def __init__(self, exchange):
        self.exchange = exchange

    def stat_layer(self, layer, language):
        value, failure = self.exchange.call("layer_stat", dict(layer=layer, localized=bool(language)))
        if failure is not None:
            raise ValueError("native Recipe layer transport")
        _keys(value, "exists directory path_b64")
        if type(value["exists"]) is not bool or type(value["directory"]) is not bool:
            raise ValueError("native Recipe stat")
        identity = _bytes(value["path_b64"])
        if value["exists"] != bool(identity) or (value["directory"] and not value["exists"]):
            raise ValueError("native Recipe stat")
        return RecipeLayerStat(value["exists"], value["directory"], identity)


class NativeFilesystemProjectRecipeAdapter(FilesystemProjectRecipeAdapter):
    def __init__(self, *args, exchange, **kwargs):
        super().__init__(*args, **kwargs)
        self.exchange = exchange

    def load_info(self):
        value, failure = self.exchange.call("metadata", {})
        if failure:
            raise RecipeOperationError("invalid_recipe", failure)
        _keys(value, "name library_name library_path_entry source_path_b64")
        if (not isinstance(value["name"], str)
                or value["library_name"] is not None and not isinstance(value["library_name"], str)
                or not isinstance(value["library_path_entry"], str)):
            raise ValueError("native Recipe metadata")
        _bytes(value["source_path_b64"])
        return RecipeInfo(value["name"], value["library_name"], value["library_path_entry"],
                          RecipeFailure("metadata", "decode", value["source_path_b64"]))

    def observe_greet(self, language):
        selected = select_recipe_layer(NativeRecipeLayerAdapter(self.exchange), "greet", language)
        if not selected:
            return GreetLayer()
        value, failure = self.exchange.call("layer_read", {"path_b64": encode_bytes(selected)})
        if failure:
            raise ValueError("native Recipe layer transport")
        _keys(value, "read_failed content_b64")
        if type(value["read_failed"]) is not bool:
            raise ValueError("native Recipe layer read")
        return GreetLayer(True, _bytes(value["content_b64"]), value["read_failed"])

    def observe_skills(self, directory_name):
        value, failure = self.exchange.call("skills_observe", {
            "directory_name_b64": encode_bytes(self.directory_identity(directory_name))})
        if failure:
            return RecipeSkills(code="recipe_skills_read_failed", failure=failure)
        _keys(value, "present canonical_changed handle paths")
        if (type(value["present"]) is not bool or type(value["canonical_changed"]) is not bool
                or type(value["handle"]) is not int or value["handle"] < 0
                or not isinstance(value["paths"], list)):
            raise ValueError("native Recipe skills")
        paths = []
        for item in value["paths"]:
            if isinstance(item, str):
                paths.append(item)
            elif type(item) is int and item >= 0:
                paths.append(RecipeOpaquePath(item))
            else:
                raise ValueError("native Recipe path entry")
        if value["present"] != (value["handle"] > 0):
            raise ValueError("native Recipe document identity")
        return RecipeSkills(present=value["present"], paths=tuple(paths),
                            canonical_changed=value["canonical_changed"], document_handle=value["handle"])

    def write_skills(self, directory_name, evidence, paths):
        value, failure = self.exchange.call("skills_write", {
            "directory_name_b64": encode_bytes(self.directory_identity(directory_name)),
            "handle": evidence.document_handle,
            "paths": [item.entry if isinstance(item, RecipeOpaquePath) else item for item in paths]})
        if failure:
            return RecipeWrite(code="recipe_init_write_failed", failure=failure)
        _keys(value, "written")
        if value["written"] is not True:
            raise ValueError("native Recipe write")
        # This native owner was never materialized/read by Python. No fabricated
        # effective-reader success or new refusal for legacy Go documents.
        return RecipeWrite(True, "not_read_native")
