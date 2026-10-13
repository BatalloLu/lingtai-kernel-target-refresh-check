---
related_files:
  - src/lingtai/kernel/project/recipe.py
  - src/lingtai/adapters/project_recipe.py
  - src/lingtai/adapters/project_recipe_exchange.py
  - src/lingtai/adapters/project_inspection_exchange.py
  - tests/test_project_inspection_exchange.py
  - src/lingtai/cli_project_recipe.py
  - tests/test_project_recipe.py
  - tests/test_project_interactive_diagnostics.py
  - src/lingtai/kernel/project/configuration.py
  - src/lingtai/adapters/project_configuration.py
  - src/lingtai/cli_project_configuration.py
  - tests/test_project_configuration.py
  - tests/fixtures/project_configuration.json
  - src/lingtai/kernel/ANATOMY.md
  - src/lingtai/kernel/project/CONTRACT.md
  - src/lingtai/kernel/project/__init__.py
  - src/lingtai/adapters/project_workspace.py
  - src/lingtai/cli_project.py
  - src/lingtai/tools/psyche/settings.py
  - docs/references/project-create.md
  - tests/test_project_creation.py
  - src/lingtai/kernel/project/inspection.py
  - src/lingtai/adapters/project_inspection.py
  - tests/test_project_inspection.py
  - src/lingtai/kernel/project/BEHAVIORS.md
  - src/lingtai/kernel/project/interactive_creation.py
  - src/lingtai/adapters/project_interactive_workspace.py
  - src/lingtai/adapters/project_creation_recipe.py
  - src/lingtai/adapters/project_creation_exchange.py
  - tests/test_project_interactive_creation.py
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/comment/comment.md
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/comment/wen/comment.md
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/comment/zh/comment.md
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/greet/greet.md
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/greet/wen/greet.md
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/greet/zh/greet.md
  - src/lingtai/kernel/project/recipe_assets/adaptive/recipe/recipe.json
  - pyproject.toml
  - MANIFEST.in
  - src/lingtai/CONTRACT.md
  - src/lingtai/tools/psyche/CONTRACT.md
  - src/lingtai/tools/pad/CONTRACT.md
maintenance: |
  Keep this map reciprocal with the Project Contract and parent kernel Anatomy.
  Update it with changed Project ownership, composition, or state; code remains
  the structural source of truth.
---
# project

`kernel/project` owns the small Core boundary for creating one fresh local
Project seed, inspecting local membership, and prerequisite-gated hidden
interactive creation. Its Contract defines the CLI-visible behavior.

## Components

- `__init__.py` — request/seed/result values, one `ProjectWorkspacePort`, input
  validation, and `ProjectCreationUseCase`.
- `src/lingtai/adapters/project_workspace.py` — the filesystem implementation
  that exclusively creates `.lingtai`, writes the seed, and calls an injected
  reader validator.
- `src/lingtai/cli_project.py` — parser and composition root for caller inputs,
  wrapper preset loading, the adapter, and output.

- `inspection.py` — typed member evidence, role policy and inspection use case
  (`src/lingtai/kernel/project/inspection.py:11-234`); guarded by PRJ001/PRJ005.
  Typed startup readiness and ordered stat-presence evidence live here; Core owns
  init all-or-none then exact-one-orchestrator classification.
- Filesystem inspection enumerates immediate children and delegates manifest
  parsing to the presence adapter and supplies stat-only init observations
  (`src/lingtai/adapters/project_inspection.py:21-80`).

- `interactive_creation.py` — typed draft/options/attempt/seed/result, specialized
  workspace/Recipe/prerequisite Ports, pure membership and seed policy, and the
  real ordered use case (`src/lingtai/kernel/project/interactive_creation.py:16-254`).
- Hidden filesystem workspace uses owner writers/readers and native exclusive
  rename (`src/lingtai/adapters/project_interactive_workspace.py:25-208`); pending
  init preflight forwards the explicit env-file path and translates owner validation
  failure before staging or prerequisite exchange.
- Creation Recipe adapter supplies project-local authority or actual adaptive
  wheel resources, layers and snapshot (`src/lingtai/adapters/project_creation_recipe.py:16-105`).
- JSON-lines driving/prerequisite adapter validates the operation-specific
  request and emits ready/consumes bound ack
  (`src/lingtai/adapters/project_creation_exchange.py:25-114`).
- Shared fake/filesystem and actual root CLI source tests are in
  `tests/test_project_interactive_creation.py`; manual acceptance is PRJ002.

## Connections

Inspection composition injects `FilesystemProjectInspectionAdapter` into
`ProjectInspectionUseCase`. Core uses Agent Presence values and human policy;
only the outer adapter enumerates filesystem children and stats eligible init
paths when asked by Core. The ordinary inspect CLI emits the additive typed
readiness payload through result.to_payload; no CLI policy/command is added.
Callback mode injects the inspection decorator instead, delegating the SAME
membership discovery and replacing only init observation I/O. Core, its Port
and readiness policy are unchanged; Core never sees the stream or sequence.
No Agent is constructed.

`cli_project` calls wrapper `agent.load_preset`, asks Psyche's public v1
serializer for the owner-document content, and supplies the same init and
Psyche owner readers used by reconstruction. Creation Core receives that content
as an opaque seed string and depends only on `ProjectWorkspacePort`; the adapter
depends inward on Core values.

Interactive Core owns seed/admin/preset authorization and sequencing; its
workspace receives the specialized seed, not generic dict mutation commands.
The workspace receives wrapper preset loading and Psyche serialization at the
CLI composition root; it imports the real init/Psyche readers and presence
translation outside Core. Recipe resources depend on the concrete workspace
only for staging ownership and paths. The exchange adapter implements the
prerequisite Port; Go remains the actual credential/preset persistence owner.

## Composition

`lingtai-agent project create --dir ROOT --name AGENT --preset PRESET
--covenant-file FILE` constructs a request, asks the use case to create a seed,
and emits a small result. It never calls `Agent.start` or `cli.run`.

`lingtai-agent project create-interactive` consumes a reviewed JSON line,
constructs `InteractiveCreationUseCase` with the three adapters, and flushes
ready/consumes ack before terminal created. It never starts `Agent`.

## State

Success writes `ROOT/.lingtai/` with `human` and the named agent, their
mailboxes and manifests, plus the named agent's `init.json` and
`settings/psyche.json`. No global or runtime state is written.

Interactive creation builds under owned sibling `.lingtai.create-*`, writes
root `.recipe` only for the packaged fallback, and snapshots behavior inside
staging. Only final `.lingtai` publication is atomic. Dependencies and root
Recipe writes are not compensated. Known publication never rolls back;
postcommit preferences, registration and launch remain Go-owned.

## Notes

The public command procedure is
[`docs/references/project-create.md`](../../../../docs/references/project-create.md).

## Existing configuration slice

`configuration.py` owns typed operation requests, specialized document/seed/write
receipts, `ProjectConfigurationPort`, and `ProjectConfigurationUseCase` for
initialize/configure/propagate-policy/propagate-config/rehydrate; guarded by
PRJ003. `src/lingtai/adapters/project_configuration.py` implements sequential
Project-local raw reads, individual atomic writes and actual init/Psyche reader
seams. `ProjectConfigurationPort.save_policy_init` and the matching filesystem
method persist only Core-authored policy edits without reconstruction; configured,
config-propagated and rehydrated init writes retain their existing owner readers.
`ConfigurationOptions` carries outer explicit/default legacy covenant paths;
Core selects explicit, existing, then default without reading global files.
`src/lingtai/cli_project_configuration.py` is the strict JSON stdin driver
and outer preset/Psyche composition. `cli_project.py` only registers/dispatches
these operations; existing create/inspect/interactive code is unchanged.
`tests/test_project_configuration.py` shares one matrix across fake and real
filesystem adapters. `tests/fixtures/project_configuration.json` carries the
public preservation/authorization cases for the paired Go consumer. No runtime,
credential, registry, lifecycle or Recipe reconciliation ownership is claimed.

The narrowly scoped `cli_project._create_interactive.selected_preset_loader`
contains ordinary kernel preset normalization diagnostics around the actual
selected load only and restores its logger in finally (PRJ002). Actual-CLI
legacy root-context success/mismatched-persistence regressions are authored in
`tests/test_project_interactive_diagnostics.py`, without adapter/reader changes.

## Existing local Recipe observation/apply

`recipe.py` owns typed observations, specialized `ProjectRecipePort`, optional
literal greet rendering, target eligibility, additive path decisions and ordered
`ProjectRecipeUseCase` (PRJ004). `src/lingtai/adapters/project_recipe.py` is the
standalone filesystem realization for existing `.lingtai`, not a creation
attempt: byte-tree evidence, local metadata/layer reads, direct prompt writes,
normalized opaque init evidence, specialized skills writes through current
public capability normalization and init/Psyche readers, and legacy normal-traversal always-
attempted best-effort-remove/copy snapshot. `cli_project_recipe.py` composes those
seams and strict stdin/stdout/stderr envelopes; `cli_project.py` registers two
no-flag commands. Existing and synchronous thin source contracts live in `tests/test_project_recipe.py`;
execution/Go callsites are parent-owned. Procedure remains the paired
`docs/references/project-create.md` manual. No fresh workspace, bootstrap,
materialization, import, registry or lifecycle owner was added.


The synchronous existing-member extension (PRJ004) is owned by
`RecipeGreetRenderingPort`/immutable `RecipeMemberGreet` and specialized
`RecipeExchangeStopped` (`src/lingtai/kernel/project/recipe.py:65-153`).
`JsonRecipeRenderingAdapter` binds one flushed frame to one pending ack, using
canonical base64/growing lines (`src/lingtai/adapters/project_recipe_exchange.py:34-76`).
The existing driver composes independent bundle/destination and detects the
closed new line form without changing valid old EOF/multiline requests
(`src/lingtai/cli_project_recipe.py:27-164`). Core retains the original template
and one enumeration, renders immediately before each prompt and writes even
empty results; normal traversal alone reaches snapshot. Filesystem name bytes
and factual native failure evidence remain outer-owned
(`src/lingtai/adapters/project_recipe.py:18-35`, `:108-120`, `:188-213`).
Existing static envelopes are unchanged; interactive receipts add lossless name
identity and first legacy failure separately from diagnostic reader evidence.
The manual remains reachable from both owner twins. This is source authoring,
not Go consumption/acceptance or a full Project migration claim.

The specialized inspection exchange (PRJ006) uses immutable `InspectionRequest`
and construction-bound `JsonProjectInspectionAdapter`
(`src/lingtai/adapters/project_inspection_exchange.py:56-175`). The CLI selects
it only for explicit callback mode (`src/lingtai/cli_project.py:111-134`). The
adapter flushes a member request, consumes one exact ack and returns existing
`ProjectInitObservation`; it never calls the decorated init observation. It
holds an ephemeral immutable observation transcript for terminal correlation,
not a cache, service locator or repeat scan. Callback projection adds native
base64 identity to members/startup arrays/evidence and sequence to evidence.
No persistent state or filesystem writes are owned by this exchange. Thin
protocol cases are in `tests/test_project_inspection_exchange.py`; parent owns
execution, installed CLI and paired Go native-error acceptance.
