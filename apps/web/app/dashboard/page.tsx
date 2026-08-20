// Reliability dashboard: terminal-state distribution, failure taxonomy, trace
// completeness, cost/latency, and firing alerts — the operating view for the
// agent's health (master plan §11.2).
import {
  Callout,
  DataTable,
  MetricCard,
  MetricGrid,
  Mono,
  Panel,
  SeverityTag,
  StatusBadge,
} from "@crucible/ui";

import {
  getAlerts,
  getBudget,
  getCacheStats,
  getCostLatency,
  getReliability,
  setupMessage,
} from "@/lib/api";

import { SetupRequired } from "../_setup";

export const dynamic = "force-dynamic";

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export default async function DashboardPage() {
  let reliability, cost, alerts, budget, cache;
  try {
    [reliability, cost, alerts, budget, cache] = await Promise.all([
      getReliability(),
      getCostLatency(),
      getAlerts(),
      getBudget(),
      getCacheStats(),
    ]);
  } catch (error) {
    const setup = setupMessage(error);
    if (setup) return <SetupRequired message={setup} />;
    throw error;
  }

  const firing = alerts.filter((a) => a.firing);

  return (
    <>
      <h1 className="cru-page-title">Reliability</h1>
      <p className="cru-page-lede">
        Every terminal run contributes its trace, cost, latency, versions, and failure category.
        This is the operating view of the agent&rsquo;s health.
      </p>

      {firing.length > 0 ? (
        <Panel title={`Firing alerts (${firing.length})`}>
          <DataTable
            headers={["Severity", "Rule", "Detail", "Runbook"]}
            empty=""
            rows={firing.map((a) => [
              <SeverityTag key="s" severity={a.severity} />,
              a.rule_id,
              a.detail,
              <Mono key="r">{a.runbook}</Mono>,
            ])}
          />
        </Panel>
      ) : (
        <Callout tone="ok" title="No firing alerts">
          Sandbox containment, trace completeness, technical completion, and abstention are within
          SLO.
        </Callout>
      )}

      <MetricGrid>
        <MetricCard label="Terminal runs" value={String(reliability.terminal)} />
        <MetricCard
          label="Technical completion"
          value={pct(reliability.technical_completion_rate)}
          hint="excludes cancelled"
        />
        <MetricCard
          label="Trace completeness"
          value={pct(reliability.trace_completeness)}
          hint="DoD target ≥ 99%"
        />
        <MetricCard label="Answered" value={String(reliability.answered)} />
        <MetricCard label="Abstained" value={String(reliability.abstained)} />
        <MetricCard label="p95 latency" value={`${cost.latency_p95_ms} ms`} />
        <MetricCard label="Total cost" value={`$${cost.total_cost_usd.toFixed(4)}`} />
        <MetricCard
          label="Cost attribution"
          value={pct(cost.cost_attribution_completeness)}
          hint="runs with a cost"
        />
      </MetricGrid>

      <section aria-labelledby="budget-title" style={{ marginTop: "var(--space-6)" }}>
        <h2 id="budget-title" className="cru-panel-title">
          Cost &amp; budget
        </h2>
        <MetricGrid>
          <MetricCard
            label="Monthly budget"
            value={budget.monthly_limit_usd === null ? "—" : `$${budget.monthly_limit_usd}`}
            hint={budget.monthly_limit_usd === null ? "unenforced (set in Settings)" : undefined}
          />
          <MetricCard label="Month spend" value={`$${budget.month_spend_usd.toFixed(4)}`} />
          <MetricCard
            label="Remaining"
            value={budget.remaining_usd === null ? "—" : `$${budget.remaining_usd.toFixed(4)}`}
          />
        </MetricGrid>
      </section>

      <section aria-labelledby="cache-title" style={{ marginTop: "var(--space-6)" }}>
        <h2 id="cache-title" className="cru-panel-title">
          Exact cache safety
        </h2>
        <MetricGrid>
          <MetricCard label="Hit rate" value={pct(cache.hit_rate)} hint="false hits count against" />
          <MetricCard label="Hits" value={String(cache.hits)} />
          <MetricCard label="Misses" value={String(cache.misses)} />
          <MetricCard
            label="False hits"
            value={String(cache.false_hits)}
            hint={cache.false_hits > 0 ? "investigate: identity inputs mismatched" : "target: 0"}
          />
          <MetricCard label="Stores" value={String(cache.stores)} />
        </MetricGrid>
      </section>

      <Panel title="Terminal states">
        <DataTable
          headers={["State", "Count"]}
          empty="No terminal runs yet."
          rows={Object.entries(reliability.terminal_states).map(([s, n]) => [
            <StatusBadge key="s" status={s} />,
            n,
          ])}
        />
      </Panel>

      <Panel title="Failure taxonomy">
        <DataTable
          headers={["Category", "Count"]}
          empty="No failures recorded — nothing to categorize."
          rows={Object.entries(reliability.failure_taxonomy).map(([c, n]) => [
            <Mono key="c">{c}</Mono>,
            n,
          ])}
        />
      </Panel>
    </>
  );
}
