// Server Component: tenant-scoped data is fetched with the server-side
// credential and rendered to HTML. No API key ever reaches the browser.
import { DataTable, Mono, Panel, StatusBadge } from "@crucible/ui";

import { listDatasets, listVersions, setupMessage } from "@/lib/api";

import { SetupRequired } from "../_setup";
import { UploadForm } from "./upload-form";

export const dynamic = "force-dynamic";

export default async function DatasetsPage() {
  let datasets;
  try {
    datasets = await listDatasets();
  } catch (error) {
    const setup = setupMessage(error);
    if (setup) return <SetupRequired message={setup} />;
    throw error;
  }

  const withVersions = await Promise.all(
    datasets.map(async (dataset) => ({
      dataset,
      versions: await listVersions(dataset.id),
    })),
  );

  return (
    <>
      <h1 className="cru-page-title">Datasets</h1>
      <p className="cru-page-lede">
        Every version is immutable and identified by the SHA-256 of its bytes — the same content can
        never become two versions.
      </p>

      <Panel title="Upload a dataset" pad>
        <UploadForm />
      </Panel>

      {withVersions.length === 0 ? (
        <Panel title="Your datasets">
          <p className="cru-empty">No datasets yet. Upload a CSV or Parquet file above.</p>
        </Panel>
      ) : (
        withVersions.map(({ dataset, versions }) => (
          <Panel key={dataset.id} title={dataset.name}>
            <DataTable
              headers={["Version", "Status", "Rows", "Cols", "Content SHA-256", "Schema hash"]}
              empty="No versions."
              rows={versions.map((v) => [
                `v${v.version_no}`,
                <StatusBadge key="s" status={v.status} />,
                v.row_count ?? "—",
                v.column_count ?? "—",
                <Mono key="c">{v.content_sha256?.slice(0, 16) ?? "—"}</Mono>,
                <Mono key="h">{v.schema_hash?.slice(0, 16) ?? "—"}</Mono>,
              ])}
            />
            {versions.some((v) => v.status === "invalid") && (
              <p className="cru-empty" style={{ color: "var(--danger)" }}>
                {versions.find((v) => v.status === "invalid")?.invalid_reason}
              </p>
            )}
          </Panel>
        ))
      )}
    </>
  );
}
