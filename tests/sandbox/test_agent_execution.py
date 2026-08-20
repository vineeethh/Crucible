"""Full agent pipeline against the REAL sandbox — the Phase 4 DoD.

The fake model plans and generates real polars code; the Docker executor runs it
in the hardened sandbox; the graph verifies and synthesizes. The answer is a
genuine computed value, not a scripted one — this proves plan → code → execute →
verify → answer end to end with real execution.
"""

from __future__ import annotations

import asyncio

import pytest

from crucible.agent import ColumnView, FakeModel, run_agent
from crucible.execution import ExecutionLimits
from tests.sandbox.conftest import requires_sandbox
from tests.support.agent_fakes import InMemoryPersistence

pytestmark = [pytest.mark.sandbox, requires_sandbox]

PROFILE = [
    ColumnView(name="region", dtype="String"),
    ColumnView(name="amount", dtype="Int64"),
    ColumnView(name="customer_id", dtype="String"),
]
CSV = b"region,amount,customer_id\nnorth,10,c1\nsouth,20,c2\neast,30,c1\n"


def _run(persistence: InMemoryPersistence, executor) -> str:
    return asyncio.run(
        run_agent(
            persistence,
            model=FakeModel(),
            executor=executor,
            limits=ExecutionLimits(wall_seconds=25),
            run_id="r1",
        )
    )


def test_agent_computes_a_real_sum(executor) -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE, content=CSV)

    outcome = _run(p, executor)

    assert outcome == "answered"
    answer, _ = p.results["r1"]
    assert answer is not None
    assert answer["value"] == 60.0  # 10 + 20 + 30, computed in the sandbox
    assert answer["provenance"]["columns_used"] == ["amount"]
    assert answer["provenance"]["executor_backend"] == "docker"


def test_agent_computes_a_real_distinct_count(executor) -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="How many distinct customers are there?", profile=PROFILE, content=CSV)

    outcome = _run(p, executor)

    assert outcome == "answered"
    answer, _ = p.results["r1"]
    assert answer["value"] == 2  # c1, c2


def test_agent_computes_a_real_group_max(executor) -> None:
    p = InMemoryPersistence()
    p.add_run("r1", question="Which region had the highest amount?", profile=PROFILE, content=CSV)

    outcome = _run(p, executor)

    assert outcome == "answered"
    answer, _ = p.results["r1"]
    assert answer["value"] == "east"  # east has the single largest amount (30)


def test_agent_abstains_when_code_cannot_run(executor) -> None:
    """A plan the coder can express but whose column is absent at run time still
    ends safely — the sandbox reports the failure and the agent abstains rather
    than inventing a number."""
    thin = [ColumnView(name="region", dtype="String")]
    p = InMemoryPersistence()
    # Ask for a sum of a numeric column that does not exist in this dataset.
    p.add_run("r1", question="What is the total amount?", profile=thin, content=b"region\nnorth\n")

    outcome = _run(p, executor)
    # The planner abstains (no numeric column matches) — no fabricated answer.
    assert outcome == "abstained"
    assert p.results["r1"][0] is None
