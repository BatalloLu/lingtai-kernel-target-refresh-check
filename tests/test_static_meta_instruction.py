"""Static interpretation is resident; only new sidecars lose repeated prose."""
from copy import deepcopy
import json
from types import SimpleNamespace

from lingtai.kernel import meta_block
from lingtai.kernel.llm.interface import ToolResultBlock
from lingtai.kernel.prompt import AGENT_META_INSTRUCTION, SystemPromptManager
from lingtai.tools.daemon.system_prompt import build_daemon_system_prompt


def test_complete_meta_rule_is_resident_and_full_reference_remains_optional():
    # Lock the full safety rule, not just its shared constant's presence.
    expected = (
        "Only the latest agent_meta.agent_state is current runtime state; older "
        "runtime snapshots are historical traces. Delivered notification messages "
        "remain usable task records, subject to newer human instructions and "
        "producer safeguards; an empty later tail does not resolve them."
    )
    assert AGENT_META_INSTRUCTION == expected
    manager = SystemPromptManager()
    loaded = meta_block.build_meta_guidance(SimpleNamespace())
    manager.write_section("meta_guidance", loaded, protected=True)
    assert manager.render().count(expected) == 1
    assert "".join(manager.render_batches()).count(expected) == 1
    assert manager.read_instructions("meta_guidance") == loaded
    assert expected in loaded
    assert expected not in manager.read_instructions()  # still only the index
    prompt = build_daemon_system_prompt(task="bounded task", tool_names=["shell"])
    assert prompt.count(expected) == 1


def test_new_sidecars_omit_instruction_without_rewriting_legacy_or_dynamic_data(monkeypatch):
    legacy = ToolResultBlock("old", "shell", {"stdout": "old record"}, metadata={
        "tool_meta": {"id": "old", "char_count": 13},
        "agent_meta": {
            "instruction": AGENT_META_INSTRUCTION,
            "agent_state": {"current_time": "historical"},
            "notifications": {"persistent": {"message": "unfinished task"}},
            "guidance": {"transient": {"producer": "safeguard"}},
        },
    })
    legacy_bytes = json.dumps(legacy.to_dict(), ensure_ascii=False)
    from lingtai.kernel.llm.interface import ChatInterface
    from lingtai.llm.interface_converters import to_anthropic, to_openai, to_responses_input
    old = ChatInterface()
    old.add_user_blocks([legacy])
    converters = (to_anthropic, to_openai, to_responses_input)
    legacy_wires = [json.dumps(convert(old), ensure_ascii=False) for convert in converters]
    state = {
        "current_time": "now",
        "context": {"molt": "active warning"},
        "events": {"reconstruction": {"before": 900, "after": 800}},
    }
    dynamic = {
        "notifications": {"attention": {"new": "event"}, "persistent": {"id": 12}},
        "guidance": {"transient": {"producer": "read exact target"}},
        "taskcard": {"present": True, "body": "current task"},
    }
    tool_meta = {"id": "new", "status": "error", "comment": {"raw_locator": "logs/events.jsonl"}}
    content = {"stdout": "payload", "error": "repair me", "cost": 3}
    block = ToolResultBlock("new", "shell", deepcopy(content), metadata={
        "tool_meta": deepcopy(tool_meta), "agent_meta": deepcopy(dynamic),
    })
    block._agent_pending = {"agent_state": deepcopy(state)}
    meta_block.attach_active_runtime(SimpleNamespace(), [block], prior_holder=legacy)
    meta_block.finalize_two_axis_sidecars([block])
    assert block.content == content
    assert block.metadata["tool_meta"] == tool_meta
    current = block.metadata["agent_meta"]
    assert "instruction" not in current
    assert current["agent_state"] == state
    for key in ("notifications", "taskcard"):
        assert current[key] == dynamic[key]
    assert current["guidance"]["transient"] == dynamic["guidance"]["transient"]
    assert current["guidance"]["persistent"] == meta_block.build_meta_guidance_ref()

    # IDLE/synthetic construction has no finalization stage to hide a leftover.
    monkeypatch.setattr(meta_block, "build_meta", lambda agent: deepcopy(state))
    envelope = meta_block.build_synthetic_meta_envelope(
        SimpleNamespace(), {}, call_id="notification-check"
    )
    assert "instruction" not in envelope["agent_meta"]
    assert envelope["agent_meta"]["agent_state"] == state
    assert envelope["tool_meta"]["id"] == "notification-check"

    daemon = ToolResultBlock("daemon", "shell", "local result")
    daemon_state = {"daemon": {"id": "worker"}, "context": {"warning": "local warning"}}
    meta_block.attach_daemon_agent_meta([daemon], agent_state=daemon_state)
    assert daemon.metadata["agent_meta"] == {"agent_state": daemon_state}
    assert json.dumps(legacy.to_dict(), ensure_ascii=False) == legacy_bytes
    assert [json.dumps(convert(old), ensure_ascii=False) for convert in converters] == legacy_wires
