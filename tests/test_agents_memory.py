"""One real startup/lifecycle smoke for unified injected memory."""
import json
from unittest.mock import MagicMock

from lingtai import cli
from lingtai.init_reader import InitReadStatus, read_init
from lingtai.kernel.llm.interface import ChatInterface, ToolCallBlock
from lingtai.llm.service import CONSERVATIVE_CONTEXT_WINDOW
from lingtai.tools.context._molt import _context_molt
from tests._molt_helpers import write_session_journal
from tests._service_helpers import make_mock_llm_service


def test_real_init_and_lifecycle_keep_unified_pad_and_instruction_guidance(
    tmp_path, monkeypatch,
):
    system = tmp_path / "system"
    system.mkdir()
    legacy = system / "lingtai.md"
    legacy.write_bytes(b"LEGACY IDENTITY\r\n")
    instructions = tmp_path / "AGENTS.md"
    instructions.write_text("PRIVATE PROJECT BODY")
    data = {"manifest": {"agent_name": "memory-test", "llm": {
        "provider": "anthropic", "model": "claude-test",
    }}, "pad": "INITIAL PAD", "lingtai": "CONFIGURED LEGACY"}
    init = tmp_path / "init.json"
    init.write_text(json.dumps(data))
    original_init = init.read_bytes()
    service = make_mock_llm_service()
    service._base_url = None
    service._context_window = CONSERVATIVE_CONTEXT_WINDOW
    service._provider_defaults = {"anthropic": {"max_rpm": 60}}
    chats = []

    def new_chat(*_args, **_kwargs):
        chat = MagicMock(interface=ChatInterface())
        chats.append(chat)
        return chat

    service.create_session.side_effect = new_chat
    monkeypatch.setattr(cli, "build_llm_service", lambda *_a, **_kw: service)
    outcome = read_init(tmp_path)
    assert outcome.status is InitReadStatus.FULLY_EFFECTIVE
    agent = cli.build_agent(outcome.data, tmp_path)
    try:
        pad = system / "pad.md"
        assert pad.read_bytes() == (
            b"INITIAL PAD\n\nLEGACY IDENTITY\r\n\n\nCONFIGURED LEGACY"
        )
        prompt = agent._build_system_prompt()
        assert "INITIAL PAD" in prompt and "LEGACY IDENTITY" in prompt
        assert "AGENTS.md and CLAUDE.md" in prompt
        assert "PRIVATE PROJECT BODY" not in prompt
        instructions_body = agent._prompt_manager.read_instructions()
        assert "anticipated long, bulky" in instructions_body
        assert "expected short results" in instructions_body
        assert "CLEAR retention targets" in instructions_body
        assert agent._prompt_manager.read_section("character") is None
        pad.write_text("UPDATED PRIVATE MEMORY")
        for boundary in ("rebuild", "refresh", "molt"):
            if boundary == "rebuild":
                result = agent._intrinsics["context"]({
                    "action": "rebuild", "input": {}, "reasoning": "apply memory",
                })
                assert "error" not in result
            elif boundary == "refresh":
                agent._setup_from_init()
            else:
                agent._session.ensure_session()
                args = {"summary": "Continue from private memory",
                        "session_journal_path": write_session_journal(agent),
                        "_tc_id": "memory-molt"}
                agent._chat.interface.add_assistant_message(content=[ToolCallBlock(
                    id="memory-molt", name="context", args=args,
                )])
                assert "error" not in _context_molt(agent, args)
            prompt = agent._build_system_prompt()
            assert "UPDATED PRIVATE MEMORY" in prompt
            assert "LEGACY IDENTITY" not in prompt
            assert "CONFIGURED LEGACY" not in prompt
        assert legacy.read_bytes() == b"LEGACY IDENTITY\r\n"
        assert init.read_bytes() == original_init
        assert instructions.read_text() == "PRIVATE PROJECT BODY"
        for chat in chats:
            chat.send.assert_not_called()
    finally:
        agent.stop(timeout=1)
