"""Weekly reliability & evaluation review (master plan Phase 10).

Generates the operational review artifact a beta week closes on: platform-wide
reliability, cost/latency, exact-cache safety, any firing SLO alert, the current
evaluation gate, and per-tenant run volume — written to
docs/operations/reviews/weekly-<date>.md. Interpreting beta *usage* as
correctness evidence is the trap this guards against: quality comes from the
evaluation gate, not from "it seemed fine."

    uv run python scripts/weekly_review.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible.db import (
    SqlIdentityRepository,
    SqlMetricsRepository,
    create_async_engine_from_url,
    install_selector_event_loop_policy,
)
from crucible.observability import (
    RunTelemetry,
    cost_latency,
    evaluate_slo_alerts,
    reliability,
)
from crucible.observability.slo import firing
from crucible_api.settings import ApiSettings

install_selector_event_loop_policy()

_REPORT = Path("evals/reports/examples/router-comparison.json")
_OUT_DIR = Path("docs/operations/reviews")


async def _gather() -> str:
    settings = ApiSettings()
    engine = create_async_engine_from_url(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        orgs = await SqlIdentityRepository(session).list_organizations()
        metrics = SqlMetricsRepository(session)
        telemetry: list[RunTelemetry] = []
        per_org: list[tuple[str, str, int]] = []
        total_cache = {"hits": 0, "misses": 0, "false_hits": 0, "stores": 0}
        containment_breaches = 0
        for org in orgs:
            rows = await metrics.run_telemetry(organization_id=org.id, limit=1000)
            per_org.append((org.slug, org.status, len(rows)))
            telemetry.extend(
                RunTelemetry(
                    run_id=str(r.run_id),
                    status=r.status,
                    failure_category=r.failure_category,
                    cost_usd=r.cost_usd,
                    latency_ms=r.latency_ms,
                    attempt_count=r.attempt_count,
                    trace_complete=r.trace_complete,
                )
                for r in rows
            )
            cache = await metrics.cache_stats(organization_id=org.id)
            total_cache["hits"] += cache.hits
            total_cache["misses"] += cache.misses
            total_cache["false_hits"] += cache.false_hits
            total_cache["stores"] += cache.stores
        # A sandbox containment breach would surface via the security posture,
        # not run telemetry; the weekly review records 0 unless an incident set it.
        rel = reliability(telemetry)
        cost = cost_latency(telemetry)
        alerts = evaluate_slo_alerts(rel, containment_breaches=containment_breaches)

    await engine.dispose()

    def pct(v: float) -> str:
        return f"{v * 100:.1f}%"

    fired = firing(alerts)
    report = None
    try:
        report = json.loads(_REPORT.read_text(encoding="utf-8"))
    except Exception:
        report = None

    date = datetime.now(UTC).date().isoformat()
    lines: list[str] = [
        f"# Weekly reliability & evaluation review — {date}",
        "",
        "Platform-wide, anonymized (no raw prompts or dataset contents).",
        "",
        "## Reliability",
        "",
        f"- terminal runs: {rel.terminal} (answered {rel.answered}, abstained {rel.abstained})",
        f"- technical completion: {pct(rel.technical_completion_rate)}",
        f"- trace completeness: {pct(rel.trace_completeness)} (DoD target ≥ 99%)",
        f"- failure taxonomy: {rel.failure_taxonomy or '(none)'}",
        "",
        "## Cost & latency",
        "",
        f"- total cost: ${cost.total_cost_usd} · cost attribution {pct(cost.cost_attribution_completeness)}",
        f"- latency p50/p95/p99 ms: {cost.latency_p50_ms} / {cost.latency_p95_ms} / {cost.latency_p99_ms}",
        "",
        "## Exact-cache safety",
        "",
        f"- hits {total_cache['hits']} · misses {total_cache['misses']} · "
        f"false hits {total_cache['false_hits']} · stores {total_cache['stores']}",
        f"- **false hits must be 0**; {total_cache['false_hits']} observed.",
        "",
        "## SLO alerts",
        "",
        (
            "- none firing"
            if not fired
            else "\n".join(
                f"- **FIRING** {a.rule_id} ({a.severity.value}): {a.detail}" for a in fired
            )
        ),
        "",
        "## Evaluation gate (quality is measured, not inferred from usage)",
        "",
    ]
    if report is not None:
        gates = report.get("quality_gates", {})
        for policy_id, gate in gates.items():
            lines.append(
                f"- {policy_id}: **{gate['status'].upper()}** (paired Δ {gate['delta']}, "
                f"CI [{gate['ci_lo']}, {gate['ci_hi']}])"
            )
        lines.append(f"- report sha256: `{report.get('content_sha256', '')[:16]}`")
    else:
        lines.append("- no committed evaluation report found")
    lines += [
        "",
        "## Per-tenant volume",
        "",
        "| tenant | status | terminal runs |",
        "|---|---|---|",
    ]
    for slug, status, n in sorted(per_org):
        lines.append(f"| {slug} | {status} | {n} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    content = asyncio.run(_gather())
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / f"weekly-{datetime.now(UTC).date().isoformat()}.md"
    out.write_text(content, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
