---
related_files:
  - src/lingtai/kernel/project/recipe.py
  - src/lingtai/adapters/project_recipe.py
  - src/lingtai/adapters/project_recipe_exchange.py
  - src/lingtai/adapters/project_inspection_exchange.py
  - tests/test_project_inspection_exchange.py
  - src/lingtai/cli_project_recipe.py
  - tests/test_project_recipe.py
  - src/lingtai/kernel/project/configuration.py
  - src/lingtai/adapters/project_configuration.py
  - src/lingtai/cli_project_configuration.py
  - src/lingtai/kernel/project/CONTRACT.md
  - src/lingtai/kernel/project/ANATOMY.md
  - src/lingtai/cli_project.py
  - src/lingtai/kernel/project/interactive_creation.py
  - src/lingtai/adapters/project_interactive_workspace.py
  - src/lingtai/adapters/project_creation_recipe.py
  - src/lingtai/adapters/project_creation_exchange.py
maintenance: |
  Keep this short public procedure aligned with the Project CLI contract. Do not
  add runtime, preset-management, or TUI workflow until separately authorized.
---
# Create a local Project

Create one fresh local LingTai seed without starting an agent:

```text
lingtai-agent project create --dir ROOT --name AGENT --preset PRESET --covenant-file FILE [--json]
```

`ROOT` must already be a directory without `.lingtai`. `FILE` is nonempty UTF-8
covenant text supplied by the caller. `PRESET` is loaded through the current
wrapper preset loader.

On success the command writes `ROOT/.lingtai/` with a `human` pseudo-agent and
one named agent, including their mailboxes, manifests, and the named agent's
`init.json` plus `settings/psyche.json` (which receives the caller covenant).
The CLI serializes that document through Psyche's owner primitive and validates
both generated owner documents before reporting success.

The command is data-only: it does not start an Agent, install a venv, contact a
provider, launch an MCP, or create TUI/global project state. Starting the agent
is a separate command:

```text
lingtai-agent run ROOT/.lingtai/AGENT
```

## Inspect local membership

Send the operation-specific request on stdin (not in argv):

```text
printf '%s\n' '{"project_dir":"/absolute/project/root"}' | lingtai-agent project inspect
```

Successful stdout is one JSON object with `status: "inspected"`, `initialized`
and `members`, plus `startup_readiness`. Each member has `directory_name`, `manifest_kind`, `role`,
`agent_name`, `address`, and `agent_id`. `directory_name` is the filesystem child;
`agent_name` is display identity and may differ. A present malformed manifest is
an `unknown` role repair target, not silently omitted. No raw manifest or
credential fields are returned. Missing `.lingtai` gives an empty observation,
not a request to initialize or start anything. Non-directory/unreadable
containers fail with exit 1 and a JSON error on stderr; do not reinterpret them
as empty projects. The caller must consume exactly one accepted stdout object
and a successful exit before using the observation.

`startup_readiness` contains `reason`, `needs_rehydration`, sorted `agents` and
`orchestrators` directory identities, and ordered `init_evidence`. Init evidence
has `directory_name`, `presence` (present/absent/stat_failed), and null `failure`
except for minimal native stat failure facts (`path_b64`, `native_errno`,
`native_winerror`). A successful stat counts even a directory as present; no
init content is read. Startup excludes dot helpers, humans and malformed members
without removing them from general membership. Reasons are not_initialized,
ready, cannot_stat_init, mixed_init, no_agents, no_orchestrator and
multiple_orchestrators. Stat failure takes precedence over mixed init, which
precedes orchestrator refusal. Refusals remain exit-0 observations, not success
authorizing launch; only ready accepts the old existing-network checks.
All-absent with agents indicates rehydration (also retained on orchestrator
refusal); it never runs a wizard or writes init. Mixed with/missing lists come
from the ordered presence evidence. Go owns the original user error prose.

This is read-only sequential evidence, not a lease, a process scan, or an
atomic snapshot. Do not authorize launch, cleanup or mutation solely from it.
Interactive creation-with-Recipe, skeleton initialization, setup, reconciliation,
import rehydration and Project lifecycle are not exposed by this operation;
the older create command remains a headless worker seed, not an interactive
orchestrator replacement.


### Preserve native Go init errors (inspection driver)

For the existing Go startup driver, keep the SAME command and live pipes. Send
ONE newline-terminated request:

```json
{"project_dir":"/absolute/project/root","init_observation_mode":"callback"}
```

On each flushed `observe_init_presence` frame validate only the closed fields
status, sequence and directory_name_b64 (canonical padded standard base64 native
filesystem bytes). Sequence starts 1; use the exact observed directory identity,
never a display label or arbitrary path. Call the original Go os.Stat ONCE on
its original joined init path. Success, even a directory, means present;
os.IsNotExist means absent; other errors mean stat_failed. Retain the ORIGINAL
error locally under sequence+directory bytes, not a reconstructed PathError.
Send one newline-terminated bound acknowledgement, for example:

```json
{"status":"init_presence_observed","sequence":1,"directory_name_b64":"YQ==","presence":"absent","failure":null}
```

Stat_failed alone sends closed factual path_b64/native_errno/native_winerror
instead of null. Never serialize exception strings, credentials or documents.
Core owns eligibility/order and readiness, stops at the first failed stat, and
never invokes the kernel native init stat in this mode. No second stat/fallback.

Accept the final inspected object only after complete transcript correlation,
closed shape/identity/reason validation, exit 0 and empty stderr. Callback-only
member directory_name_b64, readiness agents_b64/orchestrators_b64, and init-item
sequence/directory_name_b64 preserve authoritative native identity, including
surrogate-bearing labels; ordinary requests/results stay unchanged. On matched
cannot_stat_init, display the retained ORIGINAL Go error with the old wrapper
once, preserving operation, path spelling and unwrap chain. Do not infer a
Windows operation from codes. Exact schemas and consumer validation obligations
are in the [inspection exchange contract](../../src/lingtai/kernel/project/CONTRACT.md#synchronous-native-init-observation-exchange).

EOF/malformed/mismatched/private ack stops: prior intermediate frames are not
success; only one structured static stderr terminal/exit 1 is attempted, with no
partial readiness or retry. Missing/lost terminal is unknown. This exchange is
read-only, not a lease, launch permission, process scan or generic filesystem
RPC. Native Windows/name/error-chain and paired cold-CLI acceptance remain
separate requirements, not source-authoring claims.

## Approved interactive creation (Go driver)

Use `lingtai-agent project create-interactive` with live stdin/stdout pipes;
this is not the headless worker seed command. Send an explicit non-secret
projection of the reviewed draft as one JSON line. The exact fields, ordering,
and outcome rules are in the [Project transaction contract](../../src/lingtai/kernel/project/CONTRACT.md#interactive-creation-transaction).
A minimal initial line (replace paths with approved real paths) is:

```json
{"project_dir":"/approved/root","approved_root":"/approved/root","agent_name":"Display name","directory_name":"orchestrator","preset_ref":"/presets/selected.json","preset_manifest":{"llm":{"provider":"openai","model":"selected-model","api_key_env":"OPENAI_API_KEY"},"capabilities":{"shell":{"yolo":false}}},"options":{"language":"en","covenant":"Human-approved covenant","env_file":"/approved/task.env"},"recipe":"adaptive","process_evidence":"clean"}
```

The `env_file` value is an explicit non-secret path, not credential contents.
It is required when the selected LLM uses `api_key_env` without an inline key
under the current init validator. Omitting it fails before ready or writes; the
kernel does not synthesize an env file or resolve a provider key during creation.

1. Retain the wizard draft in memory through Review. Independently bind the
   approved root, normalize the selected preset without persisting it, and
   perform the real process inventory recheck. Do not turn unknown into clean.
2. Send the line, then read `ready_for_prerequisites`. Until that object arrives,
   **do not persist pending preset or credentials**. Do not log the input draft.
3. Check the returned exact `preset_ref` and nonempty `attempt_id`. Only then
   let Go persist and verify the exact preset reference and pending credentials
   using its existing owners. Send one newline-terminated acknowledgement:

   ```json
   {"status":"prerequisites_acknowledged","attempt_id":"COPY-READY-ID","preset_ref":"/presets/selected.json","accepted":true}
   ```

   Use false on persistence/verification failure. Never send credentials.
4. Accept created only after the terminal matching `created,committed:true`
   object and exit 0. Record warnings; do not regenerate init or reapply Recipe
   in Go. Persist UI preferences/registration and launch separately, without
   rolling back known publication on a UI/launch failure.
5. On documented exit-1 error, show its stable code and keep Review available.
   On unknown transport, stop and reconcile with the human before retrying;
   neither `project inspect` nor directory existence proves the lost outcome.

A valid root-local Recipe wins over packaged adaptive, with language then root
fallback. Packaged assets work in a wheel without Go extraction/global recipes.
Comment seeds Pad instead of retired init `comment_file`; covenant uses current
Psyche serialization. Procedures remain kernel-owned. External location and
command-list text may be supplied as non-secret strings; omission uses unknown
location and empty commands, with no network lookup. The kernel does not change
credentials, preset profiles, runtime settings, registration, or run an Agent.

This slice does not implement `/setup`, imported networks, existing-project
reconciliation, skeleton initialization or Project lifecycle. Full migration is
still pending; test/installed-wheel/startup acceptance is a separate gate.

## Existing Project configuration (JSON driver)

The kernel now offers the bounded `initialize`, `configure`, `propagate-policy`,
`propagate-config` and `rehydrate` operations. These add no flags: send one
EOF-delimited public JSON object on stdin. Exact closed requests, default option
values and result/error envelopes are in the
[configuration contract](../../src/lingtai/kernel/project/CONTRACT.md#existing-project-configuration-candidate-slice).
The root is the parent directory containing `.lingtai`, not `.lingtai` itself.
For example, data-only skeleton initialization is:

```text
printf '%s' '{"project_dir":"/absolute/existing/root"}' | lingtai-agent project initialize
```

Configure loads only an already-persisted selected preset reference; Go retains
credential/preset persistence. Keep current uses an empty preset_ref and explicit
keep_current/preserve_active, never a synthetic preset filename. Existing owner
bytes remain unchanged unless an explicit prompt edit is requested. New prompt
content uses Psyche's serializer; Pad replaces retired comment inputs.
Go also projects its existing language-default covenant path as public
`options.default_covenant_file` metadata, with an explicit nonempty legacy choice
in `options.covenant_file`. Core preserves the old init-path precedence (explicit,
existing nonempty, default). Fallback metadata alone never edits Psyche or reads
that legacy file; explicit prompt edits still use the current owner serializer.

Policy propagation maintains parsed preset blocks, not boot readiness. Missing
Pad/env/blueprint/preset files or malformed unrelated Psyche do not block this
policy-only write, and reader status stays `not_read`. Malformed init and write
failures remain explicit partial counts while later members continue. Configure,
config propagation and rehydrate keep their actual runtime-owner reader checks.

Imported all-absent rehydrate includes selected-source configuration. Do not
write source init first: a mixed project is refused, not automatically repaired.
A source/worker error can leave partial state, and previously written files are
not rolled back. Unknown transport does not prove either rejection or success:
no automatic retry/deletion/repair. These operations do not apply/reconcile a
Recipe, install, register or start/refresh/suspend an agent. Full Project
migration, including Recipe reconciliation and lifecycle, remains pending.

## Observe and apply an existing local Recipe

This bounded candidate uses only `ROOT/.recipe`; it never selects, imports,
replaces a bundle or creates a hidden fresh-creation attempt. For change evidence:

```text
printf '%s\n' '{"project_dir":"ROOT"}' | lingtai-agent project recipe-observe
```

Read `state` (absent/equal/changed/read_failure) AND `needs_apply`. Read failure
retains the legacy boolean, not success proof. Empty root explicitly means
absent/false, never the current directory. Nonempty root retains existing lexical path authority; missing/non-directory Recipe naturally observes absent.

To apply, send exactly one UTF-8 JSON object on stdin (no flags):

```json
{"project_dir":"ROOT","language":"en","rendering":{"time":"2030-01-02 03:04","address":"human","location":"unknown","commands":"  - /help — Help"}}
```

Outer Go resolves these **public** strings with the current greet callback:
local timestamp `YYYY-MM-DD HH:mm`, human address, cached/resolved location
joined `City, Region, Country` or `unknown`, and already-translated palette
commands. Kernel performs only ordered literal substitutions. Use `rendering:null`
for the old headless identity callback. Do not send credentials or a whole draft.

The old ApplyRecipe error semantics determine exit/status: no old error means
stdout `recipe_applied`, exit 0 (even if new current-reader receipt evidence is
partial); an old actual apply failure, rejected request or unknown driver means
one static stderr error envelope and exit 1. Do not add a launch/warning policy
from new reader/removal evidence. Validate the
whole envelope and child exit. Member receipts disclose prompt/init writes and
phase errors, actual init/Psyche reader status, and `legacy_counted`; `applied`
counts error-free processed members, `legacy_applied` is only the old count quirk.
Neither count promises launchability. Existing callers retain their returned count using `legacy_applied` and existing warning/error behavior using top-level code. Missing/unreadable/empty optional greet
is skipped and reported. Existing skills paths append only with existing skills;
no new capability is installed and no owner settings are propagated.

**Snapshot is always attempted after traversal, including partial apply.**
Read its separate attempted/removal_succeeded/copied/code fields. Removal is
best-effort and copy is not transactional; failed removal can retain extra old
files. Removal failure alone is ignored for caller errors/exits if copy succeeds,
as before. A copied snapshot can make the next observe equal even after member
failure. Prompt write errors may leave truncated/partial prompt bytes; copy
errors may leave a partial snapshot. No retries, rollback or cleanup is implied.
Unexpected/cancelled/lost output means unknown, not no-write proof. UI selection,
bundle copy/materialization/import, registration and lifecycle remain separately
owned; this is not fullProject completion. See Project Contract and PRJ004 for
acceptance scenarios. Existing declared library/language values retain Go lexical
Join/Clean semantics, including parent/non-segment/absolute-looking values; no
fresh-creation safe-sibling rule or five-OPS nonregular/symlink gate is imported.
Prompt/snapshot target following and fixed init.json.tmp + rename semantics stay
as before. This scoped caller-root Recipe authority is not general write permission.


### Retain an arbitrary Go callback (synchronous driver)

Use the SAME `lingtai-agent project recipe-apply`, no flags. With live pipes,
send ONE newline-terminated closed request instead of the EOF static form:

```json
{"project_dir":"BUNDLE","lingtai_dir":"EXPLICIT-DESTINATION-OR-STAGING","language":"en","rendering_mode":"callback"}
```

Both paths are independent, nonempty lexical caller paths; they need not be
canonical/equal/parent-child. If child cwd differs, the caller preserves original
Go path meaning before sending. `identity` mode needs no callback/ack and keeps
original bytes within kernel. Static `rendering` requests still accept multiline
or EOF-delimited JSON and retain their prior 1 MiB character bound. The new
form, rendering frames and terminal receipts have no fixed line/output cap.
Memory grows with payload; base64 requires `4*ceil(decoded_bytes/3)` ASCII bytes
plus JSON/newline and copies. Allocation/broken transport is unknown, not empty.

On each flushed stdout `render_recipe_member` frame, validate exact fields
`status,sequence,directory_name_b64,template_b64,template_bytes`. Decode standard
canonical padded base64; count BYTES, not characters/runes. Sequence starts 1.
Execute the ORIGINAL Go function exactly once on the original calling goroutine,
with `string(decoded_template)` (not member name). Send and flush one bound ack:

```json
{"status":"recipe_member_rendered","sequence":1,"rendered_b64":"","rendered_bytes":0}
```

Empty result MUST truncate/create the member prompt. Kernel finishes that member's
prompt/skills before requesting the next; function can observe preceding writes
and alter future init/tree/Recipe. It is not precomputed, batched or replayed.
No callback occurs for original absent/unreadable/empty greet, no members, or
pretraversal failure. Original template/enumeration are captured once; library
helper conditionally reads metadata a second time AFTER greet, failure nonfatal.
Never log templates, callback outputs or exception/panic text.

Interactive terminal supplements ordinary receipt fields with authoritative
per-member `directory_name_b64` and top-level `legacy_failure` (null or factual
phase/operation/base64-native-path/errno/winerror/byte-parse-offset evidence).
Display names may contain escaped surrogate characters; do not key membership
by a lossy JSON/UTF-8 replacement. Native Windows/mixed-OS name/JSON semantics
and exact Go error-message/type formatting still require paired acceptance.
No path evidence is proof of a new path safety policy or permission.

On panic/Goexit, Go MUST unwind with original semantics, close child input and
reap child, not recover into an ApplyRecipe error/success or send a substitute
ack. EOF/malformed/broken ack stops BEFORE pending prompt/skills and without
snapshot. If observable, stderr exit-1 terminal is `recipe_exchange_stopped`,
`recipe_exchange_failed`, completed receipts, pending sequence/base64 identity,
and separate `legacy_code,legacy_failure`. `partial` means known preceding writes;
`rejected` describes only pending-member rejection, not zero global effects.
Callback side effects/earlier failed writes may survive and remain unknown.
Lost terminal is unknown even after ack; ack proves rendering, NOT prompt write.
No automatic retry/rollback/cleanup, Go filesystem fallback, timeout/thread or
supervisor is introduced. This seam is not full Project completion or PR activation.
