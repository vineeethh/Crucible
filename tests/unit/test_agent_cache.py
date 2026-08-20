"""Exact answer cache: key isolation, hit/miss/store, and false-hit safety.

The cache is feature-flagged: `AgentContext.cache=None` (the default) keeps the
EXACT_CACHE node a pass-through. These tests inject an in-memory AnswerCache
and drive the real graph, asserting the executor is *not* invoked on a hit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from crucible.agent import (
    AnswerCache,
    CachedAnswer,
    ColumnView,
    FakeModel,
    compute_cache_key,
    config_signature,
    normalize_question,
    run_agent,
)
from crucible.execution import ExecutionLimits, ExecutionRequest, ExecutionResult, FakeExecutor
from tests.support.agent_fakes import InMemoryPersistence, exec_result

PROFILE = [
    ColumnView(name="region", dtype="String"),
    ColumnView(name="amount", dtype="Float64"),
]


@dataclass
class MemoryCache(AnswerCache):
    entries: dict[tuple[str, str], CachedAnswer] = field(default_factory=dict)
    hits: int = 0
    invalidated: list[str] = field(default_factory=list)

    async def lookup(self, *, organization_id: str, cache_key: str) -> CachedAnswer | None:
        return self.entries.get((organization_id, cache_key))

    async def store(
        self,
        *,
        organization_id: str,
        cache_key: str,
        dataset_version_id: str,
        dataset_sha256: str,
        question_sha256: str,
        config_signature: str,
        answer: dict[str, Any],
        verification: dict[str, Any] | None,
    ) -> None:
        self.entries[(organization_id, cache_key)] = CachedAnswer(
            cache_key=cache_key,
            dataset_sha256=dataset_sha256,
            config_signature=config_signature,
            answer=answer,
            verification=verification,
        )

    async def record_hit(self, *, organization_id: str, cache_key: str) -> None:
        self.hits += 1

    async def invalidate(self, *, organization_id: str, cache_key: str) -> None:
        self.entries.pop((organization_id, cache_key), None)
        self.invalidated.append(cache_key)


class CountingExecutor(FakeExecutor):
    def __init__(self, handler: Callable[[ExecutionRequest], ExecutionResult]) -> None:
        super().__init__(handler=handler)
        self.calls = 0

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.calls += 1
        return await super().execute(request)


def drive(
    p: InMemoryPersistence,
    cache: AnswerCache | None,
    *,
    run_id: str = "r1",
    executor: CountingExecutor | None = None,
) -> tuple[str, CountingExecutor]:
    ex = executor or CountingExecutor(
        handler=lambda req: exec_result(value=30.0, columns_used=["amount"])
    )
    outcome = asyncio.run(
        run_agent(
            p,
            model=FakeModel(),
            executor=ex,
            limits=ExecutionLimits(),
            run_id=run_id,
            cache=cache,
        )
    )
    return outcome, ex


# ------------------------------------------------------------------- key rules


def test_key_binds_tenant_dataset_config_and_question() -> None:
    base = {
        "organization_id": "org-a",
        "dataset_sha256": "sha-1",
        "config_sig": "cfg-1",
        "question": "total amount?",
    }
    key = compute_cache_key(**base)
    assert compute_cache_key(**{**base, "organization_id": "org-b"}) != key
    assert compute_cache_key(**{**base, "dataset_sha256": "sha-2"}) != key
    assert compute_cache_key(**{**base, "config_sig": "cfg-2"}) != key
    assert compute_cache_key(**{**base, "question": "mean amount?"}) != key


def test_question_normalization_is_whitespace_only() -> None:
    assert normalize_question("  total\n  amount ?  ") == "total amount ?"
    base = {"organization_id": "o", "dataset_sha256": "s", "config_sig": "c"}
    same = compute_cache_key(**base, question="total   amount?")
    assert compute_cache_key(**base, question="total amount?") == same
    # Case changes may change meaning (a column name): they must MISS.
    assert compute_cache_key(**base, question="Total amount?") != same


def test_config_signature_changes_with_any_model_config() -> None:
    a = config_signature({"planner": {"model_id": "m1", "prompt_version": "p1"}})
    b = config_signature({"planner": {"model_id": "m2", "prompt_version": "p1"}})
    assert a != b


# --------------------------------------------------------------- graph behavior


def test_flag_off_means_no_cache_activity() -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE)
    outcome, _ = drive(p, cache=None)
    assert outcome == "answered"
    assert not any(a.kind == "cache" for a in p.attempts)


def test_miss_then_store_then_hit_skips_the_sandbox() -> None:
    cache = MemoryCache()

    first = InMemoryPersistence()
    first.add_run("r1", question="What is the total amount?", profile=PROFILE)
    outcome, ex1 = drive(first, cache)
    assert outcome == "answered"
    assert ex1.calls == 1
    kinds = [(a.kind, a.payload.get("outcome")) for a in first.attempts if a.kind == "cache"]
    assert ("cache", "miss") in kinds and ("cache", "store") in kinds

    # Same org, same dataset content, same config, same question: a hit that
    # never touches the model or the sandbox.
    second = InMemoryPersistence()
    second.add_run("r2", question="What is the total amount?", profile=PROFILE)
    outcome2, ex2 = drive(second, cache, run_id="r2")
    assert outcome2 == "answered"
    assert ex2.calls == 0
    assert cache.hits == 1
    answer, _ = second.results["r2"]
    assert answer is not None and answer["cached"] is True
    assert answer["value"] == 30.0


def test_other_tenant_never_hits() -> None:
    cache = MemoryCache()
    first = InMemoryPersistence()
    first.add_run("r1", question="What is the total amount?", profile=PROFILE)
    drive(first, cache)

    other = InMemoryPersistence()
    other.add_run("r2", question="What is the total amount?", profile=PROFILE)
    other.runs["r2"].organization_id = "org-2"  # different tenant, same question
    _, ex = drive(other, cache, run_id="r2")
    assert ex.calls == 1  # computed fresh; no cross-tenant replay
    assert cache.hits == 0


def test_false_hit_is_invalidated_and_recomputed() -> None:
    cache = MemoryCache()
    first = InMemoryPersistence()
    first.add_run("r1", question="What is the total amount?", profile=PROFILE)
    drive(first, cache)

    # Corrupt the stored identity inputs: the entry now claims a different
    # dataset content hash. The node must refuse it, count a false hit, delete
    # the entry, and recompute.
    (key, entry) = next(iter(cache.entries.items()))
    cache.entries[key] = CachedAnswer(
        cache_key=entry.cache_key,
        dataset_sha256="tampered",
        config_signature=entry.config_signature,
        answer=entry.answer,
        verification=entry.verification,
    )

    second = InMemoryPersistence()
    second.add_run("r2", question="What is the total amount?", profile=PROFILE)
    outcome, ex = drive(second, cache, run_id="r2")
    assert outcome == "answered"
    assert ex.calls == 1  # recomputed, not served
    assert cache.invalidated  # the suspect entry was removed
    assert any(
        a.kind == "cache" and a.payload.get("outcome") == "false_hit" for a in second.attempts
    )


def test_abstained_runs_are_never_cached() -> None:
    cache = MemoryCache()
    p = InMemoryPersistence()
    p.add_run("r1", question="Write a poem about the data.", profile=PROFILE)
    outcome, _ = drive(p, cache)
    assert outcome == "abstained"
    assert not cache.entries


def test_review_routed_answers_are_never_cached() -> None:
    cache = MemoryCache()
    p = InMemoryPersistence()
    p.add_run("r1", question="Which region had the highest amount?", profile=PROFILE)
    ex = CountingExecutor(
        handler=lambda req: exec_result(value="north", columns_used=["region"], ambiguous=True)
    )
    outcome, _ = drive(p, cache, executor=ex)
    assert outcome == "interrupted"  # waiting for a reviewer
    assert not cache.entries  # a human decision is not a lookup
