"""Plugin mode boundary: one public mount, unchanged read-only owner semantics."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from lingtai.adapters.tool_plugin_host import agent_host_ports
from lingtai.kernel.tool_plugin import (
    OFFICIAL_TOOL_PLUGIN_NAMES, PluginCatalogState, ToolPluginHost,
)
from lingtai.tools import plugin
from lingtai.tools.plugin import _mcp
from lingtai.tools.registry import BUILTIN_TOOLS, CORE_DEFAULTS, setup_capability
from tests._service_helpers import make_mock_llm_service


def _bound(tmp_path):
    writes = {"plugin": [], "mcp": []}
    state = PluginCatalogState(
        registration={"declared": [], "configured_declared": [], "plugins": []},
        configured_paths=(), skill_paths=(), skills_enabled=True,
    )
    ports = {
        "workdir": SimpleNamespace(path=tmp_path),
        "plugin_catalog": SimpleNamespace(read_state=lambda: state),
        "prompt_section": SimpleNamespace(write_protected_section=writes["plugin"].append),
        "mcp_prompt_section": SimpleNamespace(write_protected_section=writes["mcp"].append),
    }
    host = ToolPluginHost.grant(plugin.DECLARATION, ports)
    return plugin.DECLARATION.bind(host), writes


def _call(bound, action, **extra):
    return bound.handler({"action": action, "input": {}, "reasoning": "test", **extra})


def _record(name="local"):
    return {"name": name, "summary": "local registry fact", "transport": "stdio",
            "command": "never-run", "args": [], "source": "test-local"}


def test_schema_defaults_and_clean_break():
    schema = plugin.get_schema()
    assert schema["properties"]["mode"]["enum"] == ["plugin", "mcp"]
    assert schema["properties"]["mode"]["default"] == "plugin"
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == ["info", "settings", "manual"]
    for branch in schema["properties"]["input"]["anyOf"]:
        assert branch["properties"] == {}
        assert branch["additionalProperties"] is False
    assert "mcp" not in BUILTIN_TOOLS and "mcp" not in CORE_DEFAULTS
    assert "mcp" not in OFFICIAL_TOOL_PLUGIN_NAMES
    import lingtai.tools.mcp as retired
    for name in ("DECLARATION", "setup", "get_schema", "get_description"):
        assert not hasattr(retired, name)
    with pytest.raises(ValueError, match="Unknown capability"):
        setup_capability(object(), "mcp")


def test_omitted_and_explicit_plugin_mode_preserve_results(tmp_path):
    bound, writes = _bound(tmp_path)
    for action in ("info", "settings", "manual"):
        assert _call(bound, action) == _call(bound, action, mode="plugin")
    assert writes["mcp"] == []
    assert _call(bound, "settings") == {"settings": [{
        "key": "manifest.plugins", "current": "<redacted>", "default": "<redacted>",
        "configurable": True, "comment": "plugin-manual#plugin-registration-roots",
    }]}
    assert "plugin_manual" in _call(bound, "manual")


@pytest.mark.parametrize("mode", [None, "invalid", [], {}, 0, True])
def test_invalid_mode_fails_without_io(tmp_path, mode):
    bound, writes = _bound(tmp_path)
    assert _call(bound, "info", mode=mode) == {
        "status": "failed", "error_code": "INVALID_ARGUMENT",
        "message": "mode must be 'plugin' or 'mcp'",
    }
    assert writes == {"plugin": [], "mcp": []}


@pytest.mark.parametrize("mode", ["plugin", "mcp"])
@pytest.mark.parametrize("action", ["info", "settings", "manual"])
@pytest.mark.parametrize("extra", [
    {"input": {"mode": "mcp"}}, {"input": {"unexpected": 1}},
    {"input": []}, {"summarize": "yes"}, {"unexpected": 1},
])
def test_malformed_calls_fail_before_owner_io(tmp_path, monkeypatch, mode, action, extra):
    def forbidden(*args, **kwargs):
        raise AssertionError("malformed call reached owner I/O")
    import lingtai.services.mcp_registry as mcp_registry
    import lingtai.services.plugin_registry as plugin_registry
    import lingtai.tools.tool_family.manual as manual
    monkeypatch.setattr(mcp_registry, "read_registry", forbidden)
    monkeypatch.setattr(mcp_registry, "read_identities", forbidden)
    monkeypatch.setattr(plugin_registry, "read_plugins", forbidden)
    monkeypatch.setattr(_mcp.MCPSettingsProvider, "__call__", forbidden)
    monkeypatch.setattr(manual, "load_installed_manual", forbidden)
    bound, writes = _bound(tmp_path)
    result = _call(bound, action, mode=mode, **extra)
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert writes == {"plugin": [], "mcp": []}


@pytest.mark.parametrize("action", ["missing", [], {}])
def test_unknown_action_envelopes_preserved(tmp_path, action):
    bound, writes = _bound(tmp_path)
    assert _call(bound, action)["message"] == (
        f"unknown action: {action!r}, only 'info' or 'settings' or 'manual' is supported"
    )
    assert _call(bound, action, mode="mcp")["message"] == (
        f"unknown action: {action!r}, only 'info', 'settings', or 'manual' is supported"
    )
    assert writes == {"plugin": [], "mcp": []}


def test_mcp_info_is_fresh_and_read_only_with_separate_protected_section(tmp_path):
    bound, writes = _bound(tmp_path)
    registry = tmp_path / "mcp_registry.jsonl"
    registry.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    before = registry.read_bytes()
    first = _call(bound, "info", mode="mcp", summarize=False)
    assert set(first) == {"status", "registry_path", "registered_count", "registered", "problems"}
    assert first["registered"] == [{"name": "local", "summary": "local registry fact"}]
    assert registry.read_bytes() == before
    assert len(writes["mcp"]) == 1 and writes["plugin"] == []
    registry.write_text(json.dumps(_record("second")) + "\n", encoding="utf-8")
    assert _call(bound, "info", mode="mcp")["registered"][0]["name"] == "second"


def test_mcp_manual_uses_installed_owner_and_never_reads_registry(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("manual must not inspect registry or identities")
    import lingtai.services.mcp_registry as service
    monkeypatch.setattr(service, "read_registry", forbidden)
    monkeypatch.setattr(service, "read_identities", forbidden)
    bound, writes = _bound(tmp_path)
    missing = _call(bound, "manual", mode="mcp")
    assert missing["status"] == "degraded" and missing["mcp_manual"] == ""
    path = tmp_path / ".library/intrinsic/capabilities/mcp/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("MCP installed manual", encoding="utf-8")
    assert _call(bound, "manual", mode="mcp") == {
        "status": "ok", "mcp_manual": "MCP installed manual", "manual_path": str(path),
    }
    assert writes == {"plugin": [], "mcp": []}


def test_mcp_settings_fresh_effective_reader_redaction_and_atomic_failures(tmp_path, monkeypatch):
    import lingtai.init_reader as reader
    data = {"addons": ["telegram"], "mcp": {"local": {"env": {"TOKEN": "secret"}}}}
    monkeypatch.setattr(reader, "reader_callbacks", lambda *a, **kw: (None, None))
    monkeypatch.setattr(reader, "read_init", lambda *a, **kw: SimpleNamespace(ok=True, data=data))
    bound, writes = _bound(tmp_path)
    result = _call(bound, "settings", mode="mcp")
    assert [row["key"] for row in result["settings"]] == ["init.addons", "init.mcp"]
    assert all(list(row) == ["key", "current", "default", "configurable", "comment"]
               for row in result["settings"])
    assert result["settings"][1]["current"] == result["settings"][1]["default"] == "<redacted>"
    assert "secret" not in json.dumps(result)
    data["addons"] = ["changed"]
    assert _call(bound, "settings", mode="mcp")["settings"][0]["current"] == ["changed"]
    data["addons"] = ["x" * 66000]
    assert _call(bound, "settings", mode="mcp")["error_code"] == "SETTINGS_RESPONSE_TOO_LARGE"
    data["addons"] = None
    assert _call(bound, "settings", mode="mcp") == {
        "status": "failed", "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }
    assert writes == {"plugin": [], "mcp": []}


def test_host_adapter_binds_two_fixed_protected_writers(tmp_path):
    writes = []
    agent = SimpleNamespace(working_dir=tmp_path, _log=lambda *a, **kw: None,
                            update_system_prompt=lambda *a, **kw: writes.append((a, kw)))
    ports = agent_host_ports(agent, "plugin")
    ports["prompt_section"].write_protected_section("plugins")
    ports["mcp_prompt_section"].write_protected_section("servers")
    assert writes == [(("plugin", "plugins"), {"protected": True}),
                      (("mcp", "servers"), {"protected": True})]
    assert "mcp_prompt_section" not in agent_host_ports(agent, "notification")


def test_real_agent_default_setup_installs_both_manuals_and_full_prompt(tmp_path, monkeypatch):
    from lingtai.agent import Agent
    def forbidden(*args, **kwargs):
        raise AssertionError("catalog presentation must not connect an MCP server")
    monkeypatch.setattr(Agent, "connect_mcp", forbidden)
    monkeypatch.setattr(Agent, "connect_mcp_http", forbidden)
    agent = Agent(
        service=make_mock_llm_service(), working_dir=tmp_path,
        capabilities={}, disable=[name for name in CORE_DEFAULTS if name != "plugin"],
    )
    try:
        assert "plugin" in agent._tool_handlers and "mcp" not in agent._tool_handlers
        assert "plugin" in agent.official_tool_plugins and "mcp" not in agent.official_tool_plugins
        for mode, body_key in (("plugin", "plugin_manual"), ("mcp", "mcp_manual")):
            result = agent._tool_handlers["plugin"]({"mode": mode, "action": "manual", "input": {}, "reasoning": "test"})
            assert result["status"] == "ok" and result[body_key]
        prompt = agent._build_system_prompt()
        assert "mode" in prompt and "mcp" in prompt
        assert "plugin" in agent._prompt_manager._sections
        assert "mcp" in agent._prompt_manager._sections
    finally:
        agent.stop(timeout=2.0)
