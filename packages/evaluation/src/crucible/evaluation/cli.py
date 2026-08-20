"""Evaluation CLI.

    # Compare the reference config against the frozen baseline and gate:
    python -m crucible.evaluation run --suite evals/suites/core-v1.0.0.yaml \
        --baseline evals/baseline.json --executor docker --out evals/reports

    # (Re)generate the baseline evidence for the reference config:
    python -m crucible.evaluation baseline --suite evals/suites/core-v1.0.0.yaml \
        --executor docker --out evals/baseline.json --approved-by you

Exit code is non-zero when the gate BLOCKs, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from crucible.agent import FakeModel, ModelGateway, OpenAICompatModel
from crucible.agent.models.fake import POLICY_VERSION, PROMPT_VERSION
from crucible.agent.models.registry import register_openrouter_free_model
from crucible.evaluation.comparator import GateStatus, evaluate_gate
from crucible.evaluation.config import EvalConfig
from crucible.evaluation.governance import baseline_from_result, load_baseline, write_baseline
from crucible.evaluation.loader import load_fixture, load_suite
from crucible.evaluation.report import build_report, render_markdown
from crucible.evaluation.runner import ExperimentResult, ExperimentRunner
from crucible.evaluation.schemas import EvalSuite
from crucible.execution import (
    DEFAULT_IMAGE,
    DockerExecutor,
    ExecutionLimits,
    Executor,
    FakeExecutor,
)

_SANDBOX_WORK_ROOT = Path(__file__).resolve().parents[5] / ".sandbox_runs"


def _git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


def _build_executor(name: str) -> Executor:
    if name == "docker":
        return DockerExecutor(image=DEFAULT_IMAGE, work_root=_SANDBOX_WORK_ROOT)
    # The fake executor returns no value, so correctness scores will be 0 — useful
    # only for a wiring dry-run, never for real evidence.
    return FakeExecutor()


def _build_model(args: argparse.Namespace) -> tuple[ModelGateway, str, str]:
    """Model + (model_backend, model_variant) for the report's manifest — the
    project's own principle 5 (version every behavior-changing input) means a
    real-model report must not still say `model_backend: fake`.

    No two-tier routing here — that's the `router` subcommand's job. The API
    key always comes from OPENAI_API_KEY (never a CLI flag), so it can't leak
    into shell history or CI logs.
    """
    if args.model_backend == "fake":
        return FakeModel(), "fake", "reference"
    if not args.model or not args.base_url:
        raise SystemExit("--model-backend openai_compat requires --model and --base-url")
    if args.model.endswith(":free"):
        register_openrouter_free_model(args.model)
    model = OpenAICompatModel(
        base_url=args.base_url,
        api_key=os.environ.get("OPENAI_API_KEY"),
        model=args.model,
        max_attempts=args.max_attempts,
        backoff_base_seconds=args.backoff_base,
    )
    return model, "openai_compat", args.model


def _reference_config(executor_backend: str, model_backend: str, model_variant: str) -> EvalConfig:
    return EvalConfig(
        id="reference@1",
        model_backend=model_backend,
        executor_backend=executor_backend,
        prompt_version=PROMPT_VERSION,
        policy_version=POLICY_VERSION,
        model_variant=model_variant,
        limits={"wall_seconds": 25.0},
    )


async def _run_reference(
    args: argparse.Namespace, suite_path: str, executor_backend: str, smoke: bool
) -> tuple[EvalSuite, ExperimentResult]:
    suite = load_suite(suite_path)
    if smoke:
        suite = suite.smoke_suite()
    fixture, content = load_fixture(suite.fixture)
    model, model_backend, model_variant = _build_model(args)
    runner = ExperimentRunner(
        model=model,
        executor=_build_executor(executor_backend),
        limits=ExecutionLimits(wall_seconds=25),
        config=_reference_config(executor_backend, model_backend, model_variant),
    )
    return suite, await runner.run(suite, fixture, content)


def cmd_run(args: argparse.Namespace) -> int:
    suite, result = asyncio.run(_run_reference(args, args.suite, args.executor, args.smoke))
    baseline = load_baseline(args.baseline)

    if baseline.suite_hash != suite.content_hash:
        print(
            f"WARNING: suite content hash changed ({suite.content_hash} != baseline "
            f"{baseline.suite_hash}); the baseline must be reviewed and regenerated.",
            file=sys.stderr,
        )

    gate = evaluate_gate(baseline.scores(), result.scores, tolerance=baseline.tolerance)
    tags = {c.id: c.tags for c in suite.cases}
    report = build_report(
        candidate=result,
        baseline=baseline,
        gate=gate,
        git_sha=_git_sha(),
        generated_at=datetime.now(UTC).isoformat(),
        suite_cases_tags=tags,
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{suite.id}-{result.config.config_hash}"
    (out / f"{stem}.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out / f"{stem}.md").write_text(render_markdown(report), encoding="utf-8")

    print(
        f"gate={gate.status.value} delta={gate.delta} ci=[{gate.ci_lo}, {gate.ci_hi}] "
        f"accuracy={result.accuracy}"
    )
    for reason in gate.reasons:
        print(f"  - {reason}")
    print(f"report: {out / (stem + '.json')}")
    return 1 if gate.status is GateStatus.BLOCK else 0


def cmd_baseline(args: argparse.Namespace) -> int:
    _suite, result = asyncio.run(_run_reference(args, args.suite, args.executor, smoke=False))
    baseline = baseline_from_result(
        result,
        approved_by=args.approved_by,
        approved_at=datetime.now(UTC).date().isoformat(),
        notes=args.notes,
        tolerance=args.tolerance,
    )
    write_baseline(baseline, args.out)
    print(
        f"baseline written: {args.out} (accuracy {baseline.accuracy}, {len(baseline.per_case)} cases)"
    )
    return 0


def cmd_router(args: argparse.Namespace) -> int:
    """The held-out router experiment: the same suite under the default and
    the two-tier routed policy, reported side by side (Phase 8)."""
    from crucible.evaluation.efficiency import render_router_markdown, run_router_experiment

    suite = load_suite(args.suite)
    fixture, content = load_fixture(suite.fixture)
    report = asyncio.run(
        run_router_experiment(
            suite,
            fixture,
            content,
            executor=_build_executor(args.executor),
            limits=ExecutionLimits(wall_seconds=25),
            git_sha=_git_sha(),
        )
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if args.md:
        md = Path(args.md)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_router_markdown(report), encoding="utf-8")
    for policy in report["policies"]:
        print(
            f"{policy['policy_id']}: accuracy={policy['accuracy']} "
            f"cost=${policy['total_cost_usd']} p95={policy['p95_latency_ms']}ms "
            f"escalations={policy['escalations']} n={policy['n_cases']}"
        )
    for policy_id, gate in report["quality_gates"].items():
        print(f"quality[{policy_id}]: {gate['status']} delta={gate['delta']}")
    blocked = any(g["status"] == "block" for g in report["quality_gates"].values())
    return 1 if blocked else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crucible.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a candidate and gate against the baseline")
    run.add_argument("--suite", required=True)
    run.add_argument("--baseline", required=True)
    run.add_argument("--executor", choices=["docker", "fake"], default="docker")
    run.add_argument("--model-backend", choices=["fake", "openai_compat"], default="fake")
    run.add_argument("--model", default=None, help="model id (openai_compat only)")
    run.add_argument("--base-url", default=None, help="provider base URL (openai_compat only)")
    run.add_argument(
        "--max-attempts",
        type=int,
        default=6,
        help="provider call attempts before giving up (free tiers rate-limit hard)",
    )
    run.add_argument(
        "--backoff-base",
        type=float,
        default=4.0,
        help="base seconds for exponential backoff between provider retries",
    )
    run.add_argument("--smoke", action="store_true")
    run.add_argument("--out", default="evals/reports")
    run.set_defaults(func=cmd_run)

    base = sub.add_parser("baseline", help="generate baseline evidence")
    base.add_argument("--suite", required=True)
    base.add_argument("--executor", choices=["docker", "fake"], default="docker")
    base.add_argument("--model-backend", choices=["fake", "openai_compat"], default="fake")
    base.add_argument("--model", default=None, help="model id (openai_compat only)")
    base.add_argument("--base-url", default=None, help="provider base URL (openai_compat only)")
    base.add_argument(
        "--max-attempts",
        type=int,
        default=6,
        help="provider call attempts before giving up (free tiers rate-limit hard)",
    )
    base.add_argument(
        "--backoff-base",
        type=float,
        default=4.0,
        help="base seconds for exponential backoff between provider retries",
    )
    base.add_argument("--out", default="evals/baseline.json")
    base.add_argument("--approved-by", default="")
    base.add_argument("--notes", default="")
    base.add_argument("--tolerance", type=float, default=0.02)
    base.set_defaults(func=cmd_baseline)

    router = sub.add_parser("router", help="run the held-out router experiment (Phase 8)")
    router.add_argument("--suite", required=True)
    router.add_argument("--executor", choices=["docker", "fake"], default="docker")
    router.add_argument("--out", default="evals/reports/router-comparison.json")
    router.add_argument("--md", default="")
    router.set_defaults(func=cmd_router)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    # The Docker executor uses asyncio.to_thread (no async psycopg here), so the
    # default event loop is fine on every platform.
    sys.exit(main())
