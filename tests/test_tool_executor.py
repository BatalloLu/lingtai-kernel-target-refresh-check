"""Accepted secondary-retirement boundaries: ordinary serial/parallel dispatch."""
from __future__ import annotations

from unittest.mock import MagicMock
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
