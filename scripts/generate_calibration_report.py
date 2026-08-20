"""Run the judge against the held-out human labels and publish the calibration
report (master plan §10.5 DoD: a published held-out agreement report).

    uv run python scripts/generate_calibration_report.py
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from crucible.evaluation import default_judge, load_holdout, run_calibration

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / "evals" / "calibration" / "judge-holdout-v1.yaml"
REPORT = ROOT / "docs" / "evaluation" / "judge-calibration-report.md"


async def main() -> None:
    rubric, items = load_holdout(HOLDOUT)
    report = await run_calibration(default_judge(), items)

    lines = [
        "# Judge calibration report",
        "",
        f"- generated: {datetime.now(UTC).date().isoformat()}",
        f"- rubric: `{report.rubric_version}`  holdout: `{rubric}`  items: {report.n_items}",
        "- judge: `fake-judge` (deterministic heuristic; the real judge is a different",
        "  model family from the generator — bias reduction, not independence)",
        "",
        "The judge scores **explanation quality only**. It is a secondary trend and",
        "never overrides a Tier 1 oracle (ADR-005, metric contract). This report is the",
        "evidence that licenses that limited use.",
        "",
        f"**Overall raw agreement with human labels: {report.overall_raw_agreement}**  ",
        f"**Mean quadratic-weighted kappa: {report.mean_weighted_kappa}**",
        "",
        "| dimension | raw agreement | weighted kappa | n |",
        "|---|---|---|---|",
    ]
    for d in report.per_dimension.values():
        lines.append(f"| {d.dimension} | {d.raw_agreement} | {d.weighted_kappa} | {d.n} |")
    lines += ["", "## Notable disagreements (|human - judge| >= 2)", ""]
    if report.disagreements:
        lines += ["| item | dimension | human | judge |", "|---|---|---|---|"]
        lines += [
            f"| {d['item']} | {d['dimension']} | {d['human']} | {d['judge']} |"
            for d in report.disagreements
        ]
    else:
        lines.append("None.")
    lines += [
        "",
        "## Limitations",
        "",
        "- Small holdout (n per dimension is the item count); treat kappa as directional.",
        "- The judge is calibrated for *this* rubric and workload; recalibrate when the",
        "  judge model, rubric, prompt, or workload changes materially.",
        "- Agreement is not correctness: the judge measures explanation quality, and a",
        "  high score never implies the numeric answer is right — that is the oracle's job.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")
    print(
        f"overall raw agreement={report.overall_raw_agreement} mean_kappa={report.mean_weighted_kappa}"
    )


if __name__ == "__main__":
    asyncio.run(main())
