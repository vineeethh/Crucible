"""FakeModel planner intent parsing, deterministic codegen, and the OpenAI-
compatible adapter's pure parsing, deny-by-default, and real-HTTP behavior."""

import asyncio
import json
import time

import httpx
import pytest

from crucible.agent import (
    AnswerKind,
    ColumnView,
    FakeModel,
    ModelNotConfigured,
    ModelUnavailable,
    Operation,
)
from crucible.agent.models import registry
from crucible.agent.models.codegen import generate_source
from crucible.agent.models.openai_compat import OpenAICompatModel, parse_plan

PROFILE = [
    ColumnView(name="region", dtype="String"),
    ColumnView(name="product", dtype="String"),
    ColumnView(name="amount", dtype="Float64"),
    ColumnView(name="quantity", dtype="Int64"),
    ColumnView(name="customer_id", dtype="String"),
]


def _plan(question: str):
    return asyncio.run(FakeModel().plan(question=question, profile=PROFILE))[0]


def test_planner_detects_sum() -> None:
    plan = _plan("What is the total amount?")
    assert plan.operation is Operation.SUM
    assert plan.target_column == "amount"
    assert plan.answer_kind is AnswerKind.NUMERIC_SCALAR


def test_planner_detects_mean() -> None:
    plan = _plan("What is the average amount?")
    assert plan.operation is Operation.MEAN
    assert plan.target_column == "amount"


def test_planner_detects_distinct_with_plural() -> None:
    plan = _plan("How many distinct customers are there?")
    assert plan.operation is Operation.COUNT_DISTINCT
    assert plan.target_column == "customer_id"


def test_planner_detects_missing() -> None:
    plan = _plan("How many rows are missing a region?")
    assert plan.operation is Operation.MISSING_COUNT
    assert plan.target_column == "region"


def test_planner_detects_max_by_group() -> None:
    plan = _plan("Which region had the highest total amount?")
    assert plan.operation is Operation.MAX_BY_GROUP
    assert plan.group_column == "region"
    assert plan.target_column == "amount"


def test_planner_detects_group_count_without_numeric_target() -> None:
    plan = _plan("Which product appears the most?")
    assert plan.operation is Operation.MAX_BY_GROUP
    assert plan.group_column == "product"
    assert plan.target_column is None


def test_planner_plain_count() -> None:
    plan = _plan("How many orders are there?")
    assert plan.operation is Operation.COUNT
    assert plan.answer_kind is AnswerKind.INTEGER_SCALAR


def test_planner_abstains_on_unsupported_question() -> None:
    plan = _plan("Predict next quarter's revenue and explain why.")
    assert plan.is_abstain


def test_planner_abstains_when_no_column_matches() -> None:
    plan = _plan("What is the total elevation?")
    assert plan.is_abstain


@pytest.mark.parametrize(
    "question",
    [
        "What is the total amount?",
        "How many distinct customers?",
        "Which region had the highest amount?",
        "How many orders?",
        "average quantity",
        "how many rows are missing amount",
    ],
)
def test_generated_code_compiles(question: str) -> None:
    """Every plan the fake model can produce must compile to valid Python."""
    plan = _plan(question)
    source = generate_source(plan)
    compile(source, "<generated>", "exec")  # raises SyntaxError on bad codegen
    assert "CRUCIBLE_RESULT_PATH" in source


def test_codegen_escapes_hostile_column_names() -> None:
    """A malicious column name cannot break out of the generated string literal
    (repr neutralizes it; the sandbox contains anything anyway)."""
    hostile = [ColumnView(name="'); import os; os.system('x", dtype="Float64")]
    plan = asyncio.run(FakeModel().plan(question="total amount", profile=PROFILE))[0]
    hostile_step = plan.steps[0].model_copy(
        update={"target_column": hostile[0].name, "operation": Operation.SUM}
    )
    plan = plan.model_copy(update={"steps": [hostile_step]})
    source = generate_source(plan)
    compile(source, "<generated>", "exec")  # still valid Python
    assert "os.system" not in source.replace(repr(hostile[0].name), "")


# ------------------------------------------------------- openai-compatible path


def test_parse_plan_validates_into_schema() -> None:
    plan = parse_plan(
        '{"operation": "sum", "answer_kind": "numeric_scalar", "target_column": "amount"}'
    )
    assert plan.operation is Operation.SUM


def test_parse_plan_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        parse_plan("[1, 2, 3]")


def test_openai_model_is_deny_by_default() -> None:
    model = OpenAICompatModel()  # unconfigured
    assert not model.configured
    with pytest.raises(ModelNotConfigured):
        asyncio.run(model.plan(question="total amount", profile=PROFILE))


def _chat_response(
    content: dict[str, object], *, prompt_tokens: int = 40, completion_tokens: int = 12
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


_PLAN_CONTENT = {
    "operation": "sum",
    "answer_kind": "numeric_scalar",
    "target_column": "amount",
    "rationale": "sum of amount",
}


def test_openai_model_plan_success_uses_real_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        return _chat_response(_PLAN_CONTENT, prompt_tokens=40, completion_tokens=12)

    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        transport=httpx.MockTransport(handler),
    )
    plan, usage = asyncio.run(model.plan(question="total amount", profile=PROFILE))

    assert plan.operation is Operation.SUM
    assert usage.provider == "openai-compatible"
    assert usage.model_id == "some/model:free"
    assert usage.tokens_in == 40
    assert usage.tokens_out == 12
    # Unregistered model: cost stays the honest "unknown" marker, never a guess.
    assert usage.cost_usd is None


def test_openai_model_cost_computed_for_registered_model() -> None:
    registry.register(
        registry.ModelSpec(
            provider="openrouter",
            model_id="priced/model:test",
            tier=1,
            input_usd_per_mtok=1.0,
            output_usd_per_mtok=2.0,
        )
    )
    handler = httpx.MockTransport(
        lambda request: _chat_response(_PLAN_CONTENT, prompt_tokens=1000, completion_tokens=500)
    )
    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="priced/model:test",
        transport=handler,
    )
    _plan, usage = asyncio.run(model.plan(question="total amount", profile=PROFILE))
    assert usage.cost_usd == pytest.approx(0.001 * 1.0 + 0.0005 * 2.0)


def test_openai_model_retries_429_with_retry_after_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="rate limited")
        return _chat_response(_PLAN_CONTENT)

    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        max_attempts=3,
        backoff_base_seconds=0.0,
        transport=httpx.MockTransport(handler),
    )
    plan, _usage = asyncio.run(model.plan(question="total amount", profile=PROFILE))
    assert plan.operation is Operation.SUM
    assert calls["n"] == 2


def test_openai_model_caps_a_long_retry_after_instead_of_honoring_it() -> None:
    """A daily-quota Retry-After can be hours away — honoring it verbatim
    would block a configured router's fallback to a secondary provider for
    that whole duration (crucible.agent.router.RouterPolicy.fallback_on_error).
    The gateway caps how long it will actually wait."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"}, text="rate limited")
        return _chat_response(_PLAN_CONTENT)

    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        max_attempts=3,
        backoff_base_seconds=0.0,
        max_retry_after_seconds=0.05,
        transport=httpx.MockTransport(handler),
    )
    start = time.monotonic()
    plan, _usage = asyncio.run(model.plan(question="total amount", profile=PROFILE))
    elapsed = time.monotonic() - start
    assert plan.operation is Operation.SUM
    assert calls["n"] == 2
    assert elapsed < 1.0  # would be ~3600s if the header were honored verbatim


def test_openai_model_retries_exhausted_raises_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream error")

    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        max_attempts=2,
        backoff_base_seconds=0.0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ModelUnavailable):
        asyncio.run(model.plan(question="total amount", profile=PROFILE))


def test_openai_model_retries_on_connection_error_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return _chat_response(_PLAN_CONTENT)

    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        max_attempts=3,
        backoff_base_seconds=0.0,
        transport=httpx.MockTransport(handler),
    )
    plan, _usage = asyncio.run(model.plan(question="total amount", profile=PROFILE))
    assert plan.operation is Operation.SUM
    assert calls["n"] == 2


def test_openai_model_raises_on_non_retryable_status() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(400, text="bad request"))
    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        transport=handler,
    )
    with pytest.raises(ModelUnavailable):
        asyncio.run(model.plan(question="total amount", profile=PROFILE))


def test_openai_model_raises_on_malformed_completion_content() -> None:
    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "not json"}}], "usage": {}}
        )
    )
    model = OpenAICompatModel(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="some/model:free",
        transport=handler,
    )
    with pytest.raises(ValueError):
        asyncio.run(model.plan(question="total amount", profile=PROFILE))
