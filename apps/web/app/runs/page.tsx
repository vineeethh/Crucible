import { DataTable, Mono, Panel, StatusBadge } from "@crucible/ui";
import Link from "next/link";

import { listDatasets, listRuns, listVersions, setupMessage } from "@/lib/api";

import { SetupRequired } from "../_setup";
import { NewRunForm, type ReadyVersion } from "./new-run-form";

export const dynamic = "force-dynamic";

async function readyVersions(): Promise<ReadyVersion[]> {
  const datasets = await listDatasets();
  const perDataset = await Promise.all(
    datasets.map(async (d) => {
      const versions = await listVersions(d.id);
      return versions
        .filter((v) => v.status === "ready")
        .map((v) => ({ version_id: v.id, label: `${d.name} · v${v.version_no}` }));
    }),
  );
  return perDataset.flat();
}

export default async function RunsPage() {
  let runs, versions;
  try {
    [runs, versions] = await Promise.all([listRuns(), readyVersions()]);
  } catch (error) {
    const setup = setupMessage(error);
    if (setup) return <SetupRequired message={setup} />;
    throw error;
  }

  return (
    <>
      <h1 className="cru-page-title">Runs</h1>
      <p className="cru-page-lede">
        Durable async jobs. The agent claims a run, plans, generates and executes code in the
        sandbox, verifies, and answers with provenance — or abstains, or routes to human review.
      </p>

      <Panel title="Start a run">
        <NewRunForm versions={versions} />
      </Panel>

      <Panel title={`${runs.length} run${runs.length === 1 ? "" : "s"}`}>
        <DataTable
          headers={["Run", "Question", "Status", "Outcome", "Created"]}
          empty="No runs yet. Start one above."
          columnStyles={[undefined, { maxWidth: 340 }, undefined, undefined, { whiteSpace: "nowrap" }]}
          rows={runs.map((run) => [
            <Link key="id" href={`/runs/${run.id}`}>
              <Mono>{run.id.slice(0, 8)}</Mono>
            </Link>,
            <span key="q">{run.question}</span>,
            <StatusBadge key="s" status={run.status} />,
            <span key="d" className="cru-muted">
              {run.failure_category ?? run.terminal_detail?.slice(0, 60) ?? "—"}
            </span>,
            <span key="c" className="cru-muted">
              {new Date(run.created_at).toLocaleString()}
            </span>,
          ])}
        />
      </Panel>
    </>
  );
}
