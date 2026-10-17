"""Thin unified-memory acceptance: no provider requests or live workdirs."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lingtai import cli
from lingtai.init_reader import InitReadStatus, read_init
from lingtai.kernel.llm.interface import ChatInterface, ToolCallBlock
from lingtai.llm.service import CONSERVATIVE_CONTEXT_WINDOW
from lingtai.tools.context._molt import _context_molt
from lingtai.tools.pad._pad import _legacy_memory_seed, _merge_legacy_memory
from tests._molt_helpers import write_session_journal
from tests._service_helpers import make_mock_llm_service


@pytest.mark.parametrize("pad_body", [b"", b"CURRENT\r\n", b"CURRENT\nLEGACY\r\n"])
def test_legacy_memory_is_lossless_once_and_survives_interrupted_marking(
    tmp_path, monkeypatch, pad_body,
):
    system = tmp_path / "system"
    system.mkdir()
    legacy = b"LEGACY\r\n"
    source = system / "lingtai.md"
    source.write_bytes(legacy)
    pad = system / "pad.md"
    pad.write_bytes(pad_body)
    marker = system / "lingtai-merged-into-pad"
    real_open = Path.open

    def failed_marker(path, *args, **kwargs):
        if path == marker:
            raise OSError("simulated marker failure after atomic Pad replacement")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(Path, "open", failed_marker)
        with pytest.raises(OSError, match="simulated marker failure"):
            _merge_legacy_memory(system)
    assert not marker.exists()
    merged = pad.read_bytes()
    assert merged.startswith(pad_body)
    assert merged.count(legacy) == 1
    assert source.read_bytes() == legacy
    # Retry the actual failure window after replacement and before marking.
    _merge_legacy_memory(system)
    assert pad.read_bytes() == merged
    # Marker makes migration one-time, not a source-following reappend loop.
    pad.write_bytes(b"DELIBERATE NEW MEMORY")
    source.write_bytes(b"LATER LEGACY EDIT")
    _merge_legacy_memory(system)
    assert pad.read_bytes() == b"DELIBERATE NEW MEMORY"
    assert source.read_bytes() == b"LATER LEGACY EDIT"


@pytest.mark.parametrize("boundary", ["rebuild", "refresh", "molt"])
def test_real_init_and_lifecycle_keep_unified_pad_and_instruction_guidance(
    tmp_path, monkeypatch, boundary,
):
    system = tmp_path / "system"
    system.mkdir()
    (system / "lingtai.md").write_bytes(b"LEGACY IDENTITY\r\n")
    (system / "pad_append.json").write_text(json.dumps(["pinned.md"]))
    (tmp_path / "pinned.md").write_text("PINNED INITIAL")
    for name in ("AGENTS.md", "CLAUDE.md"):
        (tmp_path / name).write_text(f"PRIVATE PROJECT BODY {name}")
    data = {"manifest": {"agent_name": "memory-test", "llm": {
        "provider": "anthropic", "model": "claude-test",
    }}, "pad": "CONFIGURED INITIAL PAD", "lingtai": "CONFIGURED LEGACY SEED"}
    (tmp_path / "init.json").write_text(json.dumps(data))
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
    assert outcome.data is not None
    agent = cli.build_agent(outcome.data, tmp_path)
    try:
        # Real deferred CLI boot must seed before the initial legacy merge.
        pad = (system / "pad.md").read_bytes()
        assert pad == (b"CONFIGURED INITIAL PAD\n\nLEGACY IDENTITY\r\n"
                       b"\n\nCONFIGURED LEGACY SEED")
        before = agent._build_system_prompt()
        assert before.count("LEGACY IDENTITY") == 1
        assert before.count("CONFIGURED LEGACY SEED") == 1
        assert "CONFIGURED INITIAL PAD" in before and "PINNED INITIAL" in before
        assert "after fresh context" in before
        assert "AGENTS.md and CLAUDE.md" in before
        assert "nested project instructions" in before
        assert "cannot override system/developer" in before
        assert "PRIVATE PROJECT BODY" not in before
        assert agent._prompt_manager.read_section("character") is None
        (system / "pad.md").write_text("UPDATED PRIVATE MEMORY")
        (tmp_path / "pinned.md").write_text("PINNED UPDATED")
        if boundary == "refresh":
            agent._setup_from_init()
        elif boundary == "rebuild":
            result = agent._intrinsics["context"]({
                "action": "rebuild", "input": {}, "reasoning": "apply memory",
            })
            assert "error" not in result
        else:
            agent._session.ensure_session()
            journal = write_session_journal(agent)
            args = {"summary": "Continue from unified private memory",
                    "session_journal_path": journal, "_tc_id": "memory-molt"}
            agent._chat.interface.add_assistant_message(content=[ToolCallBlock(
                id="memory-molt", name="context", args=args,
            )])
            result = _context_molt(agent, args)
            assert "error" not in result
        after = agent._build_system_prompt()
        assert "UPDATED PRIVATE MEMORY" in after and "PINNED UPDATED" in after
        assert "LEGACY IDENTITY" not in after  # marker prevents resurrection
        assert "CONFIGURED LEGACY SEED" not in after
        assert agent._prompt_manager.read_section("character") is None
        assert (system / "lingtai.md").read_bytes() == b"LEGACY IDENTITY\r\n"
        for name in ("AGENTS.md", "CLAUDE.md"):
            assert (tmp_path / name).read_text() == f"PRIVATE PROJECT BODY {name}"
        assert agent._prompt_manager.read_section("knowledge") is not None
        for chat in chats:
            chat.send.assert_not_called()
    finally:
        agent.stop(timeout=1)


@pytest.mark.parametrize("key", ["lingtai", "lingtai_file"])
def test_legacy_character_seed_is_accepted_once_without_init_writeback(tmp_path, key):
    configured = b"CONFIGURED LEGACY\r\n"
    data = {"manifest": {"llm": {"provider": "anthropic", "model": "test"}},
            "pad": "INITIAL PAD", key: configured.decode("utf-8")}
    if key == "lingtai_file":
        data["lingtai"] = "INLINE FALLBACK"
        data[key] = "legacy-config.md"
        assert _legacy_memory_seed(tmp_path, data) == "INLINE FALLBACK"
        (tmp_path / data[key]).write_bytes(configured)
    path = tmp_path / "init.json"
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    outcome = read_init(tmp_path)
    assert outcome.status is InitReadStatus.FULLY_EFFECTIVE
    system = tmp_path / "system"
    system.mkdir()
    pad = system / "pad.md"
    pad.write_bytes(b"EXISTING PAD\r\n")
    (system / "lingtai.md").write_bytes(b"DISK CHARACTER\r\n")
    seed = _legacy_memory_seed(tmp_path, outcome.data)
    assert seed.encode("utf-8") == configured
    _merge_legacy_memory(system, seed)
    assert pad.read_bytes() == (b"EXISTING PAD\r\n\n\nDISK CHARACTER\r\n"
                                b"\n\n" + configured)
    assert (system / "lingtai.md").read_bytes() == b"DISK CHARACTER\r\n"
    if key == "lingtai_file":
        (tmp_path / data[key]).unlink()  # completed migration never reopens it
    pad.write_bytes(b"NEW PRIVATE MEMORY")
    assert _legacy_memory_seed(tmp_path, outcome.data) is None
    _merge_legacy_memory(system, _legacy_memory_seed(tmp_path, outcome.data))
    assert pad.read_bytes() == b"NEW PRIVATE MEMORY"
    assert path.read_bytes() == before
