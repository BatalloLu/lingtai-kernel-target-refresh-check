---
name: mcp-contract
tool: plugin
contract_version: 2
related_files:
  - src/lingtai/tools/plugin/__init__.py
  - src/lingtai/tools/plugin/_mcp.py
  - src/lingtai/tools/plugin/CONTRACT.md
  - tests/test_plugin_mcp_mode.py
  - tests/test_mcp_identity_discovery.py
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/mcp/settings.py
  - src/lingtai/tools/mcp/plugin.json
  - src/lingtai/agent.py
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/mcp/BEHAVIORS.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/tools/mcp/skills/mcp-manual/SKILL.md
  - src/lingtai/tools/mcp/skills/mcp-manual/reference/runtime-and-identity.md
  - src/lingtai/services/mcp_registry.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
maintenance: |
  MCP presentation is owned by Plugin's explicit mcp mode, not a second tool.
  Keep this contract, paired Anatomy/LABT, Plugin's declaration, narrow fixed
  prompt grants, manual packaging, settings provider and tests synchronized.
  Preserve protocol/client/service/catalog/activation/LICC behavior; packaging
  is documentation only, never external-plugin registration or server launch.
---

# MCP presentation resources contract

MCP is an explicit **read-only mode of Plugin**, not a management API, protocol
change, or conversion of servers into Agent Plugin manifests. The independent
`mcp` model tool and capability and `lingtai.tools.mcp`'s `DECLARATION`, `setup`,
`get_schema`, and `get_description` SDK entry points are deliberately retired
without an alias. Enable the `plugin` capability (default-on) and call
`plugin(mode="mcp", action=..., input={}, reasoning=...)`. Plain Plugin calls
retain their Agent Plugins behavior.

## Tool surface
Guarded by: [MC001](BEHAVIORS.md#behavior-mc001),
[PL002](../plugin/BEHAVIORS.md#behavior-pl002).

Plugin has one declaration and one mounted model tool. The optional root
`mode` selector is `plugin` (default) or `mcp`; it is not action input. All
three actions retain strictly empty `input={}`. `reasoning` is Host audit
metadata, and root boolean `summarize` is the existing presentation control.
Unknown root fields, non-object/non-empty input, and non-boolean summarize
fail before owner I/O. Invalid mode returns the three-field
`status="failed", error_code="INVALID_ARGUMENT"` envelope with message
`mode must be 'plugin' or 'mcp'`; it grants no fallback or mutation authority.

| Action in mcp mode | Result and exact ownership |
|---|---|
| `info` | Fresh registry/identity read, separate protected `mcp` prompt render, `{status:"ok", registry_path, registered_count, registered:[{name, summary, identity?}], problems}`. No manual, cache of tool results, registry write or launch. |
| `settings` | Fresh canonical effective init composition used by boot/refresh; exactly `init.addons`, then `init.mcp`. |
| `manual` | Installed `.library/intrinsic/capabilities/mcp/SKILL.md`, flat `{status, mcp_manual, manual_path}` and optional truthful `error`. Missing manual is degraded with empty body; no fallback, registry/identity read or scan. |

Identity is attached only for a matching registered server with nonempty
accounts. The service retains its secret-field allowlist and narrower prompt
projection (including omission of volatile `last_verified_at`). Raw registry
problems may contain invalid lines/private values; do not publish them.

**Preserved envelopes.** Unknown/missing/unhashable action returns
`{status:"error", message:"unknown action: <repr>, only 'info', 'settings', or 'manual' is supported"}`
before input validation or I/O. Valid mode delegates to the existing generic
ToolFamily validation. MCP-mode invalid envelopes retain the historical
`unsupported mcp argument` / `unsupported mcp input field` labels, and the
existing `input must be an object` / `summarize must be a boolean` labels;
all use the unwrapped three-field `INVALID_ARGUMENT` failure. This private
family identity is not a mounted tool or public alias.

## Settings
Guarded by: [MC001](BEHAVIORS.md#behavior-mc001),
[PL002](../plugin/BEHAVIORS.md#behavior-pl002).

Each row has exactly `key`, `current`, `default`, `configurable`, `comment`,
in that order. `init.addons` uses current effective list, default `[]`;
`init.mcp` has both current and default fully `<redacted>`. Both are
configurable and link `mcp-manual#configuration-settings`. This read-only
inventory excludes registry/identity files, legacy `mcp/servers.json`, private
addon config/session data, Task Cards and live process state. The same
canonical reader is called afresh; no raw-file fallback or partial values.
Provider/read/shape/serialization failure is fixed `SETTINGS_UNAVAILABLE` with
no private detail or rows. A complete response over 65,536 UTF-8 bytes is fixed
`SETTINGS_RESPONSE_TOO_LARGE` with no partial rows. There is no setter/reset.

## Declared host composition
Guarded by: [PL002](../plugin/BEHAVIORS.md#behavior-pl002).

`plugin.DECLARATION` receives `workdir`, `plugin_catalog`, `prompt_section`
(fixed protected Plugin field), and `mcp_prompt_section` (a second grant of the
existing `PromptSectionPort`, fixed protected MCP field). The Plugin binder
composes both owner children without I/O; activation reconciles both fields
before mounting only `plugin`. Neither writer accepts a section name or an
unprotected flag. No whole Agent, transport, lifecycle, mount or registry-write
port is granted. Kernel official names and tools defaults omit `mcp`.

## State and registration boundary
Guarded by: [MC001](BEHAVIORS.md#behavior-mc001).

Presentation owns no durable state. Registry validation, JSONL I/O, catalog
load/decompression, identity projection and XML rendering remain in
`services.mcp_registry`. Agent addon decompression and explicit MCP activation,
protocol/client behavior, curated server descriptors/catalog, LICC and runtime
identity producers are unchanged. Catalog is not registered; registered is not
active. Plugin-discovered packages are not registered. Plugin-sourced server
records remain named in the protected Plugin catalog and excluded from the
standalone `<registered_mcp>` field, without losing the existing info snapshot.
Authorized changes still use explicit file operations and one controlled
System refresh/relaunch, followed by live verification; tool calls imply no
permission to configure or repair anything.

## Manual packaging
Guarded by: [PL002](../plugin/BEHAVIORS.md#behavior-pl002).

The retained `mcp/plugin.json` source owns exactly one `skills/mcp-manual/`
Agent Skill. The existing `plugin_registry.read_plugin` reader and
`Agent._install_intrinsic_manuals` copy it to `capabilities/mcp`, including its
references and README helper. This source is documentation only, not a declared
external plugin. `mcp.json` is forbidden for this built-in documentation
package, so packaging cannot register or activate a server. Plugin's default
manual and schema point meaningfully to mcp-mode manual/info/settings; no
independent tool is needed to discover or read the MCP library.

## Verification and maintenance

`tests/test_plugin_mcp_mode.py` guards single-root/default preservation, schema,
strict validation before I/O, distinct fixed prompt writers, fresh read-only
registry/settings, redaction/65KB atomic failure, degraded/installed manual,
SDK retirement and hermetic real Agent/full-prompt/manual installation.
`tests/test_mcp_identity_discovery.py` uses the actual Plugin mcp mode and
retains the service/producer identity assertions. Runtime/protocol owners are
not changed by this interface consolidation. See the
[Plugin contract](../plugin/CONTRACT.md) and [manual](skills/mcp-manual/SKILL.md).
