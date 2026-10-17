---
related_files:
  - src/lingtai/ANATOMY.md
  - src/lingtai/agent.py
  - src/lingtai/intrinsic_skills/ANATOMY.md
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/skills/BEHAVIORS.md
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/_catalog.py
  - tests/test_standard_skill_discovery.py
  - src/lingtai/tools/skills/manual/SKILL.md
  - src/lingtai/init_schema.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/skills/glossary-en.md
  - src/lingtai/tools/skills/glossary-zh.md
  - src/lingtai/tools/skills/glossary-wen.md
  - src/lingtai/tools/skills/manual/assets/skill-template.md
  - src/lingtai/tools/skills/manual/reference/cleanup-footprint-contract.md
  - src/lingtai/tools/skills/manual/scripts/validate.py
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
# core/skills

Skills capability — per-agent skill catalog and skill-manual surface. This is the renamed successor of the old `library` capability. It scans the existing `.library/` directory plus configured extra paths and bounded standard skill folders, renders a YAML catalog (one `- name:` block per skill with `location:` and a `description:` block scalar), and injects it into the `skills` prompt section. It never writes skill files; installation remains the Agent initializer's job.

## Components

- `skills/__init__.py` — the capability implementation. It registers **no** model-facing tool: the former public `skills` root and its `info` action were retired into the read-only `psyche(action='skills')` manual loader. Path helpers `_resolve_path`, `_standard_paths`, and `_compose_paths` select and canonical-deduplicate vanilla roots; `_scan` delegates to the shared Markdown scanner. `_reconcile` composes the catalog and `setup` owns lifecycle entry. [SK002](BEHAVIORS.md#behavior-sk002) guards bounded discovery, order, and plugin separation; `tests/test_standard_skill_discovery.py` supplies thin regression assertions.
- `skills/manual/` — `skills-manual` skill documentation, template assets, and validator script. The validator can optionally require `last_changed_at` for LingTai-maintained skill bundles. This is the body `psyche(action='skills')` returns.

## Connections

- `lingtai.tools.registry` maps canonical `skills` here as a *capability* (`BUILTIN_TOOLS`/`CORE_DEFAULTS`); it is not an intrinsic and registers no tool. Former skill-catalog `library.paths` compatibility is removed in the clean rename.
- `Agent._install_intrinsic_manuals()` copies every capability `manual/` bundle into `.library/intrinsic/capabilities/<name>/`, then re-runs `skills._reconcile()` for first-turn catalog freshness when `skills` is loaded (`src/lingtai/agent.py:793-805`).
- `Agent._reload_prompt_sections` re-runs `_reconcile(..., publish=False)` so a full `context.rebuild` (and passive refresh/molt reconstruction) recomposes this catalog with every other canonical section before one final prompt publication (`src/lingtai/agent.py:2743-2756`).
- [`../psyche/ANATOMY.md`](../psyche/ANATOMY.md) owns the one public root; it loads this package's `manual/SKILL.md` and holds no reference to the catalog or its composer.
- The daemon capability blacklists `skills` so emanations do not borrow it from the host tool floor (`../daemon/__init__.py:573`).
- The generic [`../tool_family/ANATOMY.md`](../tool_family/ANATOMY.md) owns the reusable schema-composition/dispatch infrastructure. This package no longer builds a `ToolFamily`; only `psyche` does.

## Public API

None. This package exposes no model-facing tool, schema, or dispatch entry
point. Its public surface is the read-only `psyche(action='skills')` manual
loader, owned by [`../psyche/CONTRACT.md`](../psyche/CONTRACT.md).

`setup(agent, paths=...)` is the capability lifecycle entry point: it reconciles
the catalog and injects the `skills` prompt section. `_reconcile` is the private
composer shared by that setup/refresh path and by full-context reconstruction.

## State

- Skill storage remains `<agent>/.library/` for compatibility: `intrinsic/` is CLI-managed and `custom/` is agent-authored (`__init__.py:182-185`).
- `_standard_paths` probes nearest Git markers and, when the current workdir has `init.json`, the project above a literal `.lingtai` ancestor; it selects only conventional `.agents/skills` and `.claude/skills` roots through the nearer boundary (workdir only without either), then the two user-home roots. `_compose_paths` canonical-deduplicates those after built-in and explicit roots, without consulting plugin registration paths.
- Config path source is canonical `manifest.capabilities.skills.paths` (`src/lingtai/init_schema.py:498-506`).
- Prompt state is the `skills` section, written only by `_reconcile` — reached by `setup` and by full-context reconstruction, never by a model-facing action (`__init__.py:218-227`).
- Health check expects `.library/intrinsic/capabilities/skills/SKILL.md` and reports `skills_manual`, with `library_manual` retained as a response compatibility key (`__init__.py:229-251`).

## Notes

- The `.library/` directory name and `.library_shared/` convention are intentionally preserved in this rename-only change; they are storage compatibility names, not the user-facing capability name.
- There is no `skills` tool call any more: use `psyche(action="skills", input={}, reasoning="load the Skills manual")` for the manual, and let setup/refresh or `context.rebuild` reconcile the catalog. The retired `library` root is likewise not registered.
- LingTai-maintained `SKILL.md` files carry `last_changed_at` in frontmatter, initialized from git history for metadata-only backfills and updated on substantive skill edits.

Standard Claude-style `SKILL.md` files may omit `name`: the shared parser
uses the containing directory name while retaining required `description`.
`KNOWLEDGE.md` still requires an explicit `name`.
