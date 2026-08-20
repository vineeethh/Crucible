"use client";

// Set the organization's monthly budget (owner-only; the API enforces
// ORG_MANAGE — this form just surfaces the result). Admission refuses new runs
// once the month's ledger reaches the limit.
import { useRouter } from "next/navigation";
import { useState } from "react";

import { updateBudget } from "../actions";

export function BudgetForm({ currentLimit }: { currentLimit: number | null }) {
  const router = useRouter();
  const [value, setValue] = useState(currentLimit === null ? "" : String(currentLimit));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = Number(value);
    if (Number.isNaN(parsed) || parsed < 0) {
      setIsError(true);
      setMessage("Enter a non-negative USD amount.");
      return;
    }
    setBusy(true);
    setMessage("");
    const result = await updateBudget(parsed);
    setBusy(false);
    if (result.ok) {
      setIsError(false);
      setMessage(`Saved. Remaining this month: $${result.data.remaining_usd ?? "—"}.`);
      router.refresh();
    } else {
      setIsError(true);
      setMessage(result.error);
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <label className="cru-field" style={{ maxWidth: 280 }}>
        <span className="cru-label">Monthly limit (USD)</span>
        <input
          className="cru-input"
          inputMode="decimal"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. 25"
          required
        />
        <span className="cru-hint">
          New runs are refused once the month&rsquo;s ledger (reserves + settled spend) reaches
          this limit. Owner-only.
        </span>
      </label>
      <div className="cru-btn-row">
        <button className="cru-btn cru-btn-primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save budget"}
        </button>
        {message && (
          <span
            role={isError ? "alert" : "status"}
            className="cru-muted"
            style={{ color: isError ? "var(--danger)" : undefined, fontSize: "0.88rem" }}
          >
            {message}
          </span>
        )}
      </div>
    </form>
  );
}
