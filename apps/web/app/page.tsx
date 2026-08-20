// Landing / product tour entry. A Server Component: it probes the API health
// path (no credential) so a first-time visitor sees whether the platform is up,
// then points them at the full journey — upload → run → evidence → compare →
// review — each completable in the UI.
import { Callout, MetricGrid } from "@crucible/ui";
import Link from "next/link";

export const dynamic = "force-dynamic";

const API_URL = process.env.CRUCIBLE_API_URL ?? "http://localhost:8100";

type VersionInfo = { git_sha: string; version: string; profile: string };

async function probe(): Promise<{ up: boolean; version: VersionInfo | null }> {
  try {
    const health = await fetch(`${API_URL}/healthz`, { cache: "no-store" });
    if (!health.ok) return { up: false, version: null };
    const v = await fetch(`${API_URL}/version`, { cache: "no-store" });
    return { up: true, version: v.ok ? ((await v.json()) as VersionInfo) : null };
  } catch {
    return { up: false, version: null };
  }
}

const JOURNEY = [
  { href: "/datasets", step: "1. Upload", body: "Add a CSV or Parquet dataset. Versions are immutable and content-addressed." },
  { href: "/runs", step: "2. Run", body: "Ask a question. The agent plans, runs code in the sandbox, verifies, and answers with provenance." },
  { href: "/runs", step: "3. See evidence", body: "Every run shows its answer, trace, config, timeline, and per-step attempts." },
  { href: "/evaluations", step: "4. Compare", body: "Gate a candidate against a frozen baseline with a paired bootstrap CI." },
  { href: "/reviews", step: "5. Review", body: "Claim an ambiguous run, grade it against the rubric, approve or reject." },
];

export default async function Home() {
  const { up, version } = await probe();

  return (
    <>
      <h1 className="cru-page-title">Crucible</h1>
      <p className="cru-page-lede">
        An evaluation and reliability platform for LLM agents. Upload data, run the durable
        data-agent, inspect the evidence behind every answer, gate candidates against a baseline,
        and review the ambiguous cases — all from here.
      </p>

      {up ? (
        <Callout tone="ok" title="API reachable">
          {version
            ? `Connected to ${API_URL} · ${version.git_sha} · v${version.version} · ${version.profile}.`
            : `Connected to ${API_URL}.`}
        </Callout>
      ) : (
        <Callout tone="warn" title="API unreachable">
          Could not reach {API_URL}. Start the stack (<code className="cru-mono">docker compose up</code>
          ) or set <code className="cru-mono">CRUCIBLE_API_URL</code>.
        </Callout>
      )}

      <section aria-labelledby="journey-title" style={{ marginTop: "var(--space-6)" }}>
        <h2 id="journey-title" className="cru-panel-title">
          The user journey
        </h2>
        <MetricGrid>
          {JOURNEY.map((j) => (
            <Link key={j.step} href={j.href} className="cru-metric">
              <div className="cru-metric-value" style={{ fontSize: "1rem" }}>
                {j.step}
              </div>
              <div className="cru-metric-hint" style={{ marginTop: "var(--space-2)" }}>
                {j.body}
              </div>
            </Link>
          ))}
        </MetricGrid>
      </section>
    </>
  );
}
