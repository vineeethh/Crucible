"""Reports: a machine-readable manifest and a human-readable Markdown summary.

The manifest carries everything needed to reproduce and audit the score: git
SHA, suite/fixture/config hashes, scorer version, per-case results, the paired
delta with its confidence interval, the gate verdict, efficiency, and the
failure-taxonomy distribution. A content hash over the deterministic parts
(everything except the wall-clock timestamp) lets a reader confirm a re-run
produced the identical result.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from crucible.evaluation.comparator import GateDecision
from crucible.evaluation.governance import Baseline
from crucible.evaluation.runner import ExperimentResult
from crucible.evaluation.scorers import SCORER_VERSION

REPORT_SCHEMA = 1


def build_report(
    *,
    candidate: ExperimentResult,
    baseline: Baseline,
    gate: GateDecision,
    git_sha: str,
    generated_at: str,
    suite_cases_tags: dict[str, list[str]],
) -> dict[str, object]:
    baseline_scores = baseline.scores()
    case_rows = []
    taxonomy: Counter[str] = Counter()
    total_latency = 0
    total_cost = 0.0
    for cid, score in candidate.scores.items():
        outcome = candidate.outcomes[cid]
        b_correct = baseline_scores[cid].correct if cid in baseline_scores else None
        total_latency += outcome.latency_ms
        total_cost += outcome.cost_usd
        if outcome.failure_category:
            taxonomy[outcome.failure_category] += 1
        case_rows.append(
            {
                "id": cid,
                "tags": suite_cases_tags.get(cid, []),
                "baseline_correct": b_correct,
                "candidate_correct": score.correct,
                "delta": (int(score.correct) - int(b_correct)) if b_correct is not None else None,
                "policy_ok": score.policy_ok,
                "policy_failures": list(score.policy_failures),
                "candidate": {
                    "terminal": outcome.terminal,
                    "value": outcome.value,
                    "answer_kind": outcome.answer_kind,
                    "exit_class": outcome.exit_class,
                    "failure_category": outcome.failure_category,
                    "latency_ms": outcome.latency_ms,
                    "cost_usd": outcome.cost_usd,
                    "attempts": outcome.attempt_count,
                },
                "detail": score.detail,
            }
        )

    body: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "git_sha": git_sha,
        "scorer_version": SCORER_VERSION,
        "suite": {
            "id": candidate.suite_id,
            "version": candidate.suite_version,
            "hash": candidate.suite_hash,
        },
        "fixture": {"id": candidate.fixture_id, "sha256": candidate.fixture_sha256},
        "baseline": {
            "config_id": baseline.config_id,
            "config_hash": baseline.config_hash,
            "accuracy": baseline.accuracy,
        },
        "candidate": {
            "config_id": candidate.config.id,
            "config_hash": candidate.config.config_hash,
            "accuracy": candidate.accuracy,
        },
        "gate": {
            "status": gate.status.value,
            "delta": gate.delta,
            "ci_lo": gate.ci_lo,
            "ci_hi": gate.ci_hi,
            "tolerance": gate.tolerance,
            "reasons": gate.reasons,
            "correctness_regressions": gate.correctness_regressions,
            "policy_regressions": gate.policy_regressions,
        },
        "efficiency": {
            "candidate_total_latency_ms": total_latency,
            "candidate_total_cost_usd": round(total_cost, 6),
            "cases": len(candidate.scores),
        },
        "failure_taxonomy": dict(sorted(taxonomy.items())),
        "cases": case_rows,
    }
    body["content_sha256"] = _content_hash(body)
    return {"generated_at": generated_at, **body}


def _content_hash(body: dict[str, object]) -> str:
    canonical = json.dumps(body, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_markdown(report: dict[str, Any]) -> str:
    gate = report["gate"]
    suite = report["suite"]
    baseline = report["baseline"]
    candidate = report["candidate"]
    lines = [
        f"# Evaluation report — suite `{suite['id']}` v{suite['version']}",
        "",
        f"- generated: {report['generated_at']}",
        f"- git: `{report['git_sha']}`  scorer: `{report['scorer_version']}`",
        f"- baseline `{baseline['config_id']}` ({baseline['config_hash']}) accuracy {baseline['accuracy']}",
        f"- candidate `{candidate['config_id']}` ({candidate['config_hash']}) accuracy {candidate['accuracy']}",
        "",
        f"## Gate: **{str(gate['status']).upper()}**",
        "",
        f"paired delta **{gate['delta']}**, 95% CI **[{gate['ci_lo']}, {gate['ci_hi']}]**, "
        f"tolerance {gate['tolerance']}",
        "",
    ]
    lines += [f"- {reason}" for reason in gate["reasons"]]
    lines += [
        "",
        "## Per-case",
        "",
        "| case | tags | base | cand | Δ | terminal | value | ms | policy |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report["cases"]:
        c = row["candidate"]
        base = "✓" if row["baseline_correct"] else ("·" if row["baseline_correct"] is None else "✗")
        cand = "✓" if row["candidate_correct"] else "✗"
        policy = "ok" if row["policy_ok"] else "FAIL:" + ",".join(row["policy_failures"])
        lines.append(
            f"| {row['id']} | {','.join(row['tags'])} | {base} | {cand} | {row['delta']} | "
            f"{c['terminal']} | {c['value']} | {c['latency_ms']} | {policy} |"
        )
    lines += ["", f"content_sha256: `{report['content_sha256']}`", ""]
    return "\n".join(lines)
