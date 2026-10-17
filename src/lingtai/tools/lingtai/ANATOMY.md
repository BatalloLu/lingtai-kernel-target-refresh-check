---
related_files:
  - tests/test_agents_memory.py
  - src/lingtai/tools/lingtai/BEHAVIORS.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/context/ANATOMY.md
  - src/lingtai/tools/lingtai/__init__.py
  - src/lingtai/tools/lingtai/_lingtai.py
  - src/lingtai/tools/lingtai/glossary-en.md
  - src/lingtai/tools/lingtai/glossary-zh.md
  - src/lingtai/tools/lingtai/glossary-wen.md
  - src/lingtai/intrinsic_skills/lingtai-manual/SKILL.md
maintenance: |
  Keep paths real, repo-relative, duplicate-free, and reciprocal with the paired
  Contract and parent/neighbor anatomies. Update this graph when symbols,
  connections, state ownership, or composition move.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# tools/lingtai — retired character domain

Retirement records only. This is not the `lingtai` Python package/runtime.

## Components

- `__init__.py:1` and `_lingtai.py:1` are retirement records with no exported
  loader, tool, or compatibility alias.
- The retained manual explains preservation, not forced/self-evolve modes.

## Connections

No production consumer imports this domain. Private memory migration and
composition now belong to [Pad](../pad/ANATOMY.md).

## Composition

Parent: [tools](../ANATOMY.md). Promise: [Contract](CONTRACT.md).
Manual: [retirement guidance](../../intrinsic_skills/lingtai-manual/SKILL.md).

## State

Existing `system/lingtai.md` is left untouched; Pad preserves it once. There is
no separately injected `character` state.

## Notes

[LG001](BEHAVIORS.md#behavior-lg001) guards retirement, not an active tool.
