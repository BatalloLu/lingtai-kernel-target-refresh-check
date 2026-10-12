"""Modern notification wake drives the existing canonical wire, never a queue."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from lingtai.kernel.base_agent.turn import _handle_tc_wake
from lingtai.kernel.llm.interface import ChatInterface, TextBlock, ToolCallBlock, ToolResultBlock


def test_tc_wake_worker_still_running_does_not_touch_iface_in_except(tmp_path):
    """When the wire-drive send() raises WorkerStillRunningError, the
    except path must re-raise WITHOUT re-inspecting/healing/saving the
    poisoned interface. The run loop's central branch owns poisoning and
    refresh — touching the interface here could race the live worker."""
    from lingtai.kernel.llm_utils import WorkerStillRunningError
    from lingtai.kernel.message import Message, MSG_TC_WAKE

    iface = ChatInterface()
    iface.add_assistant_message([
        ToolCallBlock(id="notif_call", name="system", args={"action": "notification"})
    ])
    iface.add_tool_results([
        ToolResultBlock(id="notif_call", name="system", content={"status": "ok"})
    ])

    pending_checks = {"count": 0}

    def has_pending_once():
        pending_checks["count"] += 1
        if pending_checks["count"] > 1:
            raise AssertionError("exception path must not inspect poisoned interface")
        return False

    iface.has_pending_tool_calls = has_pending_once

    @dataclass
    class _ChatHolder:
        interface: ChatInterface

    @dataclass
    class _Session:
        chat: _ChatHolder

        def ensure_session(self):
            return self.chat

        def send(self, payload):
            assert payload is None
            raise WorkerStillRunningError(elapsed=300.0, grace=5.0, agent_name="test")

    @dataclass
    class _Agent:
        _chat: _ChatHolder
        _session: _Session
        _intrinsics: dict = field(default_factory=dict)
        _tool_handlers: dict = field(default_factory=dict)
        _PARALLEL_SAFE_TOOLS: set = field(default_factory=set)
        _working_dir: Any = tmp_path
        _logs: list[tuple[str, dict]] = field(default_factory=list)
        saves: int = 0

        class _ConfigStub:
            provider = "openai"
            language = "en"

        _config = _ConfigStub()

        class _ServiceStub:
            def make_tool_result(self, name, result, **kw):
                return ToolResultBlock(
                    id=kw.get("tool_call_id") or "",
                    name=name,
                    content=result,
                )

        service = _ServiceStub()

        def _dispatch_tool(self, _call):
            return {"status": "ok"}

        def _log(self, event_type, **fields):
            self._logs.append((event_type, fields))

        def _save_chat_history(self, *, ledger_source=None):
            self.saves += 1

    chat = _ChatHolder(iface)
    agent = _Agent(_chat=chat, _session=_Session(chat))
    wake_msg = Message(type=MSG_TC_WAKE, sender="kernel", content="", timestamp=0.0)

    with pytest.raises(WorkerStillRunningError):
        _handle_tc_wake(agent, wake_msg)

    assert pending_checks["count"] == 1
    assert agent.saves == 0
    assert any(
        event == "tc_wake_error" and fields.get("worker_still_running") is True
        for event, fields in agent._logs
    )


def _modern_agent(tmp_path, monkeypatch):
    """Use the existing real BaseAgent sync harness, with a recording LLM Port."""
    from types import SimpleNamespace
    from lingtai.kernel.base_agent import turn
    from tests.test_notification_sync import _make_stub_agent_for_block_log

    agent = _make_stub_agent_for_block_log(tmp_path)
    agent._session = SimpleNamespace()
    agent.saves = []
    agent._save_chat_history = lambda **kw: agent.saves.append(kw)
    # This slice tests synchronization -> wake, not executor/tool dispatch.
    monkeypatch.setattr(turn, "_make_tool_executor", lambda a, g: None)
    return agent


def test_sync_pair_drives_once_without_appending_or_replaying(tmp_path, monkeypatch):
    import copy
    from lingtai.kernel.base_agent import turn
    from lingtai.kernel.llm.base import LLMResponse
    from lingtai.kernel.message import MSG_TC_WAKE
    from tests._notification_store_helpers import publish_test_payload

    agent = _modern_agent(tmp_path, monkeypatch)
    publish_test_payload(tmp_path, "email", {"header": "mail", "data": {"count": 1}})
    producer = tmp_path / ".notification" / "email.json"
    before_bytes = producer.read_bytes()
    agent._sync_notifications()
    msg = agent.inbox.get_nowait()
    assert msg.type == MSG_TC_WAKE
    before_wire = copy.deepcopy(agent._chat.interface.to_dict())
    assert len(agent._chat.interface.entries) == 2
    assert not hasattr(agent, "_tc_inbox")
    response = LLMResponse(text="noticed")
    sends, processed, housekeeping = [], [], []

    def send(payload):
        sends.append(payload)
        assert agent._chat.interface.to_dict() == before_wire
        return response

    agent._session.send = send
    monkeypatch.setattr(turn, "_process_response", lambda a, r, **kw: processed.append((r, kw)))
    monkeypatch.setattr(turn, "_turn_boundary_housekeeping", lambda a: housekeeping.append(a))
    turn._handle_tc_wake(agent, msg)
    assert sends == [None]
    assert processed == [(response, {"ledger_source": "tc_wake"})]
    assert housekeeping == [agent]
    assert agent.saves[-1] == {"ledger_source": "tc_wake"}
    assert agent._llm_worker_turn_request_persisted is True
    agent._sync_notifications()
    assert agent.inbox.empty(), "the unchanged delivered event must not wake again"
    assert agent._chat.interface.to_dict() == before_wire
    assert producer.read_bytes() == before_bytes


def test_wire_send_failure_preserves_real_notification_pair(tmp_path, monkeypatch):
    import copy
    from lingtai.kernel.base_agent import turn
    from tests._notification_store_helpers import publish_test_payload

    agent = _modern_agent(tmp_path, monkeypatch)
    publish_test_payload(tmp_path, "cron", {"header": "real notification payload"})
    agent._sync_notifications()
    msg = agent.inbox.get_nowait()
    before = copy.deepcopy(agent._chat.interface.to_dict())
    producer = tmp_path / ".notification" / "cron.json"
    producer_bytes = producer.read_bytes()

    def fail(payload):
        assert payload is None
        raise RuntimeError("provider failed")

    agent._session.send = fail
    with pytest.raises(RuntimeError, match="provider failed"):
        turn._handle_tc_wake(agent, msg)
    assert agent._chat.interface.to_dict() == before
    assert not agent._chat.interface.has_pending_tool_calls()
    assert producer.read_bytes() == producer_bytes
    assert agent.saves == [{"ledger_source": "notification_sync"}], "only the initial sync persisted the pair"


@pytest.mark.parametrize("tail", ["empty", "assistant", "pending"])
def test_stale_or_pending_wake_does_not_call_provider(tmp_path, monkeypatch, tail):
    from lingtai.kernel.base_agent import turn
    from lingtai.kernel.message import MSG_TC_WAKE, _make_message

    agent = _modern_agent(tmp_path, monkeypatch)
    iface = agent._chat.interface
    if tail == "assistant":
        iface.add_assistant_message([TextBlock(text="already answered")])
    elif tail == "pending":
        iface.add_assistant_message([ToolCallBlock(id="pending", name="x", args={})])
    before = iface.to_dict()
    agent._session.send = lambda _: pytest.fail("stale/pending wake reached provider")
    turn._handle_tc_wake(agent, _make_message(MSG_TC_WAKE, "kernel", ""))
    assert iface.to_dict() == before
    reason = "pending_tool_calls" if tail == "pending" else "wire_not_ready"
    assert any(event == "tc_wake_noop" and fields.get("reason") == reason
               for event, fields in agent._logs)


def test_poisoned_wake_returns_before_chat_access(tmp_path, monkeypatch):
    from lingtai.kernel.base_agent import turn, worker_recovery
    from lingtai.kernel.message import MSG_TC_WAKE, _make_message

    class Poisoned:
        _llm_worker_interface_poisoned = True
        _llm_worker_poison_artifact = "history/unfinished_turns/test.json"
        _log = lambda *a, **kw: None

        @property
        def _chat(self):
            pytest.fail("poison guard touched unsafe chat")

    refresh = []
    monkeypatch.setattr(worker_recovery, "request_worker_hang_refresh", lambda *a, **kw: refresh.append(kw))
    turn._handle_tc_wake(Poisoned(), _make_message(MSG_TC_WAKE, "kernel", ""))
    assert refresh == [{"artifact_relpath": Poisoned._llm_worker_poison_artifact,
                        "source": "tc_wake_poison_guard"}]


@pytest.mark.parametrize("fails", [False, True])
def test_wake_ensures_missing_chat_inline(tmp_path, monkeypatch, fails):
    from lingtai.kernel.base_agent import turn
    from tests._notification_store_helpers import publish_test_payload

    agent = _modern_agent(tmp_path, monkeypatch)
    publish_test_payload(tmp_path, "cron", {"header": "ready"})
    agent._sync_notifications()
    msg = agent.inbox.get_nowait()
    chat = agent._chat_stub
    before = chat.interface.to_dict()
    agent._chat_stub = None
    ensures, sends = [], []

    def ensure():
        ensures.append(True)
        if fails:
            raise RuntimeError("session unavailable")
        agent._chat_stub = chat

    def send(payload):
        sends.append(payload)
        raise RuntimeError("stop after ensure")

    agent._session.ensure_session = ensure
    agent._session.send = send
    if fails:
        turn._handle_tc_wake(agent, msg)
        assert sends == [] and agent._chat_stub is None
        assert any(event == "tc_wake_noop" and fields.get("reason") == "ensure_session_failed"
                   for event, fields in agent._logs)
    else:
        with pytest.raises(RuntimeError, match="stop after ensure"):
            turn._handle_tc_wake(agent, msg)
        assert sends == [None] and agent._chat_stub is chat
    assert ensures == [True]
    assert chat.interface.to_dict() == before
