"""Own-Agent summary receipts supplement SESSION without moving parent lanes.

Hermetic public-list-price fixtures; no provider, catalog fetch, or daemon run.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from lingtai.kernel.base_agent import turn
from lingtai.kernel.llm.base import LLMResponse, UsageMetadata
from lingtai.kernel.tool_result_summary import maybe_summarize_result
from lingtai.mcp_servers.task_card.event_projection import TaskCardEventProjection as Projection
from lingtai.mcp_servers.telegram.task_card.api_cost import (
    estimate_parts, fold_session_cost, session_cost_text,
)


MODEL = "claude-sonnet-4-20250514"
# Anthropic Sonnet 4 public USD/token list prices: $3/$15 per million
# input/output, $0.30 read, $3.75 5m write, $6 1h write. Offline fixture,
# not a claim that a catalog fetch or an invoice was verified by this test.
PUBLIC_PRICES = {
    "input_cost_per_token": 3e-6,
    "output_cost_per_token": 15e-6,
    "cache_read_input_token_cost": .3e-6,
    "cache_creation_input_token_cost": 3.75e-6,
    "cache_creation_input_token_cost_above_1hr": 6e-6,
}


class OfflineCatalog:
    def __init__(self, entry=None, status="ok"):
        self.entry = dict(PUBLIC_PRICES if entry is None else entry)
        self.status = status

    def lookup(self, model):
        return (self.status, self.entry, "offline-public-price-fixture") if model == MODEL else (
            "unlisted", None, "offline-public-price-fixture",
        )


def parent(index=1, generation=0):
    return {
        "type": "llm_response", "api_call_id": f"parent-{generation}-{index}",
        "input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0,
        "thinking_tokens": 0,
        "usage_billing": {"model": MODEL, "cache_write_tokens": 0, "billable_output_tokens": 100},
        "stream_timing": {"first_token_s": 1.2, "generation_s": 4, "generation_tokens": 100},
        "session_usage": {
            "schema": Projection.SESSION_USAGE_SCHEMA, "molt_count": generation,
            "api_call_index": index, "api_calls": index,
            "input_tokens": 1000 * index, "output_tokens": 100 * index,
            "cached_tokens": 0, "session_cache_rate": 0.0,
            "cache_miss_tokens": 1000 * index,
            "avg_input_tokens_per_api_call": 1000,
            "cache_miss_budget": 2_000_000,
            "cache_miss_remaining_tokens": 2_000_000 - 1000 * index,
            "context_tokens": 1000, "context_window": 200_000, "context_usage": .005,
        },
    }


def helper(call_id="summary-1", generation=0, **changes):
    return {
        "type": "apriori_summary_usage", "schema": "lingtai.apriori_summary.usage/v1",
        "source": "summarize_apriori", "api_call_id": call_id,
        "molt_count": generation, "tool_name": "shell", "tool_call_id": f"tool-{call_id}",
        "input_tokens": 1000, "output_tokens": 200, "cached_tokens": 200, "thinking_tokens": 30,
        # This exact-price fixture establishes all writes as 5m, not unknown TTL.
        "usage_billing": {"model": MODEL, "cache_write_tokens": 100,
                          "cache_write_1h_tokens": 0, "billable_output_tokens": 200},
        **changes,
    }


def fold(events):
    state = cost = None
    for event in events:
        state = Projection.reduce_session_usage_event(state, event)
        cost = fold_session_cost(cost, state, event)
    return state, cost


def fake_agent(monkeypatch, tmp_path, response):
    events, ledger, options = [], [], []

    def create_session(**kwargs):
        options.append(kwargs)
        return SimpleNamespace(send=lambda _prompt: response)

    agent = SimpleNamespace(
        service=SimpleNamespace(model="configured-alias", create_session=create_session),
        _config=SimpleNamespace(model="configured-alias", provider="test-provider"),
        _molt_count=4, _working_dir=tmp_path,
        _log=lambda kind, **fields: events.append({"type": kind, **fields}),
    )
    monkeypatch.setattr(turn, "append_token_entry", lambda path, **entry: ledger.append(entry))
    return agent, events, ledger, options


@pytest.mark.parametrize("text", ["useful summary", "", None, ["invalid-text"]])
def test_actual_returned_usage_recorded_before_summary_validation(monkeypatch, tmp_path, text):
    usage = UsageMetadata(
        input_tokens=1000, output_tokens=200, thinking_tokens=30, cached_tokens=200,
        cache_write_tokens=100, billable_output_tokens=230,
        response_model=MODEL, requested_service_tier="priority",
        extra={"secret_payload": "never-project", "codex_auth_path_sha8": "safe-hash"},
    )
    response = LLMResponse(text=text, usage=usage, api_call_id="normalized-response-id")
    agent, events, ledger, options = fake_agent(monkeypatch, tmp_path, response)
    raw = {"data": "raw durable content"}
    result = maybe_summarize_result(
        raw, args={"summary": True, "_reasoning": "retain facts"}, tool_name="shell",
        tool_call_id="tool-1", summarizer_fn=turn._build_apriori_summarizer_fn(agent),
        logger_fn=agent._log,
    )
    assert result is not raw
    assert options == [{"system_prompt": options[0]["system_prompt"], "tools": None,
                        "model": "configured-alias", "tracked": False, "provider": "test-provider"}]
    receipt = events[0]
    assert receipt["type"] == "apriori_summary_usage"
    assert receipt["api_call_id"] == "normalized-response-id"
    assert receipt["molt_count"] == 4
    assert receipt["usage_billing"] == {
        "model": MODEL, "requested_model": "configured-alias", "service_tier": "priority",
        "cache_write_tokens": 100, "billable_output_tokens": 230,
    }
    assert len(ledger) == 1
    assert ledger[0]["extra"]["api_call_id"] == receipt["api_call_id"]
    assert ledger[0]["extra"]["usage_billing"] == receipt["usage_billing"]
    assert ledger[0]["extra"]["source"] == "summarize_apriori"
    assert ledger[0]["extra"]["codex_auth_path_sha8"] == "safe-hash"
    assert "never-project" not in repr(events) + repr(ledger)
    assert agent._molt_count == 4  # no SessionManager/counter mutation


def test_generated_api_id_and_captured_generation(monkeypatch, tmp_path):
    response = LLMResponse(text="summary", usage=UsageMetadata(input_tokens=12, output_tokens=3))
    agent, events, ledger, _ = fake_agent(monkeypatch, tmp_path, response)

    def send(_prompt):
        agent._molt_count = 5
        agent._config.model = "later-model"
        return response

    agent.service.create_session = lambda **kw: SimpleNamespace(send=send)
    turn._build_apriori_summarizer_fn(agent)("system", "user", "shell", "tool-1")
    assert events[0]["api_call_id"].startswith("api_")
    assert events[0]["molt_count"] == 4
    assert events[0]["usage_billing"]["model"] == "configured-alias"
    assert ledger[0]["extra"]["molt_count"] == 4


@pytest.mark.parametrize("args", [{}, {"summary": False}, {"summary": 1}])
def test_no_default_summary_parallel_policy_change(args):
    raw = {"data": "raw"}
    def forbidden(*_args):
        raise AssertionError("summary provider must not be called by default")
    assert maybe_summarize_result(
        raw, args=args, tool_name="shell", tool_call_id="tool", summarizer_fn=forbidden,
    ) is raw


def test_summary_counts_dedup_and_parent_lane_unchanged():
    p, h = parent(), helper()
    original = deepcopy(p)
    base, _ = fold([p])
    state, cost = fold([p, h, h, {"type": "notification_block_injected"}])
    metadata = Projection.session_usage_metadata(state)
    assert metadata["api_calls"] == 2
    assert metadata["input_tokens"] == 2000
    assert metadata["output_tokens"] == 300
    assert metadata["cached_tokens"] == 200
    assert metadata["cache_miss_tokens"] == 1800
    assert metadata["session_cache_rate"] == .1
    assert metadata["avg_input_tokens_per_api_call"] == 1000
    assert metadata["cache_miss_remaining_tokens"] == 1_998_200
    for key in ("snapshot", "metadata", "api_call_index", "molt_count"):
        assert state[key] == base[key]
    for key in ("context_tokens", "context_window", "context_usage"):
        assert metadata[key] == base["metadata"][key]
    assert Projection.project_llm_response_usage(h) is None
    assert Projection.project_current_call_usage(h) is None
    delta, _ = Projection.reduce_input_delta_event(None, p)
    assert Projection.reduce_input_delta_event(delta, h) == (delta, None)
    assert p == original
    assert len(cost["bills"]) == len(cost["summary_bills"]) == 1


def test_exact_public_price_total_and_disjoint_buckets():
    state, cost = fold([parent(), helper()])
    bill = cost["summary_bills"]["summary-1"]
    parts, floors = estimate_parts(bill, PUBLIC_PRICES)
    assert not floors
    assert parts["miss"] == pytest.approx(.0021 + .000375)
    assert parts["hit"] == pytest.approx(.00006)
    assert parts["output"] == pytest.approx(.003)
    assert session_cost_text(cost, OfflineCatalog()) == (
        "total ~$0.0100 · in $0.0051 · write $0.0004 · read <$0.0001 · out $0.0045"
    )
    assert "summary" not in session_cost_text(cost, OfflineCatalog())  # no new subtotal/layout
    assert Projection.session_usage_metadata(state)["output_tokens"] == 300


def test_missing_write_ttl_keeps_price_partial_even_after_receipt_gap_closes():
    # Positive writes with distinct 5m/1h rates need an established TTL split.
    h = helper()
    h["usage_billing"].pop("cache_write_1h_tokens")
    outcome = {"type": "apriori_summary_generated", "tool_call_id": h["tool_call_id"]}
    state, cost = fold([parent(), outcome, h])
    assert state["summary_gaps"] == {}
    assert Projection.session_usage_metadata(state)["api_calls"] == 2
    bill = cost["summary_bills"]["summary-1"]
    assert "cache_write_1h_tokens" not in bill  # projection must not invent zero
    parts, floors = estimate_parts(bill, PUBLIC_PRICES)
    assert not floors and parts["miss"] is None
    assert parts["hit"] == pytest.approx(.00006)
    assert parts["output"] == pytest.approx(.003)
    assert session_cost_text(cost, OfflineCatalog()) == (
        "total ≥$0.0076 · in $0.0030+ · write $0+ · read <$0.0001 · out $0.0045 · partial"
    )


def test_receipt_before_first_parent_and_later_snapshots_do_not_erase_it():
    state, cost = fold([helper(), parent(), parent(2)])
    assert Projection.session_usage_metadata(state)["api_calls"] == 3
    assert len(cost["summary_bills"]) == 1
    assert state["api_call_index"] == 2


@pytest.mark.parametrize("event", [helper(generation=1), helper(em_id="child"),
                                     helper(run_id="other-run"), helper(source="daemon")])
def test_foreign_or_wrong_generation_receipt_never_counts(event):
    state, cost = fold([parent(), event])
    assert Projection.session_usage_metadata(state)["api_calls"] == 1
    assert cost["summary_bills"] == {}


def test_molt_resets_both_aggregates_and_stale_molt_does_not_erase_current():
    events = [parent(), helper(), {"type": "psyche_molt", "molt_count": 1},
              parent(generation=1), helper("new", generation=1),
              helper("old", generation=0),
              {"type": "apriori_summary_generated", "tool_call_id": "tool-old"},
              {"type": "psyche_molt", "molt_count": 0}]
    state, cost = fold(events)
    assert Projection.session_usage_metadata(state)["api_calls"] == 2
    assert list(cost["summary_bills"]) == ["new"]
    state, cost = fold([*events, {"type": "psyche_molt"}, helper("uncertain", generation=1)])
    assert Projection.session_usage_metadata(state) == {}
    assert cost is None
    assert state["summary_receipts"] == {}


@pytest.mark.parametrize("change", [{"input_tokens": None}, {"cached_tokens": True},
                                      {"cached_tokens": 1001}, {"estimated": True}])
def test_unknown_receipt_usage_is_not_zero_but_return_count_is_known(change):
    state, cost = fold([parent(), helper(**change)])
    metadata = Projection.session_usage_metadata(state)
    assert metadata["api_calls"] == 2
    assert "input_tokens" not in metadata
    assert metadata["context_tokens"] == 1000
    text = session_cost_text(cost, OfflineCatalog())
    assert "total ≥$0.0045" in text and text.endswith("partial")


@pytest.mark.parametrize("kind", ["apriori_summary_generated", "apriori_summary_empty", "apriori_summary_failed"])
def test_missing_receipt_scope_gap_is_partial_not_exception_usage(kind):
    outcome = {"type": kind, "tool_call_id": "tool-summary-1"}
    state, cost = fold([parent(), outcome])
    metadata = Projection.session_usage_metadata(state)
    assert "api_calls" not in metadata and "input_tokens" not in metadata
    assert metadata["context_tokens"] == 1000
    assert session_cost_text(cost, OfflineCatalog()).endswith("partial")
    state, cost = fold([parent(), outcome, helper()])
    assert Projection.session_usage_metadata(state)["api_calls"] == 2
    assert not session_cost_text(cost, OfflineCatalog()).endswith("partial")


def test_thrown_exception_has_no_normalized_receipt(monkeypatch, tmp_path):
    agent, events, ledger, _ = fake_agent(monkeypatch, tmp_path, None)
    def send(_prompt):
        raise RuntimeError("provider failed")
    agent.service.create_session = lambda **kw: SimpleNamespace(send=send)
    maybe_summarize_result(
        {"data": "raw"}, args={"summary": True}, tool_name="shell", tool_call_id="tool-1",
        summarizer_fn=turn._build_apriori_summarizer_fn(agent), logger_fn=agent._log,
    )
    assert ledger == []
    assert [e["type"] for e in events] == ["apriori_summary_failed"]


def test_unknown_price_tier_write_counts_and_stale_qualification():
    _, cost = fold([parent(), helper(usage_billing={"model": "unlisted", "billable_output_tokens": 200})])
    assert "partial" in session_cost_text(cost, OfflineCatalog())
    _, cost = fold([parent(), helper(usage_billing={"model": MODEL, "service_tier": "priority",
                                                  "billable_output_tokens": 200})])
    text = session_cost_text(cost, OfflineCatalog())
    assert "partial" in text and "requested-tier est." in text
    assert "stale prices" in session_cost_text(cost, OfflineCatalog(status="stale"))
    _, cost = fold([helper(usage_billing={"model": "unlisted"})])
    assert session_cost_text(cost, OfflineCatalog()) == (
        "total ? · in ? · write ? · read ? · out ? · partial"
    )


def test_legacy_metadata_without_helpers_preserves_original_fields():
    state = {"source": "legacy", "metadata": {"context_tokens": 123}}
    assert Projection.session_usage_metadata(state) == {"context_tokens": 123}


def test_accounting_sink_failures_are_independent(monkeypatch, tmp_path):
    response = LLMResponse(text="summary", usage=UsageMetadata(input_tokens=12, output_tokens=3))
    agent, events, ledger, _ = fake_agent(monkeypatch, tmp_path, response)
    def fail_log(*args, **kwargs):
        raise OSError("journal unavailable")
    agent._log = fail_log
    assert turn._build_apriori_summarizer_fn(agent)("system", "user", "shell", "tool") == "summary"
    assert len(ledger) == 1
    agent._log = lambda kind, **fields: events.append({"type": kind, **fields})
    def fail_ledger(*args, **kwargs):
        raise OSError("ledger unavailable")
    monkeypatch.setattr(turn, "append_token_entry", fail_ledger)
    assert turn._build_apriori_summarizer_fn(agent)("system", "user", "shell", "tool") == "summary"
    assert events[-1]["type"] == "apriori_summary_usage"


def test_manager_append_and_rehydrate_consume_the_same_receipt_lane(tmp_path):
    import json
    from tests.test_telegram_task_card_transport import _make_manager

    path = tmp_path / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True)
    events = [parent(), helper(), {
        "type": "apriori_summary_generated", "tool_call_id": "tool-summary-1", "ts": 2.0,
    }]
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    live, _ = _make_manager(tmp_path)
    live._append_new_lines(path, 0, path.stat().st_size)
    replay, _ = _make_manager(tmp_path)
    replay._init_event_tail()
    assert live._task_card_event_metadata == replay._task_card_event_metadata
    assert live._task_card_event_metadata["api_calls"] == 2
    assert live._task_card_session_cost_state == replay._task_card_session_cost_state
    assert live._task_card_session_cost_state["summary_bills"]
    original = deepcopy(live._task_card_event_metadata)
    offset = path.stat().st_size
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(helper()) + "\n")
    live._append_new_lines(path, offset, path.stat().st_size)
    assert live._task_card_event_metadata == original


def test_billable_output_includes_thinking_once_and_one_hour_write_rate():
    h = helper(usage_billing={"model": MODEL, "cache_write_tokens": 100,
                              "cache_write_1h_tokens": 25, "billable_output_tokens": 230})
    _, cost = fold([parent(), h])
    bill = cost["summary_bills"]["summary-1"]
    parts, floors = estimate_parts(bill, PUBLIC_PRICES)
    assert not floors
    assert parts["output"] == pytest.approx(230 * 15e-6)  # not 230 + thinking again
    assert parts["miss"] == pytest.approx(700 * 3e-6 + 75 * 3.75e-6 + 25 * 6e-6)


def test_requested_priority_price_fields_are_not_standard_or_applied_tier_proof():
    # Synthetic tier-shape fixture only, not public Sonnet priority rates.
    entry = dict(PUBLIC_PRICES)
    entry.update({key + "_priority": value * 2 for key, value in PUBLIC_PRICES.items()})
    h = helper(usage_billing={"model": MODEL, "service_tier": "priority",
                             "cache_write_tokens": 100, "cache_write_1h_tokens": 0,
                             "billable_output_tokens": 200})
    _, cost = fold([parent(), h])
    text = session_cost_text(cost, OfflineCatalog(entry))
    assert text.startswith("total ~$0.0156")  # standard parent + doubled requested-tier helper
    assert text.endswith("requested-tier est.") and "partial" not in text
