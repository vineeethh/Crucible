// Evaluations: versioned suites, the latest committed experiment comparison
// (downloadable as JSON — the exact CI-gated bytes — or Markdown), and the
// Phase 8 router efficiency experiment (quality/cost/latency per policy).
import { Callout, DataTable, GateBadge, Mono, Panel, StatusBadge, Tag } from "@crucible/ui";

import { listSuites, loadExampleReport, loadRouterReport } from "@/lib/evals";

export const dynamic = "force-dynamic";

function mark(v: boolean | null): string {
  return v === null ? "·" : v ? "✓" : "✗";
}

export default function EvaluationsPage() {
  const suites = listSuites();
  const report = loadExampleReport();
  const routerReport = loadRouterReport();

  return (
    <>
      <h1 className="cru-page-title">Evaluations</h1>
      <p className="cru-page-lede">
        Versioned suites scored against trusted oracles; candidates gated against a frozen baseline
        with a paired bootstrap confidence interval.
      </p>

      <Panel title="Suites">
        <DataTable
          headers={["Suite", "Version", "Purpose", "Fixture", "Cases", "Smoke"]}
          empty="No suites found."
          rows={suites.map((s) => [
            s.id,
            s.version,
            <StatusBadge key="p" status={s.purpose} />,
            <Mono key="f">{s.fixture}</Mono>,
            s.case_count,
            s.smoke_count,
          ])}
        />
      </Panel>

      {routerReport && (
        <Panel title="Router efficiency experiment">
          <DataTable
            headers={[
              "Policy",
              "Version",
              "n",
              "Accuracy",
              "Escalations",
              "Fallbacks",
              "Total cost",
              "Mean ms",
              "p95 ms",
              "Mean executes",
              "Quality gate",
            ]}
            empty="No policies."
            rows={routerReport.policies.map((p) => {
              const gate = routerReport.quality_gates[p.policy_id];
              return [
                <strong key="id">{p.policy_id}</strong>,
                <Mono key="v">{p.policy_version}</Mono>,
                p.n_cases,
                p.accuracy,
                p.escalations,
                p.fallbacks,
                `$${p.total_cost_usd}`,
                p.mean_latency_ms,
                p.p95_latency_ms,
                p.mean_execute_attempts,
                gate ? (
                  <span key="g" className="cru-cluster">
                    <GateBadge status={gate.status} />
                    <span className="cru-muted" style={{ fontSize: "0.8rem" }}>
                      Δ {gate.delta} [{gate.ci_lo}, {gate.ci_hi}]
                    </span>
                  </span>
                ) : (
                  <span key="g" className="cru-muted">
                    baseline
                  </span>
                ),
              ];
            })}
          />
          <p className="cru-empty" style={{ fontSize: "0.8rem" }}>
            {routerReport.pricing_note} Generated {routerReport.generated_at} · git{" "}
            {routerReport.git_sha} · executor {routerReport.executor_backend} · report{" "}
            {routerReport.content_sha256.slice(0, 16)}.
          </p>
        </Panel>
      )}

      {report ? (
        <>
          <Panel
            title="Latest comparison"
            actions={
              <span className="cru-cluster">
                <a className="cru-btn" href="/evaluations/export?format=md" download>
                  Export Markdown
                </a>
                <a className="cru-btn" href="/evaluations/export" download>
                  Export JSON
                </a>
              </span>
            }
            pad
          >
            <p className="cru-cluster" style={{ margin: "0 0 var(--space-3)" }}>
              gate <GateBadge status={report.gate.status} />
            </p>
            <p className="cru-muted" style={{ margin: 0, fontSize: "0.92rem" }}>
              candidate <Mono>{report.candidate.config_id}</Mono> (acc {report.candidate.accuracy})
              vs baseline <Mono>{report.baseline.config_id}</Mono> (acc {report.baseline.accuracy}) ·
              paired Δ <strong>{report.gate.delta}</strong>, 95% CI [{report.gate.ci_lo},{" "}
              {report.gate.ci_hi}], tolerance {report.gate.tolerance}
            </p>
            <p className="cru-muted" style={{ margin: "var(--space-2) 0 0", fontSize: "0.82rem" }}>
              git <Mono>{report.git_sha}</Mono> · scorer <Mono>{report.scorer_version}</Mono> ·
              report <Mono>{report.content_sha256.slice(0, 16)}</Mono>
            </p>
          </Panel>

          <Panel title="Per-case deltas">
            <DataTable
              headers={["Case", "Tags", "Base", "Cand", "Δ", "Terminal", "Value", "ms", "Policy"]}
              empty="No cases."
              rows={report.cases.map((c) => [
                <Mono key="id">{c.id}</Mono>,
                <span key="t">
                  {c.tags.map((t) => (
                    <Tag key={t}>{t}</Tag>
                  ))}
                </span>,
                mark(c.baseline_correct),
                mark(c.candidate_correct),
                c.delta ?? "·",
                <StatusBadge key="term" status={c.candidate.terminal} />,
                String(c.candidate.value ?? "—"),
                c.candidate.latency_ms,
                c.policy_ok ? (
                  "ok"
                ) : (
                  <span style={{ color: "var(--danger)" }}>FAIL:{c.policy_failures.join(",")}</span>
                ),
              ])}
            />
          </Panel>
        </>
      ) : (
        <Callout tone="info" title="No committed report">
          Generate one with{" "}
          <Mono>python -m crucible.evaluation run --suite … --baseline …</Mono>.
        </Callout>
      )}
    </>
  );
}
