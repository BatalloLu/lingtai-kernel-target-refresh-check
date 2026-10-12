---
name: mcp-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/plugin/ANATOMY.md
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/tools/plugin/__init__.py
  - tests/test_mcp_identity_discovery.py
  - tests/test_plugin_mcp_mode.py
  - src/lingtai/tools/plugin/_mcp.py
  - src/lingtai/tools/mcp/CONTRACT.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/mcp/settings.py
  - src/lingtai/mcp_catalog.json
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an mcp
  tool behavior clause changes, update the guarding LABT here in the same
  change.
---

# MCP mode behavior tasks

## Behavior MC001 — MCP mode is a fresh read-only registry signpost

- **id**: MC001
- **title**: MCP mode is a fresh read-only registry signpost
- **guards**: `mcp-contract` § [Tool surface](CONTRACT.md#tool-surface), § [Settings](CONTRACT.md#settings), § [State and registration boundary](CONTRACT.md#state-and-registration-boundary)
- **runner**: LingTai agent with Plugin and Shell in an authorized disposable workdir
- **prerequisites**: candidate installed by validation owner; default Plugin enabled; no addons or MCP activation; both manuals installed. Only the scratch registry fixture below may be written. No live configuration/server launch/refresh.

### Steps

1. Write workdir `mcp_registry.jsonl` containing one exact JSONL record:
   `{"name":"probe","summary":"read only","transport":"stdio","command":"never-run","args":[],"source":"labt-local"}`. Record its bytes.
2. Call `plugin(mode="mcp", action="info", input={}, reasoning="health proof", summarize=false)`; expect status ok, registered_count 1, registered `[{name:"probe", summary:"read only"}]`, problems `[]`, registry_path ending in `mcp_registry.jsonl`, and no manual body. Recheck bytes and absent server/process/tools. A registry record is not active proof.
3. Call `plugin(mode="mcp", action="settings", input={}, reasoning="safe inventory", summarize=false)`. Expect only rows `init.addons` then `init.mcp`; addons current/default `[]`, mcp both `<redacted>`; exactly five row fields key/current/default/configurable/comment; comments `mcp-manual#configuration-settings`.
4. Call `plugin(mode="mcp", action="manual", input={}, reasoning="manual proof", summarize=false)`. Expect status ok, nonempty mcp_manual and truthful path ending `.library/intrinsic/capabilities/mcp/SKILL.md`; registry bytes remain unchanged. This action reads only the installed manual, no registry/identity/network I/O.
5. Repeat each action with input `{"extra":1}` and then root summarize `"yes"`. Expect unwrapped INVALID_ARGUMENT failure before owner I/O. Confirm default `plugin(action="info", input={}, reasoning="catalog remains separate")` still reports Plugin catalog fields, not MCP health.

### Expected evidence

- [ ] Exact fresh health shape and unchanged fixture bytes; no child is activated.
- [ ] Exact redacted five-field two-row inventory; no mutation or partial state.
- [ ] Installed MCP manual stays available through meaningful explicit Plugin mode.
- [ ] Invalid calls fail before owner I/O; Plugin/MCP fields remain distinct.

### Pass / Fail

Pass only on all expected evidence and no side effects beyond the fixture write.
Fail on any implicit launch/register/repair/config change, raw credential disclosure,
missing manual, stale health, input widening, or standalone MCP alias. Preserve the
trail rather than making runtime changes to satisfy the assertions.
