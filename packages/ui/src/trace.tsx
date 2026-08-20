/*
 * Trace and config views.
 *
 * `Trace` renders the export-safe run trace (already redacted server-side: a
 * tenant pseudonym, hashes, and bounded excerpts — never raw prompts or data).
 * It is deliberately tolerant of missing fields: a partial trace is still shown,
 * with completeness surfaced honestly rather than hidden.
 */
import type { ReactNode } from "react";

import { KeyValue, Mono, StatusBadge } from "./components";

export type TraceSpan = {
  name: string;
  seq: number;
  attributes?: Record<string, unknown>;
};

export type ExportedTrace = {
  run_id: string;
  tenant: string;
  release: string;
  model_ids: string[];
  dataset_sha256: string | null;
  redaction_state: string;
  complete: boolean;
  spans: TraceSpan[];
  question?: {
    excerpt: string;
    sha256: string;
    length: number;
    truncated: boolean;
    redaction_state: string;
  };
};

function spanMeta(attrs: Record<string, unknown> | undefined): string {
  if (!attrs) return "";
  const parts: string[] = [];
  if (attrs.model_id) parts.push(String(attrs.model_id));
  if (attrs.exit_class) parts.push(String(attrs.exit_class));
  if (attrs.duration_ms != null) parts.push(`${attrs.duration_ms} ms`);
  if (attrs.event_type && parts.length === 0) parts.push(String(attrs.event_type));
  return parts.join(" · ");
}

export function Trace({ trace }: { trace: ExportedTrace }) {
  const maxDuration = Math.max(
    1,
    ...trace.spans.map((s) => Number(s.attributes?.duration_ms ?? 0)),
  );
  return (
    <div>
      <KeyValue
        items={[
          ["run", <Mono key="r">{trace.run_id}</Mono>],
          ["tenant (pseudonym)", <Mono key="t">{trace.tenant}</Mono>],
          ["release", <Mono key="rel">{trace.release}</Mono>],
          [
            "model versions",
            trace.model_ids.length ? (
              trace.model_ids.map((m) => <Mono key={m}>{m} </Mono>)
            ) : (
              <span className="cru-muted">—</span>
            ),
          ],
          [
            "dataset sha256",
            <Mono key="d">{trace.dataset_sha256?.slice(0, 24) ?? "—"}</Mono>,
          ],
          [
            "completeness",
            <StatusBadge key="c" status={trace.complete ? "ready" : "invalid"} />,
          ],
          ["redaction", <Mono key="rd">{trace.redaction_state}</Mono>],
          ...(trace.question
            ? ([
                [
                  "question (redacted excerpt)",
                  <span key="q">
                    {trace.question.excerpt}
                    {trace.question.truncated ? "…" : ""}{" "}
                    <span className="cru-muted">
                      (sha256 {trace.question.sha256.slice(0, 12)}, {trace.question.length} chars)
                    </span>
                  </span>,
                ],
              ] as [string, ReactNode][])
            : []),
        ]}
      />
      <div className="cru-trace" aria-label="span timeline">
        {trace.spans.map((s, i) => {
          const dur = Number(s.attributes?.duration_ms ?? 0);
          const width = dur > 0 ? Math.max(8, (dur / maxDuration) * 160) : 8;
          return (
            <div className="cru-span" key={`${s.seq}-${i}`}>
              <span className="cru-span-bar" style={{ width }} aria-hidden />
              <span className="cru-span-name">{s.name}</span>
              <span className="cru-span-meta">{spanMeta(s.attributes)}</span>
            </div>
          );
        })}
        {trace.spans.length === 0 && <p className="cru-empty">No spans recorded for this run.</p>}
      </div>
    </div>
  );
}

/**
 * Renders a run's config manifest (versions, hashes, limits) as a key/value
 * grid. Nested objects are shown as compact JSON; this is the "what produced
 * this run" panel that makes a run reproducible.
 */
export function ConfigView({ config }: { config: Record<string, unknown> }) {
  const entries = Object.entries(config);
  if (entries.length === 0) {
    return <p className="cru-empty">No config manifest recorded.</p>;
  }
  return (
    <KeyValue
      items={entries.map(([k, v]) => [
        k,
        typeof v === "object" && v !== null ? (
          <Mono>{JSON.stringify(v)}</Mono>
        ) : (
          <Mono>{String(v)}</Mono>
        ),
      ])}
    />
  );
}
