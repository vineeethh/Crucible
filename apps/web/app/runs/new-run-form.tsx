"use client";

// Start a run against a ready dataset version. Only versions the API has
// profiled to `ready` can back a run, so this offers exactly those.
import { useRouter } from "next/navigation";
import { useState } from "react";

import { createRun } from "../actions";

export type ReadyVersion = {
  version_id: string;
  label: string;
};

export function NewRunForm({ versions }: { versions: ReadyVersion[] }) {
  const router = useRouter();
  const [versionId, setVersionId] = useState(versions[0]?.version_id ?? "");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (versions.length === 0) {
    return (
      <p className="cru-empty">
        No ready dataset versions yet. Upload and profile a dataset first.
      </p>
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!versionId || !question.trim()) return;
    setBusy(true);
    setError("");
    const result = await createRun({ dataset_version_id: versionId, question: question.trim() });
    setBusy(false);
    if (result.ok) {
      setQuestion("");
      router.push(`/runs/${result.data.run_id}`);
      router.refresh();
    } else {
      setError(result.error);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ padding: "var(--space-4) var(--space-5)" }}>
      <label className="cru-field">
        <span className="cru-label">Dataset version</span>
        <select
          className="cru-select"
          value={versionId}
          onChange={(e) => setVersionId(e.target.value)}
        >
          {versions.map((v) => (
            <option key={v.version_id} value={v.version_id}>
              {v.label}
            </option>
          ))}
        </select>
      </label>
      <label className="cru-field">
        <span className="cru-label">Question</span>
        <textarea
          className="cru-textarea"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What is the total amount by region?"
          maxLength={2000}
          required
        />
        <span className="cru-hint">
          The agent plans an analysis, runs generated code in the sandbox, verifies, and answers
          with provenance — or abstains truthfully.
        </span>
      </label>
      <div className="cru-btn-row">
        <button className="cru-btn cru-btn-primary" type="submit" disabled={busy}>
          {busy ? "Starting…" : "Start run"}
        </button>
        {error && (
          <span role="alert" style={{ color: "var(--danger)", fontSize: "0.88rem" }}>
            {error}
          </span>
        )}
      </div>
    </form>
  );
}
