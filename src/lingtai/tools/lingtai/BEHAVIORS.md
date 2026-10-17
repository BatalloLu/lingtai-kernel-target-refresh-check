---
name: lingtai-tool-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - tests/test_agents_memory.py
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/lingtai/ANATOMY.md
  - src/lingtai/tools/lingtai/__init__.py
  - src/lingtai/tools/lingtai/_lingtai.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  lingtai tool behavior clause changes, update the guarding LABT here in the
  same change.
---
# Unified memory acceptance

## Behavior LG001 — retired character has no tool, loader or injected section

- **id**: LG001
- **title**: retired character has no tool, loader or injected section
- **guards**: [lingtai-tool-contract § Public port](CONTRACT.md#public-port)
- **runner**: a LingTai coding agent with Shell access
- **prerequisites**: repository checkout, repository Python environment; temporary test workdirs only
- **estimate**: 3 minutes

### Steps
1. From the repository root, run `.venv/bin/python -m pytest -q tests/test_agents_memory.py tests/test_psyche_family.py tests/test_psyche_prompt_settings.py`.
2. Inspect the captured results for migration byte preservation, repeated composition,
   interruption before marking, real CLI init seed wiring and full prompt build.
3. Confirm the lifecycle case exercises ordinary rebuild, refresh setup and real
   journal-gated molt without provider requests. Inspect the exact public Psyche
   inventory: `pad | knowledge | skills | instructions | covenant | settings | manual`.

### Expected evidence
- [ ] All selected tests pass; no external provider is called.
- [ ] Old source bytes survive, Pad contains the legacy body once, and a later Pad
      rewrite does not resurrect the retired source. No `character` section remains.
- [ ] Pad and pinned references reload; startup/fresh-context guidance names applicable
      AGENTS.md/CLAUDE.md and scope entry, but their bodies are not pasted or overwritten.
- [ ] Old inline/file init seeds remain accepted, preserve their bytes once
      alongside existing Pad/disk character, and never rewrite init or rebind after marking.

### Pass / Fail
Pass only when every check holds. A failed or unexecuted test is not acceptance;
record exact output and unresolved risks. No live agent memory may be modified.
