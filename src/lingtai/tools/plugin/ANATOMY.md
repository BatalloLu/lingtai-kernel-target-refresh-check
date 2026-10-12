---
related_files:
  - src/lingtai/tools/mcp/skills/mcp-manual/SKILL.md
  - tests/test_mcp_identity_discovery.py
  - tests/test_plugin_mcp_mode.py
  - src/lingtai/tools/plugin/_mcp.py
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/plugin/BEHAVIORS.md
  - src/lingtai/tools/plugin/__init__.py
  - src/lingtai/tools/plugin/settings.py
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/tools/plugin/manual/SKILL.md
  - src/lingtai/tools/plugin/manual/reference/format-and-containment.md
  - src/lingtai/tools/plugin/manual/reference/registration-and-lifecycle.md
  - src/lingtai/tools/plugin/manual/reference/diagnostics-and-settings.md
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/tools/plugin/glossary-en.md
  - src/lingtai/tools/plugin/glossary-zh.md
  - src/lingtai/tools/plugin/glossary-wen.md
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/services/mcp_registry.py
  - src/lingtai/services/ANATOMY.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/registry.py
  - src/lingtai/agent.py
  - src/lingtai/init_schema.py
  - docs/examples/agent-plugins/hello-lingtai/plugin.json
  - docs/examples/agent-plugins/hello-lingtai/mcp.json
  - docs/examples/agent-plugins/hello-lingtai/server.py
  - docs/examples/agent-plugins/hello-lingtai/skills/hello-lingtai/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. The mcp sibling is the pattern this package mirrors — when mcp's
  family composition, manual adaptation, or unknown-action envelope changes,
  re-check this one; when its addon decompression changes, re-check the
  registration half here, which mirrors it. See lingtai-dev-guide for details.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---

# Plugin catalog and MCP query mode

The single `plugin` family presents Agent Plugins by default and MCP registry
facts with explicit root `mode="mcp"`. The paired [Contract](CONTRACT.md) owns
promises; [PL001/PL002](BEHAVIORS.md) guard the two-tier catalog and mode boundary.

## Components

- `src/lingtai/tools/plugin/__init__.py:109` — `_reconcile` projects boot
  registration plus fresh discovery into the protected Plugin field. It does
  not register. `_bind` (`:236`) composes both mode owners and preserves their
  unknown-action/manual envelopes; `get_schema` (`:224`) adds only optional
  root mode, leaving strict-empty children unchanged. `DECLARATION` (`:283`)
  is the only public mount (PL001, PL002).
- `src/lingtai/tools/plugin/_mcp.py:26` — private MCP reconciliation reads
  registry/identities freshly, writes only the fixed protected MCP field, and
  returns the existing health envelope. `build_family` (`:85`) composes the
  existing strict-empty children/settings/manual owner without a declaration,
  setup, alias or transport (PL002, MC001).
- `src/lingtai/tools/plugin/settings.py:9` — existing redacted configured
  Plugin roots provider; `src/lingtai/tools/mcp/settings.py:12` — fresh canonical
  effective MCP init projection with unchanged generic strict failure/redaction.
- `plugin/manual/` owns Plugin guidance and explicitly routes MCP mode. The
  documentation-only `mcp/plugin.json` still owns `skills/mcp-manual/`, installed
  by the existing Agent manual sweep to `capabilities/mcp`; no docs are lost.
- `src/lingtai/services/plugin_registry.py:779` — boot-only registration and
  convergent source-stamped pruning remain outside this family. Discovery,
  containment and pinned Agent Plugins v1.0.0 validation are unchanged.
- `tests/test_plugin_mcp_mode.py` and `tests/test_mcp_identity_discovery.py`
  — authored mode/default, dispatch, fixed-writer, freshness, settings/manual,
  retired-root and hermetic full-prompt regressions.

## Connections

Plugin depends inward on the declared host primitive, ToolFamily and manual
loader. Registry services are imported lazily; no whole Agent is given to the
binder. The adapter grants the existing PromptSectionPort twice with fixed
protected destinations `plugin` and `mcp`. Protocol/client/service/catalog,
activation and LICC retain their existing separate owners.

## Composition

`registry.CORE_DEFAULTS` enables Plugin, not MCP. `plugin.setup` registers one
static declaration. Bind does no I/O; activation reconciles both prompt fields,
then the registrar mounts only Plugin. Root mode is removed at the owner
boundary before dispatch to strict-empty children; no generic management API
or ToolFamily schema widening exists. Plain Plugin calls are unchanged.

## State

The family owns no durable state or result cache. Host registration snapshots
remain host-owned; discovered packages cannot register, and registered MCP
servers are not active proof. Validated Plugin skills stay in the protected
Plugin namespace, never the vanilla skills catalog. MCP info retains the full
registry facts while the standalone MCP prompt excludes plugin-sourced records.

## Notes

The independent MCP tool/capability and its setup/schema/declaration SDK entry
points are deliberately retired, without aliases. Top-level `addons` and `mcp`
activation are not converted into Plugin manifests. No action registers,
launches, repairs, edits or removes anything. Tests are executed by the parent
validation owner, not inferred from source navigation.
