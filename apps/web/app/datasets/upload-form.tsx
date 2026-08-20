"use client";

// Direct-to-storage upload, three steps, all from the browser:
//   1. server action mints a presigned PUT URL (the API key never leaves the server);
//   2. the browser PUTs the bytes straight to object storage — they never touch
//      the API or this app;
//   3. the browser computes the SHA-256 and the server action completes the
//      version, which the worker then profiles.
// Content is identity: the API re-hashes the stored bytes and rejects a mismatch.
import { useRouter } from "next/navigation";
import { useState } from "react";

import { beginUpload, finishUpload } from "../actions";

type Phase = "idle" | "starting" | "putting" | "completing" | "done" | "error";

const CONTENT_TYPES: Record<string, string> = {
  csv: "text/csv",
  parquet: "application/vnd.apache.parquet",
};

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function UploadForm() {
  const router = useRouter();
  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");

  const busy = phase === "starting" || phase === "putting" || phase === "completing";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !datasetName) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const contentType = CONTENT_TYPES[ext];
    if (!contentType) {
      setPhase("error");
      setMessage("Only .csv and .parquet files are accepted.");
      return;
    }

    try {
      setPhase("starting");
      setMessage("Requesting an upload URL…");
      const started = await beginUpload({
        dataset_name: datasetName,
        filename: file.name,
        content_type: contentType,
        size_bytes: file.size,
      });
      if (!started.ok) throw new Error(started.error);

      setPhase("putting");
      setMessage("Uploading bytes to storage…");
      const bytes = await file.arrayBuffer();
      const put = await fetch(started.data.upload_url, {
        method: "PUT",
        headers: { "Content-Type": contentType },
        body: bytes,
      });
      if (!put.ok) throw new Error(`Storage upload failed (${put.status}).`);

      setPhase("completing");
      setMessage("Verifying and registering the version…");
      const sha = await sha256Hex(bytes);
      const done = await finishUpload(started.data.version_id, sha);
      if (!done.ok) throw new Error(done.error);

      setPhase("done");
      setMessage(`Version registered (${done.data.status}). Profiling runs in the background.`);
      setDatasetName("");
      setFile(null);
      router.refresh();
    } catch (err) {
      setPhase("error");
      setMessage(err instanceof Error ? err.message : "Upload failed.");
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <label className="cru-field">
        <span className="cru-label">Dataset name</span>
        <input
          className="cru-input"
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          minLength={2}
          maxLength={64}
          required
          placeholder="sales"
        />
      </label>
      <label className="cru-field">
        <span className="cru-label">File (.csv or .parquet)</span>
        <input
          className="cru-input"
          type="file"
          accept=".csv,.parquet"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
        />
        <span className="cru-hint">
          Bytes upload directly to storage; the API never sees them. Max 200&nbsp;MB.
        </span>
      </label>
      <div className="cru-btn-row">
        <button className="cru-btn cru-btn-primary" type="submit" disabled={busy || !file}>
          {busy ? "Working…" : "Upload dataset"}
        </button>
        {message && (
          <span
            className="cru-muted"
            role={phase === "error" ? "alert" : "status"}
            style={{ color: phase === "error" ? "var(--danger)" : undefined, fontSize: "0.88rem" }}
          >
            {message}
          </span>
        )}
      </div>
    </form>
  );
}
