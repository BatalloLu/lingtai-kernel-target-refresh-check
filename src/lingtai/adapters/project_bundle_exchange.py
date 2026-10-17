"""Specialized synchronous Recipe bundle phase exchange; native errors stay in Go."""
from __future__ import annotations

import base64
from dataclasses import asdict
import json
from typing import TextIO

from lingtai.adapters.project_recipe_exchange import decode_object, encode_bytes
from lingtai.kernel.project.bundle import (
    BundleDirectory, BundleFailure, BundleIOError, BundleMetadata, BundleRequest, BundleResult,
    BundleSource, DiskBundleCopy, PackagedBundleCopy, WizardBundleStage,
)


class BundleExchangeStopped(Exception):
    """Unknown effects: no normal terminal, replay, fallback or compensation."""


def decode_bytes(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("base64 required")
    content = base64.b64decode(value, validate=True)
    if encode_bytes(content) != value:
        raise ValueError("canonical base64 required")
    return content


def read_bundle_request(stream: TextIO) -> tuple[BundleRequest, dict]:
    line = stream.readline()
    if not line.endswith("\n"):
        raise ValueError("complete request required")
    value = decode_object(line)
    kind = value.get("kind")
    fields = {"kind", "destination_b64"}
    if kind == "disk":
        fields |= {"source_b64"}
    elif kind == "packaged":
        fields |= {"recipe_name_b64"}
    elif kind == "wizard":
        fields |= {"recipe_name_b64", "global_dir_b64"}
    else:
        raise ValueError("bundle kind")
    if set(value) != fields:
        raise ValueError("bundle fields")
    decoded = {key: decode_bytes(item) for key, item in value.items() if key != "kind"}
    destination = decoded["destination_b64"]
    if kind == "disk":
        request = DiskBundleCopy(decoded["source_b64"], destination)
    elif kind == "packaged":
        request = PackagedBundleCopy(decoded["recipe_name_b64"], destination)
    else:
        request = WizardBundleStage(decoded["recipe_name_b64"], destination, decoded["global_dir_b64"])
    return request, value


class JsonRecipeBundleAdapter:
    """No local path/stat/copy/JSON-metadata emulation. One pending phase only."""
    def __init__(self, binding: dict, incoming: TextIO, outgoing: TextIO) -> None:
        self.binding = binding
        self.incoming = incoming
        self.outgoing = outgoing
        self._transcript: list[dict] = []
        self._issued: set[tuple[str, str]] = set()
        self._pending = False
        self._stopped = False

    def _ask(self, operation: str, arguments: dict, keys: set[str], *, can_fail: bool = False) -> dict:
        # A member write cannot be reissued with different bytes either.
        identity_arguments = {key: value for key, value in arguments.items() if key != "content_b64"}
        identity = (operation, json.dumps(identity_arguments, sort_keys=True))
        if self._stopped or self._pending or identity in self._issued:
            self._stopped = True
            raise BundleExchangeStopped() from None
        self._issued.add(identity)
        self._pending = True
        sequence = len(self._transcript) + 1
        try:
            frame = {"status": "bundle_io", "binding": self.binding, "sequence": sequence,
                     "operation": operation, "arguments": arguments}
            self.outgoing.write(json.dumps(frame, sort_keys=True, ensure_ascii=True) + "\n")
            self.outgoing.flush()
            line = self.incoming.readline()
            if not line.endswith("\n"):
                raise ValueError("complete acknowledgement required")
            ack = decode_object(line)
            if (set(ack) != {"status", "sequence", "operation", "result"}
                    or ack["status"] != "bundle_io_result" or type(ack["sequence"]) is not int
                    or ack["sequence"] != sequence or ack["operation"] != operation):
                raise ValueError("acknowledgement binding")
            result = ack["result"]
            if not isinstance(result, dict):
                raise ValueError("phase result")
            failed = set(result) == {"failed"} and result["failed"] is True
            if not (can_fail and failed) and set(result) != keys:
                raise ValueError("phase result fields")
            self._transcript.append({"sequence": sequence, "operation": operation, "result": result})
            self._pending = False
        except Exception:
            self._stopped = True
            raise BundleExchangeStopped() from None
        if can_fail and failed:
            raise BundleIOError(BundleFailure(sequence, operation))
        return result

    def _bytes(self, value: object) -> bytes:
        try:
            return decode_bytes(value)
        except (ValueError, TypeError):
            self._stopped = True
            raise BundleExchangeStopped() from None

    def _done(self, operation: str, arguments: dict) -> None:
        value = self._ask(operation, arguments, {"ok"}, can_fail=True)
        if value["ok"] is not True:
            self._stopped = True
            raise BundleExchangeStopped() from None

    def _directory(self, operation: str, arguments: dict) -> BundleDirectory:
        value = self._ask(operation, arguments, {"kind"})
        try:
            return BundleDirectory(value["kind"])
        except (ValueError, TypeError):
            self._stopped = True
            raise BundleExchangeStopped() from None

    def observe_local_recipe(self) -> BundleDirectory:
        return self._directory("observe_local_recipe", {})

    def find_global(self) -> bool:
        value = self._ask("find_global", {}, {"found"})
        if type(value["found"]) is not bool:
            self._stopped = True
            raise BundleExchangeStopped() from None
        return value["found"]

    def _metadata(self, operation: str, arguments: dict) -> BundleMetadata:
        value = self._ask(operation, arguments, {"name_b64", "library_b64"}, can_fail=True)
        return BundleMetadata(self._bytes(value["name_b64"]),
                              None if value["library_b64"] is None else self._bytes(value["library_b64"]))

    def load_metadata(self, source: BundleSource) -> BundleMetadata:
        return self._metadata("load_metadata", {"source": source.value})

    def absolute_locations(self, source: BundleSource) -> tuple[bytes | None, bytes | None]:
        value = self._ask("absolute_locations", {"source": source.value}, {"source_b64", "destination_b64"})
        return tuple(None if value[key] is None else self._bytes(value[key])
                     for key in ("source_b64", "destination_b64"))

    def remove_recipe(self) -> None:
        self._done("remove_recipe", {})

    def copy_recipe(self, source: BundleSource) -> None:
        self._done("copy_recipe", {"source": source.value})

    def observe_library(self, source: BundleSource, library: bytes) -> BundleDirectory:
        return self._directory("observe_library", {"source": source.value, "library_b64": encode_bytes(library)})

    def copy_library(self, source: BundleSource, library: bytes) -> None:
        self._done("copy_library", {"source": source.value, "library_b64": encode_bytes(library)})

    def observe_network(self, source: BundleSource) -> BundleDirectory:
        return self._directory("observe_network", {"source": source.value})

    def copy_network(self, source: BundleSource) -> None:
        self._done("copy_network", {"source": source.value})

    def packaged_candidates(self) -> tuple[bytes, ...]:
        value = self._ask("packaged_candidates", {}, {"roots_b64"})
        roots = value["roots_b64"]
        if not isinstance(roots, list) or len(roots) != 3:
            self._stopped = True
            raise BundleExchangeStopped() from None
        return tuple(self._bytes(root) for root in roots)

    def decode_packaged_metadata(self, root: bytes, content: bytes | None) -> BundleMetadata:
        return self._metadata("decode_packaged_metadata", {"root_b64": encode_bytes(root),
                              "content_b64": None if content is None else encode_bytes(content)})

    def prepare_packaged_file(self, relative: bytes) -> None:
        self._done("prepare_packaged_file", {"relative_b64": encode_bytes(relative)})

    def write_packaged_file(self, relative: bytes, content: bytes) -> None:
        self._done("write_packaged_file", {"relative_b64": encode_bytes(relative),
                   "content_b64": encode_bytes(content)})

    def terminal(self, result: BundleResult) -> dict:
        if self._stopped or self._pending:
            raise BundleExchangeStopped() from None
        return {"status": "bundle_materialized", "binding": self.binding,
                "source": result.source.value, "outcome": result.outcome, "code": result.code,
                "failure": asdict(result.failure) if result.failure else None,
                "transcript": self._transcript}
