"""Read state follows complete context delivery, not mirror construction."""
from copy import deepcopy
from types import SimpleNamespace
import threading

import pytest

from lingtai.kernel.llm.interface import ChatInterface, ToolCallBlock, ToolResultBlock
from lingtai.kernel.meta_block import attach_active_notifications, record_notification_persistent_delivery
from lingtai.kernel.base_agent import turn
from lingtai.kernel.state import AgentState
from lingtai.tools.email import primitives as mail
from tests.test_tool_family_email_migration import _agent, _seed_inbox


def make_agent(tmp_path, count):
    agent = _agent(tmp_path)
    agent._chat = SimpleNamespace(interface=ChatInterface())
    for n in range(count):
        _seed_inbox(agent, f"mail-{n:03d}", message=f"body-{n}",
                    received_at=f"2026-10-16T00:00:{n:02d}Z")
    mail._rerender_unread_digest(agent)
    return agent


def deliver(agent, *, check=False):
    target = ToolResultBlock(id=f"test-{len(agent._chat.interface.entries)}", name="notification" if check else "test",
                             content={"_notification_placeholder": True} if check else {})
    before = mail._read_ids(agent)
    attach_active_notifications(agent, [target])
    assert mail._read_ids(agent) == before  # staging never acknowledges
    agent._chat.interface.add_assistant_message([ToolCallBlock(target.id, target.name, {})])
    agent._chat.interface.add_tool_results([target])
    turn._acknowledge_committed_email_notifications(agent, [target])
    return target.metadata.get("agent_meta", {}).get("notifications", {}).get("persistent", {})


@pytest.mark.parametrize("route", ["active", "idle"])
def test_bounded_multiround_drain_preserves_bodies(tmp_path, route):
    agent = make_agent(tmp_path, 23)
    original = {p: p.read_bytes() for p in (agent._working_dir / "mailbox/inbox").glob("*/message.json")}
    assert not mail._read_ids(agent)  # rendering is not delivery
    for total in (10, 20, 23):
        if route == "active":
            deliver(agent)
        else:
            agent._state = AgentState.IDLE
            agent._sync_notifications()
        assert len(mail._read_ids(agent)) == total
    assert all(p.read_bytes() == content for p, content in original.items())
    assert not (agent._working_dir / ".notification/email.json").exists()


def test_no_carrier_or_failed_append_does_not_ack(tmp_path, monkeypatch):
    agent = make_agent(tmp_path, 2)
    attach_active_notifications(agent, [])
    assert not mail._read_ids(agent)
    def fail(*args, **kwargs):
        raise OSError("fixture append failure")
    monkeypatch.setattr(agent._chat.interface, "add_tool_results", fail)
    import json
    payload = json.loads((agent._working_dir / ".notification/email.json").read_text())
    with pytest.raises(OSError, match="fixture append failure"):
        agent._inject_notification_pair({"email": payload})
    assert not mail._read_ids(agent)


def test_exact_snapshot_and_duplicate_receipt(tmp_path, monkeypatch):
    agent = make_agent(tmp_path, 1)
    records, ids = mail._unread_notification_context(agent)
    _seed_inbox(agent, "late", message="arrived after snapshot")
    saves = []
    real = mail._save_read_ids
    def save(agent, ids):
        saves.append(set(ids))
        real(agent, ids)
    monkeypatch.setattr(mail, "_save_read_ids", save)
    payload = {"notification_persistent": {"email": {"emails": records, "email_ids": ids}}}
    for _ in range(2):
        record_notification_persistent_delivery(agent, payload, tool_call_id="test")
    assert mail._read_ids(agent) == set(ids)
    assert len(saves) == 1


@pytest.mark.parametrize("change", [
    {"message_truncated": True}, {"message": ""}, {"message_chars": 999},
    {"preview_truncated": True}, {"message_truncated": None},
])
def test_incomplete_records_remain_unread(tmp_path, change):
    agent = make_agent(tmp_path, 1)
    records, ids = mail._unread_notification_context(agent)
    records[0].update(change)
    mail._acknowledge_notification_delivery(agent, {"emails": records, "email_ids": ids})
    assert not mail._read_ids(agent)


def test_write_failure_preserves_context_and_unread(tmp_path, monkeypatch):
    agent = make_agent(tmp_path, 1)
    def fail(*args):
        raise OSError("fixture read ledger failure")
    monkeypatch.setattr(mail, "_save_read_ids", fail)
    persistent = deliver(agent)
    assert persistent["email"]["emails"][0]["message"] == "body-0"
    assert not mail._read_ids(agent)


def test_long_mail_stays_unread_across_three_capped_deliveries(tmp_path, monkeypatch):
    monkeypatch.delenv("LINGTAI_NOTIFICATION_MAX_CHARS", raising=False)
    agent = make_agent(tmp_path, 0)
    _seed_inbox(agent, "long", message="x" * 12000)
    mail._rerender_unread_digest(agent)
    for _ in range(3):
        persistent = deliver(agent, check=True)
        item = persistent["email"]["emails"][0]
        assert persistent["overflow"]
        assert item["message_truncated"] is True
        assert len(item["message"]) < 12000
        assert not mail._read_ids(agent)
    result = agent._email_manager.handle({"action": "read", "email_id": ["long"]})
    assert result["emails"][0]["message"] == "x" * 12000
    assert mail._read_ids(agent) == {"long"}


def test_real_agent_builds_prompt_and_delivers_email(tmp_path):
    from lingtai.agent import Agent
    from tests.test_psyche_prompt_settings import _agent as real_agent
    agent = real_agent(tmp_path)
    assert isinstance(agent, Agent)
    prompt = agent._build_system_prompt()
    assert isinstance(prompt, str) and prompt
    assert "email" in prompt.lower()
    agent._chat = SimpleNamespace(interface=ChatInterface())
    _seed_inbox(agent, "startup", message="startup body")
    mail._rerender_unread_digest(agent)
    assert deliver(agent)["email"]["emails"][0]["message"] == "startup body"
    assert mail._read_ids(agent) == {"startup"}


@pytest.mark.parametrize("mode", ["staged", "rollback", "copy", "capped_copy", "poisoned"])
def test_ack_requires_actual_settled_canonical_payload(tmp_path, mode):
    agent = make_agent(tmp_path, 1)
    target = ToolResultBlock("unique", "test", {})
    attach_active_notifications(agent, [target])
    assert not mail._read_ids(agent)
    iface = agent._chat.interface
    if mode != "staged":
        iface.add_assistant_message([ToolCallBlock("unique", "test", {})])
        canonical = deepcopy(target)
        if mode == "capped_copy":
            canonical.metadata["agent_meta"]["notifications"]["persistent"]["email"]["emails"][0]["message_truncated"] = True
        iface.add_tool_results([canonical])
        if mode == "rollback":
            iface.drop_trailing(lambda entry: entry.role == "user")
        if mode == "poisoned":
            agent._llm_worker_interface_poisoned = True
    turn._acknowledge_committed_email_notifications(agent, [target])
    assert mail._read_ids(agent) == ({"mail-000"} if mode == "copy" else set())


@pytest.mark.parametrize("route", ["success", "intercept", "cancel", "backoff", "restore", "survivor", "commit_failure"])
def test_real_turn_settle_points_ack_only_after_commit(tmp_path, monkeypatch, route):
    from lingtai.kernel.llm.base import LLMResponse, ToolCall
    from tests.test_tool_result_restore_after_continuation_failure import (
        _FakeChat, _ProcessExecutor, _NoopSentTracker,
    )
    agent = make_agent(tmp_path, 1)
    agent._chat = _FakeChat()
    target = ToolResultBlock("call_1", "bash", "fixture result")
    agent._executor = _ProcessExecutor(target)
    agent._cancel_event = threading.Event()
    agent._on_tool_result_hook = None
    agent._intermediate_text_streamed = True
    agent._sent_tracker = _NoopSentTracker()
    monkeypatch.setattr(agent, "_save_chat_history", lambda **kw: None)
    monkeypatch.setattr(turn, "_turn_boundary_housekeeping", lambda a: None)
    real_commit = agent._chat.commit_tool_results
    commits = []
    def commit(results):
        assert not mail._read_ids(agent)  # catch pre-commit regression
        if route == "commit_failure":
            raise OSError("fixture commit failure")
        real_commit(deepcopy(results))
        commits.append(True)
    agent._chat.commit_tool_results = commit
    def execute(calls, **kw):
        if route == "cancel":
            agent._cancel_event.set()
        return [target], route in ("intercept", "commit_failure"), "intercepted"
    agent._executor.execute = execute
    monkeypatch.setattr(turn, "_check_poll_backoff", lambda *args: route == "backoff")
    def send(results):
        assert not mail._read_ids(agent)
        agent._chat.commit_tool_results(results)
        if route == "restore":
            agent._chat.interface.drop_trailing(lambda entry: entry.role == "user")
        if route in ("restore", "survivor"):
            raise RuntimeError("fixture provider failure")
        return LLMResponse(text="done", tool_calls=[])
    monkeypatch.setattr(agent._session, "send", send)
    response = LLMResponse(text="", tool_calls=[ToolCall(id="call_1", name="bash", args={})])
    if route in ("restore", "survivor", "commit_failure"):
        with pytest.raises((RuntimeError, OSError), match="fixture"):
            turn._process_response(agent, response, ledger_source="test")
    else:
        turn._process_response(agent, response, ledger_source="test")
    assert mail._read_ids(agent) == (set() if route == "commit_failure" else {"mail-000"})
    assert len(commits) == (0 if route == "commit_failure" else 2 if route == "restore" else 1)


def test_one_batch_is_bounded_and_preserves_concurrent_explicit_reads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    agent = make_agent(tmp_path, 23)
    records, ids = mail._unread_notification_context(agent, max_entries=23)
    barrier = threading.Barrier(2)
    def auto():
        barrier.wait(timeout=5)
        mail._acknowledge_notification_delivery(agent, {"emails": records})
    def explicit():
        barrier.wait(timeout=5)
        mail._mark_read(agent, ids[-1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(auto), pool.submit(explicit)]
        for future in futures:
            future.result(timeout=5)
    assert mail._read_ids(agent) == set(ids[:10]) | {ids[-1]}
