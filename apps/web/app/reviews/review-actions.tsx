"use client";

// Claim → grade → submit, in place in the queue. Claiming is an exclusive
// optimistic lock (one reviewer per run); a second claimant gets a clear
// conflict. Grades are the versioned rubric (0–2 each) and are recorded as
// typed human observations — they are evidence, never a correctness gate.
import { useRouter } from "next/navigation";
import { useState } from "react";

import { claimReview, submitReview } from "../actions";

const DIMENSIONS = ["groundedness", "provenance", "usefulness", "uncertainty"] as const;
type Dimension = (typeof DIMENSIONS)[number];
type Grades = Record<Dimension, number>;

const SCALE = [
  { value: 0, label: "0 — poor" },
  { value: 1, label: "1 — adequate" },
  { value: 2, label: "2 — strong" },
];

export function ReviewActions({ runId }: { runId: string }) {
  const router = useRouter();
  const [claimed, setClaimed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [grades, setGrades] = useState<Grades>({
    groundedness: 2,
    provenance: 2,
    usefulness: 2,
    uncertainty: 2,
  });

  async function onClaim() {
    setBusy(true);
    setError("");
    const result = await claimReview(runId);
    setBusy(false);
    if (result.ok) setClaimed(true);
    else setError(result.error);
  }

  async function onSubmit(decision: "approve" | "reject") {
    setBusy(true);
    setError("");
    const result = await submitReview(runId, decision, grades);
    setBusy(false);
    if (result.ok) router.refresh();
    else setError(result.error);
  }

  if (!claimed) {
    return (
      <div className="cru-btn-row">
        <button className="cru-btn" onClick={onClaim} disabled={busy} type="button">
          {busy ? "Claiming…" : "Claim"}
        </button>
        {error && (
          <span role="alert" style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
            {error}
          </span>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="cru-cluster" style={{ marginBottom: "var(--space-3)" }}>
        {DIMENSIONS.map((dim) => (
          <label key={dim} style={{ fontSize: "0.82rem" }}>
            <span className="cru-label" style={{ textTransform: "capitalize" }}>
              {dim}
            </span>
            <select
              className="cru-select"
              value={grades[dim]}
              onChange={(e) => setGrades({ ...grades, [dim]: Number(e.target.value) })}
              style={{ minWidth: 120 }}
            >
              {SCALE.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div className="cru-btn-row">
        <button
          className="cru-btn cru-btn-primary"
          onClick={() => onSubmit("approve")}
          disabled={busy}
          type="button"
        >
          Approve
        </button>
        <button
          className="cru-btn cru-btn-danger"
          onClick={() => onSubmit("reject")}
          disabled={busy}
          type="button"
        >
          Reject
        </button>
        {error && (
          <span role="alert" style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
