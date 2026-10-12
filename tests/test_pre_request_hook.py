"""Generic ChatSession pre-request hooks remain supported after TCInbox retirement."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lingtai.kernel.llm.base import ChatSession
from lingtai.kernel.llm.interface import ChatInterface, ToolCallBlock, ToolResultBlock


class TestPreRequestHookABC:
    """The ChatSession ABC declares pre_request_hook with a None default."""

    def test_default_is_none(self):
        # Subclass that satisfies the abstract methods with no-ops.
        class _DummySession(ChatSession):
            @property
            def interface(self):
                return ChatInterface()

            def send(self, message):
                from lingtai.kernel.llm.base import LLMResponse
                return LLMResponse()

        s = _DummySession()
        assert s.pre_request_hook is None

    def test_can_assign_callable(self):
        class _DummySession(ChatSession):
            @property
            def interface(self):
                return ChatInterface()

            def send(self, message):
                from lingtai.kernel.llm.base import LLMResponse
                return LLMResponse()

        s = _DummySession()
        called = []
        s.pre_request_hook = lambda iface: called.append(iface)
        s.pre_request_hook(s.interface)
        assert len(called) == 1


# ---------------------------------------------------------------------------
# 2. Anthropic adapter wiring (canonical-interface case)
# ---------------------------------------------------------------------------


class TestAnthropicAdapterHook:
    """The Anthropic adapter calls the hook at the right place: after
    commit_to_interface but before the API call."""

    def test_hook_fires_after_commit_before_api_call(self):
        """When pre_request_hook is set and send(tool_results) is called,
        the hook must observe the interface AFTER add_tool_results lands
        but BEFORE the API call would mutate state.
        """
        from lingtai.llm.anthropic.adapter import AnthropicChatSession

        # Mock client whose messages.create raises so we can inspect
        # the interface state at hook-fire time without needing a real
        # LLM. The hook fires before this raises.
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("api blocked for test")

        iface = ChatInterface()
        # Seed: assistant emitted a tool_call, agent is about to reply
        # with the tool_result. This is mid-tool-loop state.
        call_id = "toolu_test"
        iface.add_user_message("start")
        iface.add_assistant_message(
            [ToolCallBlock(id=call_id, name="bash", args={"cmd": "ls"})],
        )

        session = AnthropicChatSession(
            client=client,
            model="claude-3-5-sonnet",
            system_prompt="",
            interface=iface,
            tools=None,
            tool_choice=None,
            extra_kwargs={},
        )

        observed = {}

        def hook(captured_iface):
            # At hook fire time: tool_results just committed; tail must
            # be user[tool_result] with no pending tool_calls.
            observed["tail_role"] = captured_iface.entries[-1].role
            observed["tail_blocks"] = [type(b).__name__ for b in captured_iface.entries[-1].content]
            observed["has_pending"] = captured_iface.has_pending_tool_calls()

        session.pre_request_hook = hook

        # Send tool_results
        with pytest.raises(RuntimeError, match="api blocked"):
            session.send([
                ToolResultBlock(id=call_id, name="bash", content="result"),
            ])

        assert observed["tail_role"] == "user"
        assert "ToolResultBlock" in observed["tail_blocks"]
        assert observed["has_pending"] is False, (
            "wire must be at safe boundary when hook fires"
        )

    def test_hook_fires_for_str_send(self):
        """Hook fires even on text-message sends, not just tool_results."""
        from lingtai.llm.anthropic.adapter import AnthropicChatSession

        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("api blocked")

        session = AnthropicChatSession(
            client=client,
            model="claude-3-5-sonnet",
            system_prompt="",
            interface=ChatInterface(),
            tools=None,
            tool_choice=None,
            extra_kwargs={},
        )
        observed = []
        session.pre_request_hook = lambda iface: observed.append("fired")

        with pytest.raises(RuntimeError):
            session.send("hello")
        assert observed == ["fired"]

    def test_no_hook_means_no_call(self):
        """When pre_request_hook is None (default), nothing is called."""
        from lingtai.llm.anthropic.adapter import AnthropicChatSession

        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("api blocked")

        session = AnthropicChatSession(
            client=client,
            model="claude-3-5-sonnet",
            system_prompt="",
            interface=ChatInterface(),
            tools=None,
            tool_choice=None,
            extra_kwargs={},
        )
        # Don't set pre_request_hook — it stays None.

        with pytest.raises(RuntimeError):
            session.send("hello")
        # If we got here without AttributeError or TypeError on the hook
        # path, the None branch worked.
