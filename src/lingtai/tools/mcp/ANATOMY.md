---
related_files:
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/tools/plugin/__init__.py
  - tests/test_mcp_identity_discovery.py
  - tests/test_plugin_mcp_mode.py
  - src/lingtai/tools/plugin/_mcp.py
  - src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/mcp/BEHAVIORS.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/mcp/settings.py
  - src/lingtai/tools/mcp/plugin.json
  - src/lingtai/agent.py
  - src/lingtai/services/mcp_inbox.py
  - src/lingtai/services/mcp_licc.py
  - src/lingtai/tools/mcp/skills/mcp-manual/SKILL.md
  - src/lingtai/tools/mcp/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/plugin/ANATOMY.md
  - src/lingtai/mcp_servers/ANATOMY.md
  - src/lingtai/tools/mcp/glossary-en.md
  - src/lingtai/tools/mcp/glossary-zh.md
  - src/lingtai/tools/mcp/glossary-wen.md
  - ENVIRONMENT_VARIABLES.md
  - src/lingtai/tools/mcp/skills/mcp-manual/reference/curated-addons.md
  - src/lingtai/tools/mcp/skills/mcp-manual/reference/third-party-and-legacy.md
  - src/lingtai/tools/mcp/skills/mcp-manual/reference/runtime-and-identity.md
  - src/lingtai/tools/mcp/skills/mcp-manual/reference/troubleshooting.md
  - src/lingtai/tools/mcp/skills/mcp-manual/scripts/find_readme.py
  - src/lingtai/tools/ANATOMY.md
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. See lingtai-dev-guide for details.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---

# MCP presentation resources, registry and LICC

MCP presentation is now Plugin's explicit mcp query mode, not an independent
tool. Its resource [Contract](CONTRACT.md) and [MC001](BEHAVIORS.md) retain the
read-only semantics; [Plugin Anatomy](../plugin/ANATOMY.md) owns dispatch/mount.

## Components

- `src/lingtai/tools/mcp/__init__.py:1` — documentation-resource namespace;
  no declaration, setup or public schema remains. The private presentation
  owner is `src/lingtai/tools/plugin/_mcp.py:26` (MC001, PL002).
- `src/lingtai/tools/mcp/settings.py:12` — `MCPSettingsProvider` retains fresh
  canonical effective init reads, exact two rows, fully sensitive activation
  map and generic whole-action failure behavior.
- `src/lingtai/tools/mcp/plugin.json` plus `skills/mcp-manual/` — retained
  documentation package, read by the existing Plugin registry reader and
  installed to `.library/intrinsic/capabilities/mcp/`, including references
  and README helper. No MCP server manifest or registration is generated.
- `src/lingtai/services/mcp_registry.py:436` — existing registry XML builder;
  registry validation/JSONL, curated catalog/decompression and secret-safe
  identity projection remain in this service. Only its manual signpost prose
  now points to Plugin mcp mode.
- `services/mcp_inbox.py`, `services/mcp_licc.py` and curated `mcp_servers/`
  retain LICC producer/consumer, runtime identity and protocol responsibilities.
  Notification projection remains governed by the linked LICC contract.

## Connections

The private Plugin owner lazily imports registry services and reuses the same
settings provider/manual loader. It receives workdir plus a fixed protected MCP
writer, not a whole Agent or transport. The protected `mcp` section is distinct
from Plugin's registered/discovered catalog; protocol, client and activation
are not unified into Plugin packaging.

## Composition

Agent boot still decompresses addons and registers declared external plugins
before capabilities, then separately loads explicitly activated MCP clients.
Plugin is the sole default model-query mount and reconciles both protected
fields. The old MCP capability has no alias; standalone SDK mounting APIs are
retired. MCP manual installation uses the same manifest/containment reader and
owned-skill installer, regardless of capability enablement.

## State

Registry lives beside init.json as `mcp_registry.jsonl`; account identity caches
live under `system/mcp_identities/`. Presentation owns no cache/files. Info reads
these resources freshly, manual reads only its installed body, and settings
reads effective init configuration. Registered does not mean active; discovery
does not mean registration. Plugin-sourced records keep their existing separate
prompt catalog and registration source stamps.

## Notes

[PL002](../plugin/BEHAVIORS.md#behavior-pl002) and
`tests/test_plugin_mcp_mode.py` guard mode routing, strict validation, separate
writers, installed manual and compatibility loss.
`tests/test_mcp_identity_discovery.py` exercises the actual mode and existing
secret-safe identity/prompt semantics. Protocol/client/service/catalog/activation
and LICC logic are not changed by this presentation consolidation.
