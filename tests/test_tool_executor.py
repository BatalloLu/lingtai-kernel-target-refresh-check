"""Accepted secondary-retirement boundaries: ordinary serial/parallel dispatch."""
from __future__ import annotations

from unittest.mock import MagicMock
from copy import deepcopy
import pytest
from lingtai.kernel.llm.base import ToolCall
from lingtai.kernel.llm.interface import ToolResultBlock
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.tool_executor import ToolExecutor

def make_executor(
    dispatch_fn=None,
    parallel_safe=None,
    known_tools=None,
    logger_fn=None,
    working_dir=None,
    max_result_chars=50_000,
    guard=None,
    tool_call_guard=None,
    canonical_result=False,
):
    if dispatch_fn is None:
        dispatch_fn = lambda tc: {"status": "ok", "result": f"ran {tc.name}"}
    if canonical_result:
        result_factory = lambda name, result, **kw: ToolResultBlock(
            kw.get("tool_call_id", ""),
            name,
            result,
        )
    else:
        result_factory = lambda name, result, **kw: {"name": name, "result": result}
    make_result = MagicMock(side_effect=result_factory)
    guard = guard or LoopGuard(max_total_calls=50)
    return ToolExecutor(
        dispatch_fn=dispatch_fn,
        make_tool_result_fn=make_result,
        guard=guard,
        known_tools=known_tools,
        parallel_safe_tools=parallel_safe or set(),
        logger_fn=logger_fn,
        working_dir=working_dir,
        max_result_chars=max_result_chars,
        tool_call_guard=tool_call_guard,
    )


@pytest.mark.parametrize("unexpected_arg", ["secondary", "unexpected"])
@pytest.mark.parametrize("value", [
    {"tool": "telegram", "args": {"action": "read", "chat_id": 123}},
    None,
    False,
])
def test_obsolete_secondary_arg_follows_ordinary_dispatch_error(unexpected_arg, value):
    seen = []
    handled = []
    logs = []

    def read(*, path):
        handled.append(path)
        return {"status": "ok", "path": path}

    def dispatch(tc):
        seen.append((tc.name, dict(tc.args)))
        return read(**tc.args)

    executor = make_executor(
        dispatch_fn=dispatch,
        known_tools={"read", "telegram"},
        logger_fn=lambda event_type, **fields: logs.append((event_type, fields)),
    )
    args = {"path": "/tmp", unexpected_arg: value}
    call = ToolCall(name="read", args=args, id="tc1")
    errors = []

    results, intercepted, _ = executor.execute([call], collected_errors=errors)

    assert not intercepted
    assert len(results) == 1
    assert seen == [("read", args)]
    assert handled == []  # Python rejects the keyword before the body runs.
    assert call.args == {"path": "/tmp", unexpected_arg: value}
    payload = results[0]["result"]
    assert payload["status"] == "error"
    assert payload["error_type"] == "TypeError"
    assert payload["error_phase"] == "dispatch"
    assert f"unexpected keyword argument '{unexpected_arg}'" in payload["message"]
    assert payload["tool_args"] == args
    assert payload["tool_call_id"] == "tc1"
    assert errors == [f"read: {payload['message']}"]
    assert "_secondary" not in payload
    normalized = [fields for event, fields in logs if event == "tool_call_normalized"]
    assert len(normalized) == 1
    assert normalized[0]["tool_args"] == args
    assert normalized[0]["removed_args"] == []
    assert all(event != "deprecated_secondary_ignored" for event, _ in logs)
    assert all("deprecated_secondary_ignored" not in fields for _, fields in logs)


def test_obsolete_secondary_arg_fails_normally_on_parallel_path():
    seen = []
    handled = []
    logs = []

    def a():
        handled.append("a")
        return {"status": "ok"}

    def b(*, value):
        handled.append("b")
        return {"status": "ok", "value": value}

    def dispatch(tc):
        seen.append((tc.name, dict(tc.args)))
        return {"a": a, "b": b}[tc.name](**tc.args)

    executor = make_executor(
        dispatch_fn=dispatch,
        known_tools={"a", "b", "telegram"},
        parallel_safe={"a", "b"},
        logger_fn=lambda event_type, **fields: logs.append((event_type, fields)),
    )
    args = {"secondary": {"tool": "telegram", "args": {"action": "read", "chat_id": 123}}}
    errors = []

    results, intercepted, _ = executor.execute([
        ToolCall(name="a", args=args, id="a1"),
        ToolCall(name="b", args={"value": 2}, id="b1"),
    ], collected_errors=errors)

    assert not intercepted
    assert [result["name"] for result in results] == ["a", "b"]
    assert len(seen) == 2
    assert ("a", args) in seen
    assert ("b", {"value": 2}) in seen
    assert handled == ["b"]
    failed, valid = [result["result"] for result in results]
    assert failed["status"] == "error"
    assert failed["error_type"] == "TypeError"
    assert failed["error_phase"] == "dispatch"
    assert "unexpected keyword argument 'secondary'" in failed["message"]
    assert failed["tool_args"] == args
    assert failed["tool_call_id"] == "a1"
    assert errors == [f"a: {failed['message']}"]
    assert valid["status"] == "ok"
    assert valid["value"] == 2
    assert all("_secondary" not in result["result"] for result in results)
    normalized = [fields for event, fields in logs if event == "tool_call_normalized"]
    assert len(normalized) == 2
    assert all(fields["removed_args"] == [] for fields in normalized)
    assert all(event != "deprecated_secondary_ignored" for event, _ in logs)
    assert all("deprecated_secondary_ignored" not in fields for _, fields in logs)


@pytest.mark.parametrize("parallel", [False, True])
def test_secondary_named_handler_arg_is_preserved_as_ordinary_data(parallel):
    """A handler accepting this name gets data, not a nested dispatch request."""
    seen = []

    def handler(*, value, secondary):
        return {"status": "ok", "value": value, "secondary": secondary}

    def dispatch(tc):
        seen.append((tc.name, dict(tc.args)))
        return handler(**tc.args)

    executor = make_executor(dispatch_fn=dispatch, known_tools={"custom", "telegram"})
    args = {"value": 1, "secondary": {"tool": "telegram", "args": {"action": "read"}}}
    calls = [ToolCall(name="custom", args=args, id="custom1")]
    if parallel:
        calls.append(ToolCall(name="custom", args={"value": 2, "secondary": None}, id="custom2"))

    results, intercepted, _ = executor.execute(calls)

    assert not intercepted
    assert len(results) == len(calls)
    assert len(seen) == len(calls)
    for call, result in zip(calls, results):
        assert (call.name, call.args) in seen
        assert result["result"]["status"] == "ok"
        assert result["result"]["value"] == call.args["value"]
        assert result["result"]["secondary"] == call.args["secondary"]
        assert "_secondary" not in result["result"]


# Default-on a-priori presentation: exercise the consumer, not schema prose.
_LTP_SUMMARY_ROOTS = (
    "web", "mcp", "plugin", "vision", "avatar", "shell", "notification",
    "system", "daemon", "email", "task_card", "context", "psyche",
    "telegram", "feishu", "imap", "wechat", "whatsapp", "cloud_mail",
)
_CURATED_SUMMARY_ROOTS = (
    "telegram", "feishu", "imap", "wechat", "whatsapp", "cloud_mail",
)


def _summary_executor(dispatch, summarize, logs, *, daemon=False):
    return ToolExecutor(
        dispatch_fn=dispatch,
        make_tool_result_fn=lambda name, result, **kw: {"name": name, "result": result},
        guard=LoopGuard(max_total_calls=50),
        # Durable log serialization snapshots fields before metadata stamping.
        logger_fn=lambda event, **fields: logs.append((event, deepcopy(fields))),
        summarizer_fn=summarize,
        raw_log_path="daemons/test/logs/events.jsonl" if daemon else None,
        raw_event_type="daemon_tool_result" if daemon else None,
    )


@pytest.mark.parametrize("name", _LTP_SUMMARY_ROOTS)
@pytest.mark.parametrize("daemon", [False, True])
def test_apriori_default_omission_and_false_reach_actual_executor(name, daemon):
    """Tiny receipts are eligible; SDK/direct and daemon executors share policy."""
    from lingtai.kernel.tool_result_summary import is_apriori_summary

    logs, summaries = [], []
    raw = {"status": "ok", "receipt": "exact-id"}

    def summarize(system, prompt, tool_name, call_id):
        # The raw record precedes any summary request for this exact call.
        assert any(event == "tool_result" and fields["tool_call_id"] == call_id
                   and fields["result"] == raw for event, fields in logs)
        assert "retain receipt" in prompt
        summaries.append(call_id)
        return "receipt retained"

    executor = _summary_executor(lambda tc: dict(raw), summarize, logs, daemon=daemon)
    args = {"action": "probe", "input": {}, "reasoning": "retain receipt"}
    # Two calls select the real concurrent sibling path. Explicit canonical
    # false wins even over a historical/pending legacy summary=true flag.
    calls = [
        ToolCall(name=name, args=args, id="default"),
        ToolCall(name=name, args={**args, "summarize": False, "summary": True}, id="raw"),
    ]
    results, intercepted, _ = executor.execute(calls)
    assert not intercepted
    assert summaries == ["default"]
    summary, exact = [item["result"] for item in results]
    assert is_apriori_summary(summary)
    assert summary["canonical"] is False
    assert summary["raw_preserved"] is True
    assert summary["raw_locator"]["tool_call_id"] == "default"
    assert summary["raw_locator"]["event_type"] == ("daemon_tool_result" if daemon else "tool_result")
    assert summary["raw_locator"]["log"] == ("daemons/test/logs/events.jsonl" if daemon else "logs/events.jsonl")
    # Recover the exact recorded original using the unchanged locator identity.
    locator = summary["raw_locator"]
    recovered = [fields["result"] for event, fields in logs
                 if event == "tool_result" and fields["tool_call_id"] == locator["tool_call_id"]]
    assert recovered == [raw]
    assert locator["query"] == f"grep 'default' <workdir>/{locator['log']}"
    assert "raw_locator" in summary["retrieval_hint"]
    assert "summarize=false" in summary["retrieval_hint"]
    assert all(exact[key] == value for key, value in raw.items())
    assert not is_apriori_summary(exact)
    # Provider proposals and durably logged raw results are not rewritten.
    assert "summarize" not in calls[0].args
    assert calls[1].args["summarize"] is False
    assert all(fields["result"] == raw for event, fields in logs if event == "tool_result")


@pytest.mark.parametrize("control,expected", [
    ({}, True), ({"summarize": True}, True), ({"summarize": False}, False),
    ({"summarize": None}, False), ({"summarize": "true"}, False),
    ({"summarize": 1}, False), ({"summary": True}, True),
    ({"summary": False}, False), ({"summary": None}, False),
    ({"summarize": False, "summary": True}, False),
    ({"summarize": True, "summary": False}, True),
])
def test_apriori_default_literal_controls_single_consumer(control, expected):
    from lingtai.kernel.tool_result_summary import is_apriori_summary, summary_requested

    assert summary_requested(control, "shell") is expected
    logs, summaries = [], []
    executor = _summary_executor(
        lambda tc: {"status": "ok", "receipt": "raw"},
        lambda *args: summaries.append(args) or "retained",
        logs,
    )
    result = executor.execute([ToolCall(name="shell", args=control, id="single")])[0][0]["result"]
    assert is_apriori_summary(result) is expected
    assert bool(summaries) is expected
    assert summary_requested(None, "shell") is False


@pytest.mark.parametrize("name", _CURATED_SUMMARY_ROOTS)
@pytest.mark.parametrize("control", [{}, {"summarize": False}, {"summarize": True}])
def test_apriori_default_curated_schema_and_real_manual_dispatch(name, control):
    """All shipped exact names, including independently composed Cloud Mail."""
    from importlib import import_module
    from lingtai.kernel.tool_result_summary import is_apriori_summary

    family = import_module(f"lingtai.mcp_servers.{name}._family")
    schema = getattr(family, f"{name}_schema")()
    prop = schema["properties"]["summarize"]
    assert prop["type"] == "boolean"
    assert prop["default"] is True
    assert "Proactively set summarize=false" in prop["description"]
    assert "reasoning" in prop["description"]
    assert "noncanonical" in prop["description"]
    assert "summarize" not in schema["required"]
    handle = getattr(family, f"handle_{name}")
    args = {"action": "manual", "input": {}, "reasoning": "retain manual title", **control}
    # Direct family dispatch owns canonical raw action output; presentation is
    # the host executor's responsibility, never an action argument/default.
    raw = handle(None, args)
    logs, summaries = [], []

    def dispatch(tc):
        envelope = dict(tc.args)
        envelope["reasoning"] = envelope.pop("_reasoning")
        return handle(None, envelope)

    executor = _summary_executor(dispatch, lambda *a: summaries.append(a) or "title retained", logs)
    visible = executor.execute([ToolCall(name=name, args=args, id="manual")])[0][0]["result"]
    enabled = control.get("summarize", True)
    assert is_apriori_summary(visible) is enabled
    assert bool(summaries) is enabled
    recorded = [fields["result"] for event, fields in logs if event == "tool_result"]
    assert recorded == [raw]
    if not enabled:
        # Metadata is additive; every canonical action field stays exact.
        assert all(visible[key] == value for key, value in raw.items())


@pytest.mark.parametrize("name", _CURATED_SUMMARY_ROOTS)
@pytest.mark.parametrize("value", [None, "true", 1])
def test_apriori_default_curated_parser_failure_stays_exact(name, value):
    from importlib import import_module
    from lingtai.kernel.tool_result_summary import is_apriori_summary

    handle = getattr(import_module(f"lingtai.mcp_servers.{name}._family"), f"handle_{name}")
    args = {"action": "manual", "input": {}, "reasoning": "read gates", "summarize": value}
    expected = handle(None, args)
    assert expected["status"] == "failed"
    assert expected["error_code"] == "INVALID_ARGUMENT"
    logs, summaries = [], []

    def dispatch(tc):
        envelope = dict(tc.args)
        envelope["reasoning"] = envelope.pop("_reasoning")
        return handle(None, envelope)

    result = _summary_executor(dispatch, lambda *a: summaries.append(a) or "wrong", logs).execute(
        [ToolCall(name=name, args=args, id="invalid")]
    )[0][0]["result"]
    assert not is_apriori_summary(result)
    assert summaries == []
    assert all(result[key] == value for key, value in expected.items())


def test_apriori_default_shared_schema_and_unrelated_domain_isolation():
    from lingtai.kernel.tool_result_summary import summary_requested, is_apriori_summary
    from lingtai.tools.tool_family import ChildTool, ToolFamily

    schema = ToolFamily("shell", [ChildTool("probe", {"type": "object", "properties": {}}, lambda a: {})]).build_schema()
    assert schema["properties"]["summarize"]["default"] is True
    assert "summarize" not in schema["required"]
    for name in (None, "external", "Context.summarize", "CloudMail", "cloud-mail"):
        assert summary_requested({}, name) is False
        assert summary_requested({"summarize": True}, name) is False
        assert summary_requested({"summary": True}, name) is True  # preserved legacy contract
    logs, summaries, received = [], [], []
    args = {"summarize": True, "input": {"summary": "domain text"}}

    def dispatch(tc):
        received.append(tc.args)
        return {"status": "ok", "domain": tc.args}

    result = _summary_executor(dispatch, lambda *a: summaries.append(a) or "wrong", logs).execute(
        [ToolCall(name="Context.summarize", args=args, id="domain")]
    )[0][0]["result"]
    assert received == [args]
    assert result["domain"] == args
    assert not is_apriori_summary(result)
    assert summaries == []


def test_apriori_default_context_action_input_is_not_presentation_control():
    from lingtai.tools import context as context_tool
    from lingtai.kernel.tool_result_summary import summary_requested

    schema = context_tool.get_schema()
    # Context's record-only summarize action stays domain input, independent
    # of the separately resolved root presentation control.
    args = {"action": "summarize", "input": {"items": [
        {"tool_call_id": "prior", "summary": "agent-authored replacement"},
    ]}, "summarize": False, "reasoning": "inspect exact receipt"}
    logs, summaries, received = [], [], []
    executor = _summary_executor(
        lambda tc: received.append(tc.args["input"]) or {"status": "ok", "items": tc.args["input"]["items"]},
        lambda *a: summaries.append(a) or "wrong", logs,
    )
    result = executor.execute([ToolCall(name="context", args=args, id="context")])[0][0]["result"]
    assert "summarize" in schema["properties"]["action"]["enum"]
    assert summary_requested(args, "context") is False
    assert received == [args["input"]]
    assert result["items"] == args["input"]["items"]
    assert summaries == []


@pytest.mark.parametrize("daemon", [False, True])
def test_apriori_default_missing_gateway_still_fails_closed(daemon):
    from lingtai.kernel.tool_result_summary import is_apriori_summary

    raw = {"status": "ok", "secret_raw": "preserved only"}
    logs = []
    result = _summary_executor(lambda tc: dict(raw), None, logs, daemon=daemon).execute(
        [ToolCall(name="shell", args={}, id="no-gateway")]
    )[0][0]["result"]
    assert is_apriori_summary(result)
    assert result["summary_kind"] == "apriori_error"
    assert "secret_raw" not in result
    assert [fields["result"] for event, fields in logs if event == "tool_result"] == [raw]


@pytest.mark.parametrize("name", _CURATED_SUMMARY_ROOTS)
def test_apriori_default_curated_error_with_omitted_control_stays_exact(name):
    from importlib import import_module
    from lingtai.kernel.tool_result_summary import is_apriori_summary

    handle = getattr(import_module(f"lingtai.mcp_servers.{name}._family"), f"handle_{name}")
    args = {"action": "unknown", "input": {}, "reasoning": "inspect exact error"}
    expected = handle(None, args)
    logs, summaries = [], []

    def dispatch(tc):
        envelope = dict(tc.args)
        envelope["reasoning"] = envelope.pop("_reasoning")
        return handle(None, envelope)

    result = _summary_executor(dispatch, lambda *a: summaries.append(a) or "wrong", logs).execute(
        [ToolCall(name=name, args=args, id="failed")]
    )[0][0]["result"]
    assert expected["status"] == "failed"
    assert all(result[key] == value for key, value in expected.items())
    assert not is_apriori_summary(result)
    assert summaries == []


@pytest.mark.parametrize("value", [None, "true", 1])
def test_apriori_default_generic_family_parser_contract_is_preserved(value):
    from lingtai.tools.tool_family import ChildTool, ToolFamily

    inputs, summaries, logs = [], [], []
    family = ToolFamily("shell", [ChildTool(
        "probe", {"type": "object", "properties": {}, "additionalProperties": False},
        lambda action_input: inputs.append(action_input) or {"status": "ok"},
    )])
    args = {"action": "probe", "input": {}, "summarize": value}
    result = _summary_executor(lambda tc: family.handle(tc.args),
                               lambda *a: summaries.append(a) or "wrong", logs).execute(
        [ToolCall(name="shell", args=args, id="invalid")]
    )[0][0]["result"]
    assert result["status"] == "failed"
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert result["message"] == "summarize must be a boolean"
    assert inputs == []
    assert summaries == []


@pytest.mark.parametrize("kind", ["success", "cap", "error"])
@pytest.mark.parametrize("daemon", [False, True])
def test_apriori_compact_envelope_preserves_raw_locator(kind, daemon):
    """Pure builders retain retrieval and loss boundaries on every replacement."""
    from lingtai.kernel.tool_result_summary import (
        APRIORI_SUMMARY_CAP, APRIORI_SUMMARY_MARKER,
        build_cap_refusal, build_summary_error, build_summary_replacement,
    )

    log = "daemons/test/logs/events.jsonl" if daemon else "logs/events.jsonl"
    event = "daemon_tool_result" if daemon else "tool_result"
    common = dict(tool_name="shell", tool_call_id="call_exact",
                  original_visible_chars=1234, raw_log_path=log, raw_event_type=event)
    if kind == "success":
        payload = build_summary_replacement(
            **common, summary_text="receipt exact-id", reason="retain receipt",
            summary_input_chars=1234, summary_input_truncated=False,
        )
        assert payload["generated_summary"] == "receipt exact-id"
        assert payload["summary_kind"] == "apriori_generated"
        assert payload["summary_reason"] == "retain receipt"
        assert payload["summarized_at"]
        assert payload["summary_effect"] == dict(prev_chars=1234, after_chars=16, saved_chars=1218)
        assert payload["summary_chars"] == 16
        assert payload["summary_input_chars"] == 1234
    elif kind == "cap":
        payload = build_cap_refusal(**common)
        assert payload["summary_kind"] == "apriori_cap_refused"
        assert payload["cap_chars"] == APRIORI_SUMMARY_CAP
        assert payload["summary_input_chars"] == 0
    else:
        payload = build_summary_error(**common, error="gateway failed")
        assert payload["summary_kind"] == "apriori_error"
        assert payload["error"] == "gateway failed"
        assert payload["summary_input_chars"] == 0
    assert payload["artifact"] == APRIORI_SUMMARY_MARKER
    assert payload["canonical"] is False
    assert payload["raw_preserved"] is True
    assert payload["summary_input_truncated"] is False
    assert payload["raw_locator"] == {
        "tool_call_id": "call_exact", "log": log, "event_type": event,
        "query": f"grep 'call_exact' <workdir>/{log}",
    }
    hint = payload["retrieval_hint"]
    assert len(hint) < 220
    assert all(term in hint for term in (
        "noncanonical", "lossy", "incomplete or inaccurate", "preserved outside context",
        "raw_locator", "summarize=false",
    ))
    # The query/path occur once, in raw_locator, not repeated in prose.
    assert "grep" not in hint
    assert log not in hint
