"""Synchronous existing-Recipe rendering JSON lines; no generic bridge/policy."""
from __future__ import annotations

import base64
import json
from typing import TextIO

from lingtai.kernel.project.recipe import (
    RecipeGreetRenderingPort, RecipeMemberGreet, RecipeRenderingStopped,
)


def _closed_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def decode_object(text: str) -> dict:
    value = json.loads(text, object_pairs_hook=_closed_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class JsonRecipeRenderingAdapter(RecipeGreetRenderingPort):
    """One immutable pending member and one exact bound ack, no replay."""
    def __init__(self, incoming: TextIO, outgoing: TextIO) -> None:
        self.incoming = incoming
        self.outgoing = outgoing
        self.sequence = 0
        self.pending: RecipeMemberGreet | None = None
        self.stopped = False

    def render(self, member: RecipeMemberGreet) -> bytes:
        if (self.stopped or self.pending is not None or type(member.sequence) is not int
                or member.sequence != self.sequence + 1):
            self.stopped = True
            raise RecipeRenderingStopped() from None
        self.pending = member
        self.sequence = member.sequence
        try:
            frame = {"status": "render_recipe_member", "sequence": member.sequence,
                     "directory_name_b64": encode_bytes(member.directory_name),
                     "template_b64": encode_bytes(member.template), "template_bytes": len(member.template)}
            self.outgoing.write(json.dumps(frame, sort_keys=True) + "\n")
            self.outgoing.flush()
            # Dynamically growing line: no inherited Scanner/creation/1MiB cap.
            line = self.incoming.readline()
            if not line.endswith("\n"):
                raise ValueError("incomplete acknowledgement")
            ack = decode_object(line)
            if set(ack) != {"status", "sequence", "rendered_b64", "rendered_bytes"}:
                raise ValueError("ack fields")
            if (ack["status"] != "recipe_member_rendered" or type(ack["sequence"]) is not int
                    or ack["sequence"] != self.pending.sequence
                    or type(ack["rendered_bytes"]) is not int or ack["rendered_bytes"] < 0
                    or not isinstance(ack["rendered_b64"], str)):
                raise ValueError("ack binding")
            rendered = base64.b64decode(ack["rendered_b64"], validate=True)
            if len(rendered) != ack["rendered_bytes"] or encode_bytes(rendered) != ack["rendered_b64"]:
                raise ValueError("ack bytes")
            self.pending = None
            return rendered
        except Exception:
            self.stopped = True
            # No template/result/exception text reaches logs or error receipts.
            raise RecipeRenderingStopped() from None
