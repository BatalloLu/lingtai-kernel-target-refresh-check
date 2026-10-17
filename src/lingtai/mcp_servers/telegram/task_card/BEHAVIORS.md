---
name: telegram-task-card-behavior-tests
behavior_version: 3
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - tests/test_apriori_summary_session_cost.py
  - src/lingtai/mcp_servers/telegram/task_card/CONTRACT.md
  - src/lingtai/mcp_servers/telegram/task_card/ANATOMY.md
  - src/lingtai/mcp_servers/telegram/task_card/resident.py
  - src/lingtai/mcp_servers/telegram/task_card/SKILL.md
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  telegram task-card projection behavior clause changes, update the guarding
  LABT here in the same change.
---
> Test-reference maintenance (2026-10-12): `retired-test:` identifiers below name removed pytest coverage, not runnable selectors or replacement conformance. Product promises are unchanged; manual acceptance remains necessary where automated coverage was surrendered.

# Telegram Task Card Projection Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/mcp_servers/telegram/task_card/CONTRACT.md` (programmable body
only when status is exactly active and nonempty; safe Markdown rendering;
diff-only projection; no-op preservation; automatic per-call token metrics).
Pinned pytest commands
must run from the repo root with
the project's Python.

## Behavior TT001 — the programmable frame is composed only for exact active with a nonempty body, and diff-only updates suppress transport churn

- **id**: TT001
- **title**: the programmable frame is composed only for exact active with a nonempty body, and diff-only updates suppress transport churn
- **guards**: `telegram-task-card-projection` § Behavior
- **runner**: any LingTai agent with `shell` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with `taskcard/status` and `taskcard/taskcard.md`
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed** and capture the outcome.
2. In `<scratch>`, set `taskcard/status` to exact `active` with a nonempty body and project the card; then set status to a missing/unreadable value and project again; record both compositions.
3. Re-project with identical body bytes and confirm no transport update occurs (diff-only); set status to exact `inactive` twice and confirm the second projection delivers nothing further.

### Expected evidence
- [ ] Step 1: the programmable projection suite passes, pinning active projection, diff-only updates, exact-`inactive` frame exclusion, reactivation, and last-good preservation.
- [ ] Step 2: the programmable frame is composed only for exact `active` with a nonempty body; missing/unreadable status or blank body is a no-op that preserves the last valid programmable frame.
- [ ] Step 3: identical body bytes produce no transport update; exact `inactive` idempotently excludes only the programmable frame and never deletes the resident message, the local body, or pauses automatic updates.

### Pass / Fail
Pass when the suite passes and the active/diff-only observations hold. Fail on programmable composition for a non-active status, on a transport update for identical bytes, or on `inactive` clearing the resident message or body; record the evidence trail in the task report.

## Behavior TT002 — automatic API-call dividers show reasoning tokens beside output tokens

- **id**: TT002
- **title**: automatic API-call dividers show reasoning tokens beside output tokens
- **guards**: `telegram-task-card-projection` § Behavior rule 9
- **runner**: any LingTai agent with `shell` access to this repository
- **prerequisites**: a clean checkout of `<repo>`
- **estimate**: ≈ 2 minutes

### Steps
1. From `<repo>`, **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed** and capture the outcome.
2. Project one tool-call group whose notification carrier reports `current_call.output`, `current_call.thinking`, cache miss/rate, and session context.
3. Project one pure-text group whose `llm_response` reports `output_tokens` and `thinking_tokens`, then repeat without a thinking field.
4. Project text, tool-only and mixed `llm_response.stream_timing` with first actual output 1.2s, generation interval 4s and 200 total output tokens (including 20 thinking; retain measured non-reasoning count 180); then omit timing or final usage.

5. Replay and live-append measured IDLE intervals between progress rows, then tool-only, missing-field, ASLEEP and restart-crossing gaps.
6. Replay and live-append consecutive parent inputs 156185 then 157504 with cached input 153600; include pure-text predecessors, later carriers, duplicate ids, malformed input/generation and lifecycle reset events.

### Expected evidence
- [ ] Step 1: the automatic event-tail suite passes.
- [ ] Step 2: the divider contains `↓<output> (<thinking>) ↑<cache-miss>` with compact counts, while `_usage` remains private projection state.
- [ ] Step 3: the `llm_response` fallback renders the same parenthesized form; an old event without thinking tokens preserves the prior output/cache/context line with no dangling parentheses.
- [ ] Step 4: time and speed occupy their own line (`↻12.4s · ⚡1.2s · 38 tok/s`), token symbols remain on the next line; unavailable evidence omits the new metric, never inferred zero.

- [ ] Step 5: only complete IDLE evidence adds `☕X.Ys` on the first line; gap, first-output and speed values stay unchanged; unknown coverage omits coffee.
- [ ] Step 6: the token row shows `Δ +1.3k` separately from `↑3.9k`, with no word `input`; zero and negative changes are valid, unreliable predecessors omit delta, and initial replay matches incremental append without changing other channels.

### Pass / Fail
Pass when both normalized usage paths render the same parenthesized reasoning count immediately after output and legacy missing-field input remains unchanged. Fail if the count is misplaced, reasoning text is exposed, or missing/malformed data leaves a dangling marker.

## Behavior TT003 — generated a-priori summaries add an existing-data-only cost line after the successful tool row

- **id**: TT003
- **title**: generated a-priori summaries add an existing-data-only cost line after the successful tool row
- **guards**: `telegram-task-card-projection` § Behavior rule 10 and Contract rule 11
- **runner**: any LingTai agent with `shell` access to this repository
- **prerequisites**: a clean checkout of `<repo>`
- **estimate**: ≈ 2 minutes

### Steps
1. From `<repo>`, **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed** and capture the outcome.
2. Project an existing successful `tool_result` followed by `apriori_summary_generated`, plus its already-recorded `source=summarize_apriori` token-ledger row, all sharing one `tool_call_id`.
3. Repeat with missing, malformed, mismatched, and unsuccessful inputs, and restart-rehydrate the valid case.

### Expected evidence
- [ ] Step 1: the automatic event-tail suite passes.
- [ ] Step 2: exactly one `(summary, <elapsed>, <input> in, <output> out)` line follows the completed tool row; elapsed derives from event timestamps and tokens from the bounded ledger tail.
- [ ] Step 3: valid data survives restart rehydration; all invalid/legacy cases preserve old output, while generated summary text, tool-result bodies, and provider metadata never render.

### Pass / Fail
Pass when only fully correlated existing data produces the second line in the required order and all unsafe/malformed cases omit it. Fail if a new producer event is required, more than the bounded ledger tail is read, an unsuccessful tool receives a summary line, or private payload fields render.

## Behavior TT004 — Markdown-authored programmable content renders safely inside the complete Telegram resident

- **id**: TT004
- **title**: Markdown-authored programmable content renders safely inside the complete Telegram resident
- **guards**: `telegram-task-card-projection` § Behavior rule 13 and Contract rule 14
- **runner**: any LingTai agent with `shell` access to this repository
- **prerequisites**: a clean checkout of `<repo>`
- **estimate**: ≈ 2 minutes

### Steps
1. From `<repo>`, **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed** and capture the outcome.
2. Project an active `taskcard/taskcard.md` body containing ATX heading and subheading lines, `**bold**`, inline backtick code, nested unordered/task-list items, and an ordered item onto a resident that already has automatic content.
3. Repeat with raw HTML, `<`, `>`, `&`, and unmatched bold/backtick delimiters; inspect both the provider text and the shared resident slot.

### Expected evidence
- [ ] Step 1: the programmable projection suite passes.
- [ ] Step 2: the complete provider message retains automatic content and its Telegram HTML header, while the programmable heading markers, strong delimiters, backticks, and unordered markers are replaced by supported rendered HTML/bullets under `parse_mode=HTML`.
- [ ] Step 3: raw HTML and special characters are escaped, generated tags remain balanced, malformed delimiters remain literal text, and the shared programmable slot still equals the exact authored Markdown bytes.

### Pass / Fail
Pass when supported Markdown renders without visible source markers, unsafe input cannot become provider markup, malformed input cannot unbalance generated HTML, and raw slot/diff-only state is unchanged. Fail on literal markers for supported syntax, HTML injection, malformed generated tags, any change to ordinary Telegram rendering, or mutation of the authored resident slot.

## Behavior TT005 — Claude Code aliases retain exact returned-model evidence

- **id**: TT005
- **title**: Claude Code aliases retain exact returned-model evidence
- **guards**: [telegram-task-card-projection § Behavior 9](CONTRACT.md#behavior)
- **runner**: any LingTai agent with shell access to this repository
- **prerequisites**: the repository Python and local mocked CLI fixtures; no login or provider call
- **estimate**: approximately 2 minutes

### Steps
1. **Automated step unavailable: pytest recipe retired (2026-10-12); no replacement conformance claimed**.
2. Inspect the exact-model fixture: requested `opus`, returned `claude-sonnet-5-5`. Confirm the billing event/projected row uses the returned id, keeps the requested alias distinct, and prices by exact catalog key.
3. Check missing, malformed, conflicting and multi-model fixtures plus a non-Claude control; no guessed model mapping or configuration mutation occurs.

### Expected evidence
- The mocked CLI→usage→billing→projection→price path passes and names the actual model when distinct.
- An unlisted exact model remains unpriced and still named; absent or ambiguous evidence retains existing configured-name behavior.
- Unknown prices are not an invoice or subscription-charge claim.

### Pass / Fail
Pass only when all pinned regressions pass. Fail on alias-based guessed pricing, raw metadata leakage, or changed model selection.

## Behavior TT006 — own-Agent summary receipts supplement since-molt SESSION exactly once

- **id**: TT006
- **title**: own-Agent summary receipts supplement since-molt SESSION exactly once
- **guards**: `telegram-task-card-projection` § [Behavior rule 15](CONTRACT.md#behavior)
- **supersedes**: `tests/test_apriori_summary_session_cost.py` (complements hermetic regression coverage)
- **runner**: any LingTai agent with shell access to this repository
- **prerequisites**: checkout containing `tests/test_apriori_summary_session_cost.py`; repository Python environment with pytest and package dependencies; no Telegram account or provider credentials required
- **estimate**: ≈ 2 minutes

### Steps
1. From the repository root run `.venv/bin/python -m pytest -q tests/test_apriori_summary_session_cost.py` and capture its full outcome. The suite uses fake normalized responses, offline public Sonnet 4 list-price fixtures and temporary event journals, never provider/catalog network calls.
2. Inspect the fixture with one main response (1000 input, 100 output) and one helper (1000 input, 200 output, 200 cache reads, 100 established 5m writes and `cache_write_1h_tokens=0`); repeat the helper receipt and a notification carrier.
3. Inspect the actual Telegram manager live-append/rehydrate comparison, missing/malformed counts, missing receipt outcomes, missing write-TTL evidence (still partial after a receipt closes the coverage gap), unknown price/tier and molt/stale-generation cases.

### Expected evidence
- [ ] The full focused suite passes without live provider/network/daemon activity.
- [ ] SESSION reports 2 calls, 2000 input, 300 output, 200 cached, cache miss 1800 and cache rate .1, with no duplicate charges from receipt replay or carriers.
- [ ] At public USD/million prices 3 input, 15 output, .30 reads and 3.75 writes, Cost remains the single existing row: `total ~$0.0100 · in $0.0051 · write $0.0004 · read <$0.0001 · out $0.0045` (estimate, not invoice proof).
- [ ] Parent context remains 1000 of 200000 (.005); parent snapshot/index, TPS/stream timing, Δ and per-round cache/input/output facts are unchanged.
- [ ] Molt resets counts and cost; daemon/other-run/wrong-generation receipts do not count. Missing receipt/count/price evidence stays unknown or partial, never fabricated `$0`; requested-tier and stale-price qualifications retain their existing meaning.

### Pass / Fail
Pass only with the passing suite and all expected evidence. Fail on a changed layout/symbol/subtotal, lifetime or child spend entering SESSION, duplicate billing, overwritten parent-round metadata, unknown prices becoming zero, or a live/network side effect.
