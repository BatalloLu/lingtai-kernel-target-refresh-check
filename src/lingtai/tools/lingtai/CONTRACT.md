---
name: lingtai-tool-contract
tool: lingtai
contract_version: 3
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/lingtai/BEHAVIORS.md
  - tests/test_agents_memory.py
  - src/lingtai/tools/lingtai/ANATOMY.md
  - src/lingtai/tools/lingtai/__init__.py
  - src/lingtai/tools/lingtai/_lingtai.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/psyche/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/intrinsic_skills/lingtai-manual/SKILL.md
maintenance: |
  This component contract is governed by root CONTRACT.md. Keep the paired
  ANATOMY.md, manual, schema, glossary resources, and focused tests in sync.
  Bump contract_version for breaking changes. The character domain and loader
  are retired; Pad owns one-time legacy preservation without deleting sources.
---
# Retired LingTai character domain

## Purpose and ownership

The separate character/LingTai domain is retired by human instruction. This does
not retire the `lingtai` Python package or mechanical identity.
Guarded by [LG001](BEHAVIORS.md#behavior-lg001).

## Public port

No tool, loader, `psyche.lingtai` route, or compatibility alias remains. Old
string `lingtai`/`lingtai_file` init values remain accepted for one-way Pad
preservation, not a continuing character binding. A readable file wins over
inline fallback. Disk character and a distinct configured value both survive;
no old init is rewritten and no existing upgrade is blocked just for those keys.
New serializers/templates omit them. Forced/self-evolve semantics are retired.

## Memory preservation

Existing `system/lingtai.md` is never removed or emptied. Its contents are
preserved once by the [Pad contract](../pad/CONTRACT.md#legacy-preservation),
without any separate `character` injection. Subsequent memory edits belong in
`system/pad.md` or Knowledge. Names and Covenant keep their existing owners.

## Evidence

[LG001](BEHAVIORS.md#behavior-lg001), `tests/test_agents_memory.py` and the Psyche
inventory tests guard strict retirement and non-destructive migration.
