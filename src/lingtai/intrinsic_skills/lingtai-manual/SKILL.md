---
name: lingtai-manual
description: |
  Retirement reference for legacy character memory; use unified Pad and Knowledge.
version: 2.1.0
last_changed_at: 2026-09-29T00:00:00Z
related_files:
- src/lingtai/tools/lingtai/__init__.py
- src/lingtai/tools/lingtai/_lingtai.py
- src/lingtai/tools/lingtai/CONTRACT.md
- src/lingtai/tools/psyche/CONTRACT.md
- src/lingtai/intrinsic_skills/psyche-manual/SKILL.md
- src/lingtai/tools/context/manual/SKILL.md
maintenance: |
  Keep the manual-only Psyche route, Shell ownership of durable edits, no-hot-load
  rule, retirement, and unified Pad reconstruction route aligned with code.
---
# Retired character memory

There is no separate character/LingTai memory domain or `psyche.lingtai` route.
Use `psyche(action="pad", input={}, reasoning="load memory guidance")`.
Pad and Knowledge are private memory; applicable AGENTS.md and CLAUDE.md hold
project working instructions. No forced/self-evolve mode remains.

Existing `system/lingtai.md` is preserved once into `system/pad.md` without
modifying the old file. The one-time marker prevents re-append after later Pad
rewrites. Edit unified Pad or Knowledge thereafter, not the old source.
Old string `lingtai`/`lingtai_file` init values remain accepted as one-way
migration inputs. A readable configured file wins over inline fallback; its
bytes and any distinct disk character are preserved in Pad once. Marked migration
never reopens those old sources, and the runtime never rewrites old configs.
New templates and serializers omit the old keys.
Mechanical names and Covenant have not changed owners.
