"""Trusted reference calculator for the employee_performance_2024 suite.

Computes every gold with the SAME semantics the agent's code generator emits
(packages/agent/src/crucible/agent/models/codegen.py):

  missing_count  -> is_null() OR cast-to-str == ''
  dedupe         -> df.height - df.unique().height
  count+filter   -> df.filter(<cast-to-str comparison>).height
  group_aggregate/rank_top_n -> group_by().agg(sum/mean/count).round(2 for
                     sum/mean).sort(...)[.head(n) for rank_top_n]

Every "value" key below is a real, answerable gold. Values under `_unanswerable`
are computed here for reference/documentation only — the suite does not use
them as golds, because the agent has no operation for them (correlation,
IQR/z-score outlier detection, a HAVING-style minimum-count qualifier on a
ranking, or a custom multi-condition rule). See the suite YAML for exactly
which task maps to which case, including the abstentions.

Run:  uv run python evals/references/employee_performance_2024_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "employee_performance_2024.csv"


def compute() -> dict[str, object]:
    df = pl.read_csv(FIXTURE, infer_schema_length=10000)

    def missing(col: str) -> int:
        s = df[col]
        return int((s.is_null() | (s.cast(pl.Utf8, strict=False) == "")).sum())

    def group_table(group: str, target: str, reducer: str) -> list[dict[str, object]]:
        agg = {
            "sum": pl.col(target).sum(),
            "mean": pl.col(target).mean(),
            "count": pl.len(),
        }[reducer]
        return (
            df.group_by(group)
            .agg(agg.round(2).alias("value") if reducer != "count" else agg.alias("value"))
            .sort(group)
            .to_dicts()
        )

    def top_n(group: str, target: str, reducer: str, n: int) -> list[dict[str, object]]:
        agg = {"sum": pl.col(target).sum(), "mean": pl.col(target).mean()}[reducer]
        return (
            df.group_by(group)
            .agg(agg.round(2).alias("value"))
            .sort("value", descending=True)
            .head(n)
            .to_dicts()
        )

    golds: dict[str, object] = {
        "row_count": int(df.height),
        # -- Task 1: cleaning / detection ----------------------------------
        "duplicate_row_count": int(df.height - df.unique().height),
        "missing_performance_score": missing("PerformanceScore"),
        "missing_engagement_score": missing("EngagementScore"),
        "missing_training_hours": missing("TrainingHoursCompleted"),
        "sentinel_999_monthly_hours": int(df.filter(pl.col("MonthlyHoursWorked") == 999).height),
        "negative_absence_days": int(df.filter(pl.col("AbsenceDays") < 0).height),
        # -- Task 2: mean PerformanceScore/EngagementScore by Dept/JobLevel --
        "mean_performance_by_department": group_table("DepartmentCode", "PerformanceScore", "mean"),
        "mean_engagement_by_department": group_table("DepartmentCode", "EngagementScore", "mean"),
        "mean_performance_by_joblevel": group_table("JobLevel", "PerformanceScore", "mean"),
        "mean_engagement_by_joblevel": group_table("JobLevel", "EngagementScore", "mean"),
        # -- Task 7: headcount / avg YearsAtCompany / avg SalaryBand by Dept -
        # Three SEPARATE tables: group_aggregate has one reducer per query,
        # so the brief's single combined summary table isn't producible in
        # one call — this is three answers, not one, and is presented that way.
        "headcount_by_department": group_table("DepartmentCode", "EmployeeID", "count"),
        "mean_years_by_department": group_table("DepartmentCode", "YearsAtCompany", "mean"),
        "mean_salaryband_by_department": group_table("DepartmentCode", "SalaryBand", "mean"),
        # -- Task 4, partial: ranking WITHOUT the "min 3 direct reports"
        # qualifier (rank_top_n has no HAVING-style filter, and no bottom-N).
        # Recorded to show what the operation CAN do, not as a gold for the
        # task as literally stated — the suite's ro-... case for Task 4 in
        # full abstains, because ignoring the qualifier changes the answer.
        "_partial_top5_managers_by_engagement_no_qualifier": top_n(
            "ManagerID", "EngagementScore", "mean", 5
        ),
    }

    # Documented, NOT used as golds — no supported operation computes these.
    golds["_unanswerable"] = {
        "correlation_overtime_vs_performance": round(
            float(df.select(pl.corr("OvertimeHours", "PerformanceScore")).item()), 4
        ),
        "correlation_absence_vs_performance": round(
            float(df.select(pl.corr("AbsenceDays", "PerformanceScore")).item()), 4
        ),
        "reason": (
            "Computed here with polars' own pl.corr for reference only. The "
            "agent has no correlation operation, no IQR/z-score outlier "
            "operation, no HAVING-style minimum-group-size filter, and no "
            "custom multi-condition rule composition — Tasks 3, 4 (as stated, "
            "with its qualifier), 5, and 6 correctly abstain."
        ),
    }
    return golds


def main() -> int:
    golds = compute()
    for key, value in golds.items():
        print(json.dumps({key: value}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
