/*
 * Presentational primitives for the Crucible product UI.
 *
 * These are framework-agnostic React components — no Next, no data fetching, no
 * client state — so they render identically in Server Components and are trivial
 * to reason about. Styling is entirely class-based (see tokens.css); status is
 * never conveyed by colour alone (a dot/icon plus a text label — WCAG 1.4.1).
 */
import type { CSSProperties, ReactNode } from "react";

type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral";

// Maps every terminal/lifecycle status the API can emit to a semantic tone.
const STATUS_TONE: Record<string, StatusTone> = {
  ready: "ok",
  answered: "ok",
  pass: "ok",
  approve: "ok",
  pending_profile: "warn",
  awaiting_upload: "neutral",
  queued: "neutral",
  running: "info",
  waiting_review: "warn",
  needs_human_review: "warn",
  abstained: "warn",
  flag: "warn",
  reject: "danger",
  invalid: "danger",
  policy_denied: "danger",
  budget_exhausted: "danger",
  block: "danger",
  cancelled: "neutral",
};

function toneVar(tone: StatusTone): string {
  return `var(--${tone})`;
}

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "neutral";
  const color = toneVar(tone);
  return (
    <span
      className="cru-badge"
      style={{
        color,
        borderColor: `color-mix(in srgb, ${color} 45%, transparent)`,
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
      }}
    >
      <span className="cru-badge-dot" aria-hidden style={{ background: color }} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

const SEVERITY_TONE: Record<string, StatusTone> = {
  sev1: "danger",
  sev2: "warn",
  sev3: "neutral",
};

export function SeverityTag({ severity }: { severity: string }) {
  const color = toneVar(SEVERITY_TONE[severity] ?? "neutral");
  return (
    <span style={{ color, fontWeight: 650 }}>{severity.toUpperCase()}</span>
  );
}

export function GateBadge({ status }: { status: string }) {
  return <StatusBadge status={status} />;
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <code className="cru-mono" title={title}>
      {children}
    </code>
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return <span className="cru-tag">{children}</span>;
}

export function Panel({
  title,
  actions,
  pad = false,
  children,
}: {
  title?: string;
  actions?: ReactNode;
  pad?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="cru-panel">
      {(title || actions) && (
        <div className="cru-panel-head">
          {title ? <h2 className="cru-panel-title">{title}</h2> : <span />}
          {actions}
        </div>
      )}
      <div className={pad ? "cru-panel-body cru-panel-pad" : "cru-panel-body"}>{children}</div>
    </section>
  );
}

export function DataTable({
  headers,
  rows,
  empty,
  columnStyles,
}: {
  headers: string[];
  rows: ReactNode[][];
  empty: string;
  columnStyles?: (CSSProperties | undefined)[];
}) {
  if (rows.length === 0) {
    return <p className="cru-empty">{empty}</p>;
  }
  return (
    <table className="cru-table">
      <thead>
        <tr>
          {headers.map((h) => (
            <th key={h} scope="col">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((cells, i) => (
          <tr key={i}>
            {cells.map((cell, j) => (
              <td key={j} style={columnStyles?.[j]}>
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <section className="cru-metric-grid">{children}</section>;
}

export function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="cru-metric">
      <div className="cru-metric-label">{label}</div>
      <div className="cru-metric-value">{value}</div>
      {hint && <div className="cru-metric-hint">{hint}</div>}
    </div>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "ok";
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`cru-callout ${tone}`} role={tone === "danger" ? "alert" : undefined}>
      {title && <p className="cru-callout-title">{title}</p>}
      <p className="cru-callout-body">{children}</p>
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="cru-kv">
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Pre({ children }: { children: ReactNode }) {
  return <pre className="cru-pre">{children}</pre>;
}

/**
 * Loading placeholder: a column of pulsing bars with staggered widths so the
 * skeleton suggests content shape rather than a uniform block. Purely
 * presentational — pages render it from route-level `loading.tsx` files.
 */
export function Skeleton({ lines = 4 }: { lines?: number }) {
  const widths = ["62%", "94%", "83%", "71%", "89%", "58%"];
  return (
    <div role="status" aria-label="Loading" className="cru-panel-pad">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="cru-skeleton" style={{ width: widths[i % widths.length] }} />
      ))}
    </div>
  );
}

/** Standard page-level loading frame: a title bar plus a skeleton panel. */
export function PageSkeleton() {
  return (
    <div aria-busy="true">
      <span className="cru-skeleton" style={{ width: 180, height: 22 }} />
      <div className="cru-panel">
        <div className="cru-panel-body">
          <Skeleton lines={5} />
        </div>
      </div>
    </div>
  );
}
