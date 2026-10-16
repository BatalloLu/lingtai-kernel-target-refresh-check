---
name: email-manual-notifications-and-delivery
description: >
  Focused Email reference for daemon delivery, heartbeat/liveness, bounce
  recovery, unread payloads, persistent bodies, overflow, and read-state refresh.
  Read when delivery or notices need diagnosis.
version: 1.0.0
tags: [lingtai, email, notifications, delivery, recovery]
last_changed_at: "2026-09-09T10:17:00Z"
related_files:
- src/lingtai/tools/email/manual/SKILL.md
- src/lingtai/tools/email/manual/reference/actions-and-storage/SKILL.md
- src/lingtai/tools/email/manager.py
- src/lingtai/tools/email/primitives.py
- src/lingtai/adapters/posix/mail.py
- src/lingtai/tools/email/CONTRACT.md
maintenance: |
  Tracks Email delivery, unread notification projection, bounce recovery, and read-state mirror semantics; update when producer or mail-adapter behavior changes.
---

# Email notifications and delivery

## Delivery, liveness, and recovery

`send` writes each recipient's outbox entry, then starts that recipient's daemon
`_mailman` thread before that call's unified sent record is written. Even `delay=0`
can return `sent` before delivery finishes. A later thread-start or persistence
failure can leave earlier deliveries; neither a failed call nor a missing sent
record proves zero effect. Delay waits in a daemon thread: this is not a restart-resilient queue.
A process exit can strand outbox files; no automatic replay is promised.

Non-self POSIX targets need `.agent.json` presence and a Core-fresh
`.agent.heartbeat`; use current kernel liveness policy, not a fixed Email timeout.
Core currently counts even malformed manifests as present; a valid manifest with
missing/null `admin` identifies a human and bypasses heartbeat checks. This is
implementation truth, not permission to deliver to an unverified owner. Self-send
bypasses this transport handshake. Refresh/relaunch windows can produce
`not running`; refused attempts are not queued for a later retry. Failures publish
`email.bounce` in `.notification/system.json`.

A process may appear in `ps` before a fresh heartbeat. If a CPR attempt exits
because the duplicate-process guard sees the existing same-workdir process, do not
stack CPR attempts: wait for a heartbeat. Any lifecycle intervention needs its
own authorization and diagnosis, not just a bounce. A non-self absolute-path
target has the same handshake.

For a known POSIX pre-publication refusal (unknown/dead recipient or rejected
attachment), no entry was published for that target. A generic bounce is not a
universal zero-effect receipt: custom adapters or post-publication exceptions can
fail after an effect, and other fan-out targets may already have received mail.
Inspect the exact failure and recipient state; retry once only when a safe
pre-delivery refusal is established and the cause is corrected. Never guess a
replacement address or replay the whole fan-out blindly.

## Unread producer mirror

Arrival and every read-state mutation render the current unread set to
`.notification/email.json`; the next heartbeat exposes it through
`notification(action="check")`. Its relevant shape is:

```json
{"instructions":"delivered once; act with email.read/reply/dismiss",
 "data":{"count":3,"newest_received_at":"<time>",
         "email_ids":["<local-id>"],
         "emails":[{"id":"<local-id>","from":"/abs/path/to/peer",
                    "subject":"...","message":"full body",
                    "message_chars":10,"message_truncated":false}]}}
```

The attention lane carries IDs; structured entries live in
`_meta.agent_meta.notifications.persistent.email`. The send layer rejects bodies
over 50,000 characters. The shared persistent envelope has a 10,000-character
hard ceiling (possibly configured lower), so even accepted new messages can be
truncated. The producer selects at most 10 newest unread entries per round.

## Handling and overflow

After a complete body successfully enters model context, Email automatically
marks that ID read and renders the next bounded unread batch. Constructing or
rerendering the mirror alone never marks mail read. Delivery means context
canonical insertion after the send/commit settles, not mere carrier preparation,
a successful provider response, or completion of the mail's task.
Explicit `read`, `dismiss`, `archive`, `delete`, and reply behavior is unchanged.
Use `read` for source metadata, attachments, or missing full bodies; use `dismiss`
only when deliberately handling a still-unread message without another body copy.
Replies currently leave the source unread; see the
[Contract discrepancy and explicit-dismiss workaround](../addressing-and-replies/SKILL.md#same-channel-reply).

Truncated, ID-only, omitted and spill-only records remain unread. Overflow can
come from one long mail, a batch of otherwise short mails, or other lanes. Use
explicit `email.read` to recover the complete source body (or follow the spill
locator when appropriate). One-shot delivery may suppress unchanged records;
automatic retries, chunking and source reads are not provided. Large unread mail
can occupy the newest-entry window until explicitly handled. This change does
not change delivery, the notification cap or the 50,000-character send limit.
There is no notification dismiss action; read-state belongs to Email.
