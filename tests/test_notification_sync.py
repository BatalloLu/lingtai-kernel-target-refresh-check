"""Existing canonical sync harness retained solely for modern wake regressions."""
from __future__ import annotations

from pathlib import Path
from tests._notification_store_helpers import notification_store_for

def _make_chat_stub():
    """Minimal ChatInterface-backed chat stub for sync tests."""
    from lingtai.kernel.llm.interface import ChatInterface

    class _ChatStub:
        def __init__(self):
            self.interface = ChatInterface()

    return _ChatStub()


def _make_stub_agent_for_block_log(
    tmp_path: Path,
    *,
    notification_deferred_log_fp=None,
    asleep_evt=None,
    cancel_event=None,
):
    """Build the shared notification-sync agent, preserving optional state fields."""
    from dataclasses import dataclass, field as dc_field
    from lingtai.kernel.base_agent import BaseAgent
    from lingtai.kernel.state import AgentState

    chat = _make_chat_stub()

    class _Agent(BaseAgent):
        def __init__(self, workdir):
            self._working_dir = workdir
            self._notification_store = notification_store_for(workdir)
            self._state = AgentState.IDLE
            self._notification_fp = ()
            if notification_deferred_log_fp is not None:
                self._notification_deferred_log_fp = notification_deferred_log_fp
            self._notification_block_id = None
            self._chat_stub = chat
            self._logs: list = []
            self.agent_name = "stub"
            if asleep_evt is not None:
                self._asleep_evt = asleep_evt
            if cancel_event is not None:
                self._cancel_event = cancel_event
            import queue
            self.inbox = queue.Queue()

        @property
        def _chat(self):
            return self._chat_stub

        def _save_chat_history(self, *, ledger_source="main"):
            pass

        def _log(self, evt, **fields):
            self._logs.append((evt, fields))

        def _wake_nap(self, *_a, **_kw):
            pass

        def _set_state(self, *_a, **_kw):
            pass

        def _reset_uptime(self):
            pass

    return _Agent(tmp_path)
