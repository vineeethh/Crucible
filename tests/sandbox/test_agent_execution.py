"""Full agent pipeline against the REAL sandbox — the Phase 4 DoD.

The fake model plans and generates real polars code; the Docker executor runs it
in the hardened sandbox; the graph verifies and synthesizes. The answer is a
genuine computed value, not a scripted one — this proves plan → code → execute →
verify → answer end to end with real execution.
"""

from __future__ import annotations

import asyncio

import pytest

from crucible.agent import ColumnView, FakeModel, GeneratedCode, ModelRole, resolve_review, run_agent
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


def test_implausible_count_is_caught_then_self_corrects_on_revision(executor) -> None:
    """crucible.agent.policy.check_plausibility: a COUNT can never legitimately
    exceed the dataset's own row_count — that's not a judgment call, it's
    logically impossible for a correct program. A buggy FIRST coder response
    that hardcodes an inflated count is caught even though it executes
    cleanly and even though the metamorphic shuffle/reorder checks (which
    only compare the program's answer to ITSELF under transform, not to any
    external fact) would not catch a constant that never changes.

    This is the "re-iterate" behavior itself, not just detection: Node.REVISE
    calls the coder again with the verifier's critique, the plan itself was
    fine (a plain row count), so the regenerated program is correct — the run
    ends ANSWERED with the real value, not abstained. Detection without
    correction was Phase 1/2; this is Phase 3.
    """
    buggy_source = (
        "import json, os\n"
        "with open(os.environ['CRUCIBLE_RESULT_PATH'], 'w') as f:\n"
        "    json.dump({'value': 9999, 'operation': 'count', 'columns_used': []}, f)\n"
    )
    model = FakeModel(scripts={ModelRole.CODER: [GeneratedCode(source=buggy_source)]})
    p = InMemoryPersistence()
    p.add_run("r1", question="How many rows are there?", profile=PROFILE, content=CSV, row_count=3)

    outcome = asyncio.run(
        run_agent(
            p,
            model=model,
            executor=executor,
            limits=ExecutionLimits(wall_seconds=25),
            run_id="r1",
        )
    )

    assert outcome == "answered"
    answer, _ = p.results["r1"]
    assert answer["value"] == 3  # the real row count, not the buggy 9999
    verify_attempts = [a for a in p.attempts if a.kind == "verify"]
    assert len(verify_attempts) == 2  # caught on the first, passed on the second
    assert verify_attempts[0].payload["policy_ok"] is False
    assert any(
        "exceeds the dataset's row_count" in r for r in verify_attempts[0].payload["reasons"]
    )
    assert verify_attempts[1].payload["policy_ok"] is True
    assert any(a.kind == "revise_code" for a in p.attempts)


def test_row_order_dependent_program_is_caught_then_self_corrects_on_revision(executor) -> None:
    """crucible.agent.metamorphic: no gold answer exists for "what is the
    total amount" other than the one the program itself computes — so the
    only way to catch a program that is silently WRONG (reads df['amount'][0]
    instead of actually summing) is to notice its answer changes when it has
    no legitimate reason to. This deliberately-buggy FIRST program runs,
    produces a plausible-looking scalar, and is caught: the CHALLENGE node
    reruns it against a row-shuffled dataset and gets a different value.

    Node.REVISE then repairs it with that critique; the plan itself was fine
    (a plain sum), so the regenerated program is correct and the run ends
    ANSWERED with the real sum — the actual re-iterate-until-correct loop.
    """
    buggy_source = (
        "import polars as pl\n"
        "import json, os\n"
        "df = pl.read_csv(os.environ['CRUCIBLE_DATASET_PATH'])\n"
        "value = float(df['amount'][0])\n"  # first row only — order-dependent, not a sum
        "with open(os.environ['CRUCIBLE_RESULT_PATH'], 'w') as f:\n"
        "    json.dump({'value': value, 'operation': 'sum', 'columns_used': ['amount']}, f)\n"
    )
    model = FakeModel(scripts={ModelRole.CODER: [GeneratedCode(source=buggy_source)]})
    p = InMemoryPersistence()
    p.add_run("r1", question="What is the total amount?", profile=PROFILE, content=CSV)

    outcome = asyncio.run(
        run_agent(
            p,
            model=model,
            executor=executor,
            limits=ExecutionLimits(wall_seconds=25),
            run_id="r1",
        )
    )

    assert outcome == "answered"
    answer, _ = p.results["r1"]
    assert answer["value"] == 60.0  # the real sum (10+20+30), not one row's value
    assert any(a.kind == "revise_code" for a in p.attempts)


def test_persistent_verification_failure_exhausts_revisions_to_human_review(executor) -> None:
    """When the SAME wrong answer recurs after a revision (the oscillation
    guard's fingerprint matches), Node.REVISE stops trying automatically and
    routes to human review instead of spinning — the bounded half of "close
    the loop": iterate, but not forever."""
    buggy_source = (
        "import json, os\n"
        "with open(os.environ['CRUCIBLE_RESULT_PATH'], 'w') as f:\n"
        "    json.dump({'value': 9999, 'operation': 'count', 'columns_used': []}, f)\n"
    )
    model = FakeModel(
        scripts={
            ModelRole.CODER: [GeneratedCode(source=buggy_source)],
            ModelRole.REPAIR: [GeneratedCode(source=buggy_source)],  # same bug persists
        }
    )
    p = InMemoryPersistence()
    p.add_run("r1", question="How many rows are there?", profile=PROFILE, content=CSV, row_count=3)

    outcome = asyncio.run(
        run_agent(
            p,
            model=model,
            executor=executor,
            limits=ExecutionLimits(wall_seconds=25),
            run_id="r1",
        )
    )

    assert outcome == "interrupted"
    assert p.status_of("r1") == "waiting_review"
    revise_attempts = [a for a in p.attempts if a.kind == "revise_code"]
    assert len(revise_attempts) == 1  # the oscillation guard stopped it, not the cap
    verify_attempts = [a for a in p.attempts if a.kind == "verify"]
    assert len(verify_attempts) == 2
    assert all(not v.payload["policy_ok"] for v in verify_attempts)

    # A human reviews, supplies feedback, and asks for another try — this time
    # with a fresh (unscripted) model, so the regenerated code is correct.
    resolved = asyncio.run(
        resolve_review(
            p,
            model=FakeModel(),
            executor=executor,
            limits=ExecutionLimits(wall_seconds=25),
            run_id="r1",
            decision="revise",
            feedback="the count looks wrong, please recompute it directly from the data",
        )
    )
    assert resolved == "answered"
    assert p.status_of("r1") == "answered"
    answer, _ = p.results["r1"]
    assert answer["value"] == 3  # the real row count


def test_genuine_tie_is_not_flagged_as_a_metamorphic_violation(executor) -> None:
    """Regression: a tie has more than one equally correct answer, and a
    row shuffle is legitimately allowed to flip WHICH tied value the program
    reports — that's what "tie" means, not evidence of a bug. Node.CHALLENGE
    must skip the check entirely for a result the program itself already
    flagged `ambiguous`, or a genuinely honest tied answer gets wrongly
    caught in the revision loop and never reaches human review as intended.
    """
    tied_csv = b"region,amount,customer_id\nnorth,10,c1\nsouth,10,c2\n"
    p = InMemoryPersistence()
    p.add_run("r1", question="Which region had the highest amount?", profile=PROFILE, content=tied_csv)

    outcome = _run(p, executor)

    assert outcome == "interrupted"  # routed straight to review, not abstained
    assert p.status_of("r1") == "waiting_review"
    verify_attempts = [a for a in p.attempts if a.kind == "verify"]
    assert len(verify_attempts) == 1  # no revision loop was ever entered
    vector = verify_attempts[0].payload
    assert vector["policy_ok"] is True  # the tie is a REVIEW, not a policy failure
    assert vector["ambiguous"] is True
    assert vector["metamorphic_checks"] == []  # skipped, not run and failed
    assert not any(a.kind in ("revise_plan", "revise_code") for a in p.attempts)
