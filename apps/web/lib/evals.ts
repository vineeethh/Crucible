// Server-only readers for committed evaluation evidence.
//
// Phase 5 exposes the file-based report (the CI-gated artifact). The live eval
// service + score DB is a Phase 7 dashboard deliverable; here we read the
// committed example report and suite manifests from the repo so the pages show
// real evidence in local development.
import "server-only";

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { load as yamlLoad } from "js-yaml";

function repoRoot(): string {
  // `pnpm --filter web dev` runs from apps/web; the repo root is two levels up.
  return join(process.cwd(), "..", "..");
}

export type EvalReport = {
  generated_at: string;
  git_sha: string;
  scorer_version: string;
  suite: { id: string; version: string; hash: string };
  baseline: { config_id: string; config_hash: string; accuracy: number };
  candidate: { config_id: string; config_hash: string; accuracy: number };
  gate: {
    status: string;
    delta: number;
    ci_lo: number;
    ci_hi: number;
    tolerance: number;
    reasons: string[];
    correctness_regressions: string[];
    policy_regressions: string[];
  };
  efficiency: { candidate_total_latency_ms: number; candidate_total_cost_usd: number; cases: number };
  failure_taxonomy: Record<string, number>;
  cases: Array<{
    id: string;
    tags: string[];
    baseline_correct: boolean | null;
    candidate_correct: boolean;
    delta: number | null;
    policy_ok: boolean;
    policy_failures: string[];
    candidate: { terminal: string; value: unknown; latency_ms: number; exit_class: string | null };
    detail: string;
  }>;
  content_sha256: string;
};

export type SuiteSummary = {
  id: string;
  version: string;
  purpose: string;
  status: string;
  fixture: string;
  case_count: number;
  smoke_count: number;
};

export function loadExampleReport(): EvalReport | null {
  try {
    const path = join(repoRoot(), "evals", "reports", "examples", "core-comparison.json");
    return JSON.parse(readFileSync(path, "utf-8")) as EvalReport;
  } catch {
    return null;
  }
}

export type RouterPolicySummary = {
  policy_id: string;
  policy_version: string;
  config_hash: string;
  n_cases: number;
  accuracy: number;
  answered: number;
  abstained: number;
  escalations: number;
  fallbacks: number;
  total_cost_usd: number;
  cost_attribution_complete: boolean;
  mean_latency_ms: number;
  p95_latency_ms: number;
  mean_execute_attempts: number;
};

export type RouterReport = {
  generated_at: string;
  git_sha: string;
  suite: { id: string; version: string; hash: string };
  executor_backend: string;
  pricing_note: string;
  policies: RouterPolicySummary[];
  quality_gates: Record<
    string,
    { status: string; delta: number; ci_lo: number; ci_hi: number; tolerance: number }
  >;
  content_sha256: string;
};

export function loadRouterReport(): RouterReport | null {
  try {
    const path = join(repoRoot(), "evals", "reports", "examples", "router-comparison.json");
    return JSON.parse(readFileSync(path, "utf-8")) as RouterReport;
  } catch {
    return null;
  }
}

/** Renders a committed comparison report as a self-contained Markdown document
 * — the shareable, human-readable form of the CI-gated JSON artifact. */
export function reportToMarkdown(report: EvalReport): string {
  const g = report.gate;
  const lines: string[] = [
    `# Evaluation comparison — gate ${g.status.toUpperCase()}`,
    "",
    `- generated: ${report.generated_at}`,
    `- git: \`${report.git_sha}\` · scorer \`${report.scorer_version}\``,
    `- suite: \`${report.suite.id}@${report.suite.version}\` (hash \`${report.suite.hash.slice(0, 16)}\`)`,
    `- candidate \`${report.candidate.config_id}\` (acc ${report.candidate.accuracy}) vs baseline \`${report.baseline.config_id}\` (acc ${report.baseline.accuracy})`,
    `- paired Δ **${g.delta}**, 95% CI [${g.ci_lo}, ${g.ci_hi}], tolerance ${g.tolerance}`,
    `- report sha256: \`${report.content_sha256}\``,
    "",
    "## Gate reasons",
    "",
    ...(g.reasons.length ? g.reasons.map((r) => `- ${r}`) : ["- (none)"]),
    "",
    "## Per-case deltas",
    "",
    "| case | tags | base | cand | Δ | terminal | value | ms | policy |",
    "|---|---|---|---|---|---|---|---|---|",
    ...report.cases.map((c) => {
      const mark = (v: boolean | null) => (v === null ? "·" : v ? "✓" : "✗");
      const policy = c.policy_ok ? "ok" : `FAIL:${c.policy_failures.join(",")}`;
      return `| ${c.id} | ${c.tags.join(" ")} | ${mark(c.baseline_correct)} | ${mark(
        c.candidate_correct,
      )} | ${c.delta ?? "·"} | ${c.candidate.terminal} | ${String(c.candidate.value ?? "—")} | ${
        c.candidate.latency_ms
      } | ${policy} |`;
    }),
    "",
  ];
  return lines.join("\n");
}

export function listSuites(): SuiteSummary[] {
  try {
    const dir = join(repoRoot(), "evals", "suites");
    return readdirSync(dir)
      .filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"))
      .map((f) => {
        const doc = yamlLoad(readFileSync(join(dir, f), "utf-8")) as Record<string, unknown>;
        const cases = (doc.cases as unknown[]) ?? [];
        const smoke = (doc.smoke as unknown[]) ?? [];
        return {
          id: String(doc.id ?? f),
          version: String(doc.version ?? ""),
          purpose: String(doc.purpose ?? ""),
          status: String(doc.status ?? ""),
          fixture: String(doc.fixture ?? ""),
          case_count: cases.length,
          smoke_count: smoke.length,
        };
      });
  } catch {
    return [];
  }
}
