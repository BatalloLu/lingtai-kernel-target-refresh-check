---
name: plugin-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - tests/test_mcp_identity_discovery.py
  - tests/test_plugin_mcp_mode.py
  - src/lingtai/tools/plugin/_mcp.py
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/tools/plugin/ANATOMY.md
  - src/lingtai/tools/plugin/__init__.py
  - src/lingtai/tools/plugin/settings.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  plugin tool behavior clause changes, update the guarding LABT here in the same
  change.
---
> Test-reference maintenance (2026-10-12): `retired-test:` identifiers below name removed pytest coverage, not runnable selectors or replacement conformance. Product promises are unchanged; manual acceptance remains necessary where automated coverage was surrendered.

# Plugin Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/plugin/CONTRACT.md` (read-only info/settings/manual, skipped
entries explain non-mounting). Pinned pytest commands must run
from the repo root with the project's Python.

## Behavior PL001 — info reports health and every non-mounting component explains itself in skipped

- **id**: PL001
- **title**: info reports health and every non-mounting component explains itself in skipped
- **guards**: `plugin-contract` § Tool surface
- **runner**: any LingTai agent with `shell` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with one declared plugin
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed** and capture the outcome.
2. Call `plugin(action="info", input={}, reasoning="probe")` and record the result; confirm `registered`, `discovered`, `paths`, and `problems` are present and that no file was created or modified.
3. Declare a plugin with an escaping path or a server name outside the registry grammar and re-run `info`; confirm the plugin lands in `skipped` with a `{component, reason}` entry.
4. Call `plugin(action="settings", input={}, reasoning="probe policy")`; confirm the one `manifest.plugins` row has exactly `key`, `current`, `default`, `configurable`, and `comment`, both values are redacted, and the comment targets `plugin-manual#plugin-registration-roots`. Confirm non-empty input fails and a second `info` still returns the unchanged snapshot.

### Expected evidence
- [ ] Step 1: the plugin-tool suite passes, pinning the two-tier mount contract, lifecycle, and read-only info/settings/manual surface.
- [ ] Step 2: `info` returns the health snapshot and performs zero writes (the capability owns no state).
- [ ] Step 3: every non-mounting component appears in `skipped` with its reason; no plugin silently vanishes from the report.
- [ ] Step 4: settings reveals no local roots, advertises the authorized manual procedure, accepts only `{}`, and leaves the ordinary `info` behavior unchanged.

### Pass / Fail
Pass when the suite passes and the read-only/self-explaining observations hold.
Fail on a mutating action, settings path disclosure or extra row field, a silent
non-mount (no `skipped` entry), or a missing `paths`/`problems` report; record
the evidence trail in the task report.

## Behavior PL002 — Plugin defaults are preserved and MCP is an explicit read-only mode

- **id**: PL002
- **title**: Plugin defaults are preserved and MCP is an explicit read-only mode
- **guards**: `plugin-contract` § [MCP mode and compatibility](CONTRACT.md#mcp-mode-and-compatibility); `mcp-contract` § [Tool surface](../mcp/CONTRACT.md#tool-surface)
- **runner**: LingTai agent with Plugin and Shell, in an authorized disposable agent workdir
- **prerequisites**: the candidate package is already installed by the validation owner; the disposable Agent has default `plugin` enabled, no top-level MCP activation, no addons, no declared plugins; both manuals are installed. The executor may write only fixture registry/identity files inside this disposable workdir. Do not refresh, launch, install, configure accounts or use a live project.

### Steps

1. With Shell write exactly one line to workdir `mcp_registry.jsonl`:
   `{"name":"labt-local","summary":"LABT registered only","transport":"stdio","command":"never-run","args":[],"source":"labt-local"}`.
   Record the bytes/hash; do not add an activation entry.
2. Call `plugin(action="info", input={}, reasoning="default catalog proof", summarize=false)` and then the same call with root `mode="plugin"`. Compare results: both report declared/registered/discovered/path/problem Plugin facts, not MCP health.
3. Call `plugin(mode="mcp", action="info", input={}, reasoning="registered not active proof", summarize=false)`. Expect status ok, registry path, registered_count 1, registered `[ {name:"labt-local", summary:"LABT registered only"} ]`, problems `[]`, and no manual. Confirm registry bytes unchanged and no `labt-local` server/tool/process exists. Replace only the fixture summary with `LABT fresh` and repeat: the new summary must appear without refresh.
4. Call both modes' `manual` with `input={}` and `summarize=false`. Expect respectively flat `plugin_manual` and `mcp_manual` with nonempty installed bodies and their own truthful paths. The default manual must point to the explicit mcp mode; its MCP body routes exact README/runtime/identity/settings guidance. Hash the registry before/after; manual must not inspect or change it.
5. Call both modes' `settings`. Default mode has only the fully redacted `manifest.plugins` row. MCP mode has exactly `init.addons` (empty list, default empty list), then `init.mcp` (both values `<redacted>`). Every row has only key/current/default/configurable/comment; MCP comments equal `mcp-manual#configuration-settings`. No registry or live-health rows exist.
6. Call mcp info with `input={"mode":"mcp"}`, then with root `mode="invalid"`, then manual with `input={"extra":1}`. All must return `INVALID_ARGUMENT` before scan/read. Unknown action `"bogus"` returns status error; Plugin and MCP modes retain their distinct `only 'info' or 'settings' or 'manual'` versus `only 'info', 'settings', or 'manual'` messages. Call the retired standalone `mcp` tool: it must be unavailable, not an alias.
7. Inspect a complete system prompt: Plugin and MCP protected fields remain distinct, and no MCP info call overwrote Plugin facts. Confirm no registry/config writes, launches, registration or cleanup occurred except the explicitly authorized fixture writes in steps 1/3.

### Expected evidence

- [ ] Omitted/explicit Plugin mode results match; one public Plugin mount, no MCP mount/SDK alias.
- [ ] Fresh MCP health and unchanged registry bytes; registered does not prove active.
- [ ] Both installed manuals remain meaningfully discoverable; manual has no registry/identity scan.
- [ ] Strict-empty input, fixed error envelopes and two redacted inventories; no side effects.
- [ ] Distinct protected prompt fields and unchanged protocol/activation ownership.

### Pass / Fail

Pass only when every observation matches. Fail on fallback/alias, any unintended
write/launch/register/config repair, lost manual, stale read, credential disclosure,
mode admitted inside input, or merged/overwritten prompt field. Preserve evidence;
do not fix configuration or start a server to make this task pass.
