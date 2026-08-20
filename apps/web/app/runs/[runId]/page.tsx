// Run detail (Server Component): the answer with provenance, the verification
// vector, the redacted trace, the config manifest, the node timeline, and the
// per-step attempts. This is the page that makes the agent's reasoning legible —
// every claim is backed by evidence.
import {
  ConfigView,
  DataTable,
  KeyValue,
  Mono,
  Panel,
  StatusBadge,
  Trace,
  type ExportedTrace,
} from "@crucible/ui";
import Link from "next/link";

import {
  getRun,
  getRunAttempts,
  getRunEvents,
  getRunTrace,
  setupMessage,
  type Trace as TraceData,
} from "@/lib/api";

import { SetupRequired } from "../../_setup";
import { RunActions } from "./run-actions";

export const dynamic = "force-dynamic";

export default async function RunDetail({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  let run, events, attempts, trace: TraceData | null;
  try {
    [run, events, attempts] = await Promise.all([
      getRun(runId),
      getRunEvents(runId),
      getRunAttempts(runId),
    ]);
    try {
      trace = await getRunTrace(runId);
    } catch {
      trace = null; // trace is best-effort; the rest of the page still renders
    }
  } catch (error) {
    const setup = setupMessage(error);
    if (setup) return <SetupRequired message={setup} />;
    throw error;
  }

  return (
    <>
      <Link href="/runs" style={{ fontSize: "0.85rem" }}>
        ← all runs
      </Link>
      <div className="cru-toolbar" style={{ marginTop: "var(--space-3)" }}>
        <h1 className="cru-page-title" style={{ margin: 0 }}>
          {run.question}
        </h1>
        <RunActions runId={run.id} status={run.status} />
      </div>
      <p className="cru-cluster" style={{ marginTop: 0 }}>
        <StatusBadge status={run.status} /> <Mono>{run.id}</Mono>
      </p>

      {run.answer ? (
        <Panel title="Answer" pad>
          <p style={{ fontSize: "1.15rem", margin: "0 0 var(--space-2)" }}>{run.answer.text}</p>
          {run.answer.limitations && (
            <p className="cru-muted" style={{ margin: "0 0 var(--space-4)", fontSize: "0.9rem" }}>
              {run.answer.limitations}
            </p>
          )}
          <KeyValue
            items={[
              ["value", <Mono key="v">{String(run.answer.value)}</Mono>],
              ["operation", <Mono key="o">{run.answer.provenance.operation}</Mono>],
              [
                "columns used",
                <Mono key="c">{run.answer.provenance.columns_used.join(", ") || "—"}</Mono>,
              ],
              ["code sha256", <Mono key="s">{run.answer.provenance.code_sha256.slice(0, 24)}</Mono>],
              ["attempts", run.answer.provenance.attempt_count],
              [
                "executor",
                <Mono key="e">
                  {run.answer.provenance.executor_backend} {run.answer.provenance.image_ref}
                </Mono>,
              ],
            ]}
          />
        </Panel>
      ) : (
        <Panel title="Outcome" pad>
          <p className="cru-muted" style={{ margin: 0 }}>
            {run.terminal_detail ?? "No answer was produced (the run has not terminated with one)."}
          </p>
        </Panel>
      )}

      {run.verification && (
        <Panel title="Verification">
          <DataTable
            headers={["Check", "Result"]}
            empty="—"
            rows={Object.entries(run.verification)
              .filter(([k]) => k !== "reasons")
              .map(([k, v]) => [k, <Mono key={k}>{String(v)}</Mono>])}
          />
        </Panel>
      )}

      {trace && (
        <Panel title="Trace (redacted, export-safe)">
          <Trace trace={trace as ExportedTrace} />
        </Panel>
      )}

      <Panel title="Config manifest">
        <ConfigView config={run.config_manifest} />
      </Panel>

      <Panel title="Node timeline">
        <DataTable
          headers={["#", "Event", "Node / status"]}
          empty="No events yet."
          rows={events.map((e) => [
            e.sequence_no,
            e.event_type,
            <Mono key="n">{String(e.payload.node ?? e.payload.status ?? "")}</Mono>,
          ])}
        />
      </Panel>

      <Panel title="Attempts">
        <DataTable
          headers={["#", "Kind", "Model", "Exit", "ms", "Code sha256"]}
          empty="No attempts."
          rows={attempts.map((a) => [
            a.attempt_no,
            a.kind,
            <Mono key="m">{a.model_id ?? "—"}</Mono>,
            a.exit_class ?? "—",
            a.duration_ms ?? "—",
            <Mono key="c">{a.source_sha256?.slice(0, 12) ?? "—"}</Mono>,
          ])}
        />
      </Panel>
    </>
  );
}
