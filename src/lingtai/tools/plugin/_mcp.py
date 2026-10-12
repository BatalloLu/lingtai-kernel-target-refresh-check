"""Private MCP presentation owner of Plugin's explicit ``mode="mcp"``.

No declaration, public tool, setup, transport, registry writer, or alias lives
here. The existing MCP settings provider and installed manual remain owned
resources; the only extra host grant writes the separate protected mcp section.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child
from ..mcp.settings import MCPSettingsProvider

if TYPE_CHECKING:
    from lingtai.kernel.tool_plugin import ToolPluginHost

def _registered_entry(record: dict, identity: dict | None) -> dict:
    """Build one ``registered`` entry, attaching identity only when present."""
    entry = {"name": record["name"], "summary": record["summary"]}
    if identity and identity.get("accounts"):
        entry["identity"] = identity
    return entry


def _reconcile(host: "ToolPluginHost") -> dict:
    """Read registry, render into prompt, return health snapshot.

    Reached through the two granted host ports, never through the Agent: the
    registry and the installed manual are resolved below ``host.workdir.path``
    (formerly the private ``agent._working_dir``), and the rendered XML goes to
    ``host.mcp_prompt_section``, which is bound to the separately protected
    ``mcp`` section and cannot address another's.
    """
    from lingtai.services.mcp_registry import (
        read_registry,
        read_identities,
        _build_registry_xml,
        _registry_path,
    )

    working_dir = host.workdir.path
    records, problems = read_registry(working_dir)
    identities = read_identities(working_dir)

    xml = _build_registry_xml(records, identities)
    host.mcp_prompt_section.write_protected_section(xml)

    result = {
        "status": "ok",
        "registry_path": str(_registry_path(working_dir)),
        "registered_count": len(records),
        "registered": [
            _registered_entry(r, identities.get(r["name"]))
            for r in records
        ],
        "problems": problems,
    }
    return result


def _flatten_manual_result(mcp_result: dict) -> dict:
    """Adapt the canonical ``manual`` child result to mcp's public flat shape.

    ``ToolFamily.handle()`` has already dispatched to the registered ``manual``
    child (``build_manual_child``) and returned its canonical result *verbatim*
    (no double wrap) — full body at ``content[0].text``, host-local path at
    ``structuredContent.manual_path``, plus the loader's truthful
    ``status``/``error`` facts. mcp's own public result shape predates that
    generic contract and must stay exactly ``status``/``mcp_manual``/
    ``manual_path`` (note the tool-specific body key), so this Host-owned
    adapter runs strictly *after* dispatch — never inside a registered child,
    and never on the ``info`` path.
    """
    flat = {
        "status": mcp_result.get("status", "ok"),
        "mcp_manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


def build_family(host: "ToolPluginHost | None") -> ToolFamily:
    """Compose private mode children; retain MCP's historical error labels."""
    if host is None:
        def unused(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("schema-only family never dispatches")
        info_handler: Any = unused
        manual_child = ChildTool("manual", MANUAL_INPUT_SCHEMA, unused, title="manual input")
    else:
        info_handler = lambda _input: _reconcile(host)
        manual_child = build_manual_child(host.workdir, "mcp")
    return ToolFamily(
        "mcp",
        [ChildTool("info", MANUAL_INPUT_SCHEMA, info_handler, title="info input"), manual_child],
        settings_provider=MCPSettingsProvider(host.workdir.path if host else None),
    )
