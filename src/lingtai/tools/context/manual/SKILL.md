---
name: context-manual
description: |
  Use for an unfamiliar or consequential context operation, session journaling, handoff, or context-loss recovery; routine calls can follow the schema.
version: 2.4.0
last_changed_at: "2026-10-12T00:00:00Z"
related_files:
- src/lingtai/tools/context/__init__.py
- src/lingtai/tools/context/_molt.py
- src/lingtai/tools/context/_session_journal.py
- src/lingtai/tools/system/summarize.py
- src/lingtai/agent.py
- src/lingtai/tools/psyche/CONTRACT.md
- src/lingtai/kernel/base_agent/CONTRACT.md
- src/lingtai/kernel/base_agent/lifecycle.py
maintenance: |
  This package is the canonical Context manual source and runtime-installed owner.
  Update it when the tool/capability behavior changes.
---

# Context Manual

Use the schema for routine calls; open this manual for unfamiliar workflows or recovery risk. Context has four operations:

- `summarize` records compact replacements for selected old tool results; it does not rebuild provider context.
- `rebuild` recomposes all canonical prompt sources, applies summaries, then requests provider replay. Bare `input={}` is valid; durable file edits do not hot-load. It is strongly discouraged as routine compaction, tool-result cleanup, or a ceremony after every Pad/Knowledge edit: full replay is costly, can disturb prompt-prefix cache reuse, and still retains the bulky history.
- `molt` sheds conversation while retaining durable files and stores. It is an irreversible boundary, not housekeeping, but it is the preferred deliberate response to substantial or noisy history or sustained pressure when a fresh briefing is worth its cost.
- `manual` returns the installed `context-manual` without changing context.

## Shortest useful path

When current `meta_guidance` says a consumed result needs a posteriori compaction, inspect it first, then use `context(action="summarize", input={"items": [...]})`; do not use this as routine cleanup. Prefer a deliberate molt over a manual rebuild when history is substantial or noisy. Routine durable edits can simply wait for the next natural molt or reload; they do not need an immediate rebuild. Rare exception: when new canonical prompt sources or pending summaries must apply in this conversation and a molt is unsuitable, make one targeted `context(action="rebuild", input={})`—never a loop. The [summarize reference](reference/summarize-manual/SKILL.md) owns selection, recovery, and pressure guidance.

Before a deliberate molt:

1. Make the task, authority, blockers, live IDs, evidence paths, and next action recoverable. Update only stores that changed. No summarize or rebuild is required first.
2. Write the session-journal child and parent-index pointer. It must be `knowledge/session-journal/<entry>/KNOWLEDGE.md`, nonempty UTF-8, with valid `name`/`description` frontmatter and `type: session-journal` or `session_journal: true`. Use the [journal scaffold](assets/session-journal-entry-template.md) if useful.
3. Pass its path as `session_journal_path` and write the shortest sufficient handoff: active state, verified results, pending authority, next steps, live IDs, artifact/evidence paths, blockers, and lessons. Use the [optional handoff scaffold](assets/molt-template.md) only when it lowers real risk.
4. Call `context(action="molt", ...)`. The journal is validated before shedding; invalid input leaves molt count/history untouched. `keep_tool_calls` refuses unknown IDs; `keep_last` preserves a suffix and complete tool-call batches. The schema is authoritative.

Molt preserves durable files and source reconstruction: it archives/snapshots the old conversation, rebuilds the fresh prompt, and publishes a post-molt notification. It does not delete durable stores. Molt for sustained pressure, an explicit human reset, confusion, or a long-inactivity reminder as described below—not merely task completion. Tending stores need not create gratuitous edits or new skills.

A `system.auto_molt` reminder is sent once per continuous IDLE/ASLEEP period ≥ the positive `LINGTAI_AUTO_MOLT_IDLE_SECONDS` duration (default 1800 s), regardless of low, high, unknown or unloaded context. The producer does not read context or create a session. Real work always wins. If your CURRENT context is strictly >100000 tokens (not cumulative spending), consider ONE safe idle-boundary molt: tend only changed stores, write a valid session journal, and preserve unfinished authorized duties; defer the molt rather than discard them. Otherwise do absolutely nothing: no tools, external reply, or molt; return IDLE. After any post-molt reorientation remain IDLE until human input or other real work; do not invent work from the reminder or handoff. An ordinary ACTIVE notification wake clears the period and later inactivity starts another, even if context is below 100000 after molt. The timer/latch are process-local and reset on restart; the runtime [gate contract](../../../kernel/base_agent/CONTRACT.md#contract-rules) owns these semantics. Notification delivery may start an ordinary paid turn. This is a cache-warm attempt, not a cache TTL or free-turn guarantee; the kernel never forces discard or generates a journal.

Ordinary molt/rebuild retains notification delivery identity within this agent process: already delivered events do not automatically replay. Carry still-needed message content and routing IDs in your authorized handoff; new post-molt notices and new producer events still deliver. A new Agent/process restart starts fresh bookkeeping, not cross-crash exactly-once.

## After a molt

Read applicable AGENTS.md and CLAUDE.md working instructions after fresh context,
and applicable nested instructions when entering that project scope. Do not
paste their bodies into private memory or create/overwrite those files merely
for orientation. Pad and Knowledge remain private memory; legacy character is
preserved once into Pad, not injected as a separate section.

Read the post-molt notification/`summary_path`, current prompt/Pad, journal index, and new producer messages. An inactivity-triggered molt with no remaining authorized work ends in IDLE waiting for human input or other real work; its own post-molt notice is reorientation, not new work. Treat the briefing as context, not a command to run blindly. Re-check IDs and evidence paths. After reorientation, explicitly choose `continue`, `defer`, or `obsolete` and record that decision in your session journal/pad. The post-molt notification is delivered once and is not re-attached automatically; there is no notification dismiss action, and delivery does not mean any human task is completed (`notification(action="check")` rereads it deliberately). Resume through the originating channel/tool; a saved briefing or provider replay is not proof of delivery.

The action `summarize` records Context history; the optional root `summarize` boolean only presents results and defaults to true. They are not the same input. Proactively set root `summarize=false` for verbatim manuals and mandatory gates, exact names/paths, field presence, source, diffs, or evidence; otherwise specify what to retain in `reasoning`. Use `psyche(action="manual", input={}, reasoning="load durable-store routes")` for store ownership; durable writes go through `shell` (verify the old text exists exactly once before replacing, and read the file back afterwards), and may wait for the next natural molt or reload; rebuild only under the rare exception above.
