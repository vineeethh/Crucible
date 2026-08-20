// Human review queue: runs the agent routed to a human (an ambiguous result).
// Reviewers claim (exclusive), apply the versioned rubric, and approve or reject
// in place — no internal tools required.
import { DataTable, Mono, Panel, StatusBadge } from "@crucible/ui";
import Link from "next/link";

import { getReviewQueue, setupMessage } from "@/lib/api";

import { SetupRequired } from "../_setup";
import { ReviewActions } from "./review-actions";

export const dynamic = "force-dynamic";

export default async function ReviewsPage() {
  let queue;
  try {
    queue = await getReviewQueue();
  } catch (error) {
    const setup = setupMessage(error);
    if (setup) return <SetupRequired message={setup} />;
    throw error;
  }

  return (
    <>
      <h1 className="cru-page-title">Review queue</h1>
      <p className="cru-page-lede">
        Runs the agent routed to a human because verification was ambiguous. Claim one, grade it
        against the rubric (groundedness / provenance / usefulness / uncertainty, 0–2 each), then
        approve or reject. Grades are recorded as evidence — never a correctness gate.
      </p>

      <Panel title={`${queue.length} awaiting review`}>
        <DataTable
          headers={["Run", "Question", "State", "Created", "Action"]}
          empty="Nothing awaiting review."
          columnStyles={[undefined, { maxWidth: 300 }, undefined, { whiteSpace: "nowrap" }, { minWidth: 260 }]}
          rows={queue.map((item) => [
            <Link key="id" href={`/runs/${item.run_id}`}>
              <Mono>{item.run_id.slice(0, 8)}</Mono>
            </Link>,
            <span key="q">{item.question}</span>,
            <StatusBadge key="s" status={item.review_status ?? "waiting_review"} />,
            <span key="c" className="cru-muted">
              {new Date(item.created_at).toLocaleString()}
            </span>,
            <ReviewActions key="a" runId={item.run_id} />,
          ])}
        />
      </Panel>
    </>
  );
}
