"use client";

// Cancel a run that has not yet terminated. Cancellation is cooperative: the
// API records the request and a queued run stops synchronously; a running one
// is not resurrected by a later worker (compare-and-set transitions).
import { useRouter } from "next/navigation";
import { useState } from "react";

import { cancelRun } from "../../actions";

const CANCELLABLE = new Set(["queued", "running", "waiting_review"]);

export function RunActions({ runId, status }: { runId: string; status: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!CANCELLABLE.has(status)) return null;

  async function onCancel() {
    setBusy(true);
    setError("");
    const result = await cancelRun(runId);
    setBusy(false);
    if (result.ok) router.refresh();
    else setError(result.error);
  }

  return (
    <div className="cru-btn-row">
      <button className="cru-btn cru-btn-danger" onClick={onCancel} disabled={busy} type="button">
        {busy ? "Cancelling…" : "Cancel run"}
      </button>
      {error && (
        <span role="alert" style={{ color: "var(--danger)", fontSize: "0.88rem" }}>
          {error}
        </span>
      )}
    </div>
  );
}
