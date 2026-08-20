// Server-only API client.
//
// The API key lives in a server-side env var and is used exclusively from
// Server Components / route handlers. It is never shipped to the browser —
// a credential in client JS is a credential in the user's clipboard.
import "server-only";

const API_URL = process.env.CRUCIBLE_API_URL ?? "http://localhost:8100";
const API_KEY = process.env.CRUCIBLE_API_KEY ?? "";

export type Dataset = {
  id: string;
  name: string;
  created_at: string;
};

export type DatasetVersion = {
  id: string;
  dataset_id: string;
  version_no: number;
  status: "awaiting_upload" | "pending_profile" | "ready" | "invalid";
  content_sha256: string | null;
  schema_hash: string | null;
  row_count: number | null;
  column_count: number | null;
  size_bytes: number | null;
  invalid_reason: string | null;
  created_at: string | null;
};

export type Run = {
  id: string;
  dataset_version_id: string;
  question: string;
  status: string;
  terminal_detail: string | null;
  failure_category: string | null;
  cancel_requested: boolean;
  answer: {
    value: unknown;
    text: string;
    limitations: string;
    provenance: {
      operation: string;
      columns_used: string[];
      code_sha256: string;
      attempt_count: number;
      executor_backend: string;
      image_ref: string;
      dataset_sha256: string | null;
    };
  } | null;
  verification: Record<string, unknown> | null;
  config_manifest: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type RunEvent = {
  sequence_no: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Attempt = {
  attempt_no: number;
  kind: string;
  sequence_no: number;
  payload: Record<string, unknown>;
  model_provider: string | null;
  model_id: string | null;
  exit_class: string | null;
  failure_category: string | null;
  duration_ms: number | null;
  source_sha256: string | null;
  created_at: string;
};

export class NotConfigured extends Error {}

/** The API could not be reached at all (server down, wrong URL, network). */
export class ApiUnreachable extends Error {}

/** A structured API error carrying the RFC-7807 problem detail when present. */
export class ApiError extends Error {
  status: number;
  type: string;
  constructor(status: number, type: string, detail: string) {
    super(detail);
    this.status = status;
    this.type = type;
  }

  /** True for authentication/authorization failures (stale/invalid key, no
   * membership, suspended org) — recoverable by fixing the credential. */
  get isAuth(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

function requireKey(): string {
  if (!API_KEY) {
    throw new NotConfigured(
      "CRUCIBLE_API_KEY is not set. Mint one with scripts/onboard_beta_tenant.py " +
        "(or scripts/seed_demo.py) and set it in apps/web/.env.local.",
    );
  }
  return API_KEY;
}

async function fail(response: Response, path: string): Promise<never> {
  let type = "about:blank";
  let detail = `${response.status}`;
  try {
    const body = (await response.json()) as { type?: string; detail?: string; title?: string };
    type = body.type ?? type;
    detail = body.detail ?? body.title ?? detail;
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(response.status, type, `API ${path} failed: ${detail}`);
}

/** Fetch that converts a transport failure (API down / wrong URL) into a typed
 * error, so callers never see a raw "fetch failed". */
async function request(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, init);
  } catch (cause) {
    throw new ApiUnreachable(
      `Could not reach the API at ${API_URL}. Is it running, and is CRUCIBLE_API_URL correct?`,
      { cause },
    );
  }
}

/** Classify an error thrown by the client into a friendly "setup required"
 * message, or null if it is a genuine/unexpected failure the error boundary
 * should surface. A missing/stale key, a suspended org, or an unreachable API
 * are all operator-actionable states — not app crashes. */
export function setupMessage(error: unknown): string | null {
  if (error instanceof NotConfigured) return error.message;
  if (error instanceof ApiUnreachable) return error.message;
  if (error instanceof ApiError && error.isAuth) {
    return (
      `${error.message}. The CRUCIBLE_API_KEY in apps/web/.env.local is missing, ` +
      "expired, or its organization was reset/suspended — mint a fresh one with " +
      "scripts/onboard_beta_tenant.py or scripts/seed_demo.py."
    );
  }
  return null;
}

async function get<T>(path: string): Promise<T> {
  const key = requireKey();
  const response = await request(path, {
    headers: { Authorization: `Bearer ${key}` },
    cache: "no-store",
  });
  if (!response.ok) await fail(response, path);
  return (await response.json()) as T;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const key = requireKey();
  const response = await request(path, {
    method,
    headers: {
      Authorization: `Bearer ${key}`,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!response.ok) await fail(response, path);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type Reliability = {
  total: number;
  terminal: number;
  terminal_states: Record<string, number>;
  answered: number;
  abstained: number;
  technical_completion_rate: number;
  trace_completeness: number;
  failure_taxonomy: Record<string, number>;
};

export type CostLatency = {
  runs_with_cost: number;
  total_cost_usd: number;
  cost_attribution_completeness: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  latency_p99_ms: number;
};

export type AlertRow = {
  rule_id: string;
  severity: string;
  firing: boolean;
  detail: string;
  runbook: string;
};

export type ReviewQueueItem = {
  run_id: string;
  question: string;
  created_at: string;
  review_status: string | null;
  verification: Record<string, unknown> | null;
};

export type Me = {
  actor_type: string;
  actor_id: string;
  organization_id: string;
  role: string;
  permissions: string[];
};

export type ApiKeyInfo = {
  id: string;
  name: string;
  prefix: string;
  role: string;
  scopes: string[] | null;
  expires_at: string | null;
  revoked_at: string | null;
};

// The export-safe trace shape returned by GET /v1/runs/{id}/trace. Mirrors the
// design system's ExportedTrace (kept here so lib stays free of a UI import).
export type Trace = {
  run_id: string;
  tenant: string;
  release: string;
  model_ids: string[];
  dataset_sha256: string | null;
  redaction_state: string;
  complete: boolean;
  spans: Array<{ name: string; seq: number; attributes?: Record<string, unknown> }>;
  question?: {
    excerpt: string;
    sha256: string;
    length: number;
    truncated: boolean;
    redaction_state: string;
  };
};

export type StartUpload = {
  dataset_id: string;
  version_id: string;
  upload_url: string;
  expires_seconds: number;
};

export type Budget = {
  monthly_limit_usd: number | null;
  month_spend_usd: number;
  remaining_usd: number | null;
};

export type CacheStats = {
  hits: number;
  misses: number;
  false_hits: number;
  stores: number;
  hit_rate: number;
};

export const getReliability = () => get<Reliability>("/v1/metrics/reliability");
export const getCostLatency = () => get<CostLatency>("/v1/metrics/cost");
export const getAlerts = () => get<AlertRow[]>("/v1/metrics/alerts");
export const getReviewQueue = () => get<ReviewQueueItem[]>("/v1/reviews");
export const getBudget = () => get<Budget>("/v1/budget");
export const getCacheStats = () => get<CacheStats>("/v1/metrics/cache");
export const setBudget = (monthlyLimitUsd: number) =>
  send<Budget>("PUT", "/v1/budget", { monthly_limit_usd: monthlyLimitUsd });

export const getMe = () => get<Me>("/v1/me");
export const listApiKeys = () => get<ApiKeyInfo[]>("/v1/api-keys");

export const listDatasets = () => get<Dataset[]>("/v1/datasets");
export const listVersions = (datasetId: string) =>
  get<DatasetVersion[]>(`/v1/datasets/${datasetId}/versions`);
export const listRuns = () => get<Run[]>("/v1/runs?limit=50");
export const getRun = (runId: string) => get<Run>(`/v1/runs/${runId}`);
export const getRunEvents = (runId: string) => get<RunEvent[]>(`/v1/runs/${runId}/events`);
export const getRunAttempts = (runId: string) => get<Attempt[]>(`/v1/runs/${runId}/attempts`);
export const getRunTrace = (runId: string) => get<Trace>(`/v1/runs/${runId}/trace`);

// ------------------------------------------------------------------ mutations

export const startUpload = (input: {
  dataset_name: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}) => send<StartUpload>("POST", "/v1/datasets/uploads", input);

export const completeUpload = (versionId: string, contentSha256: string) =>
  send<DatasetVersion>("POST", `/v1/datasets/versions/${versionId}/complete`, {
    content_sha256: contentSha256,
  });

export const createRun = (input: { dataset_version_id: string; question: string }) =>
  send<Run>("POST", "/v1/runs", input);

export const cancelRun = (runId: string) => send<Run>("POST", `/v1/runs/${runId}/cancel`);

export const claimReview = (runId: string) =>
  send<{ run_id: string; status: string; rubric_version: string; decision: string | null }>(
    "POST",
    `/v1/reviews/${runId}/claim`,
  );

export const submitReview = (
  runId: string,
  input: {
    decision: "approve" | "reject";
    grades: {
      groundedness: number;
      provenance: number;
      usefulness: number;
      uncertainty: number;
    };
  },
) =>
  send<{ run_id: string; status: string; rubric_version: string; decision: string | null }>(
    "POST",
    `/v1/reviews/${runId}/submit`,
    input,
  );
