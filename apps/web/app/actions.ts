"use server";

// Server Actions: the only place the browser can trigger a mutation. The API
// key stays on the server (see lib/api.ts, which is `server-only`); the browser
// posts a plain form/JSON and gets back a typed result. Every action returns a
// discriminated result rather than throwing, so client components render a
// precise message instead of a redacted framework error.
import { revalidatePath } from "next/cache";

import {
  ApiError,
  cancelRun as apiCancelRun,
  claimReview as apiClaimReview,
  completeUpload as apiCompleteUpload,
  createRun as apiCreateRun,
  NotConfigured,
  setBudget as apiSetBudget,
  startUpload as apiStartUpload,
  submitReview as apiSubmitReview,
} from "@/lib/api";

export type ActionResult<T = null> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function toError(e: unknown): { ok: false; error: string } {
  if (e instanceof NotConfigured) return { ok: false, error: e.message };
  if (e instanceof ApiError) return { ok: false, error: e.message };
  if (e instanceof Error) return { ok: false, error: e.message };
  return { ok: false, error: "Unexpected error" };
}

export async function beginUpload(input: {
  dataset_name: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}): Promise<ActionResult<{ version_id: string; upload_url: string }>> {
  try {
    const started = await apiStartUpload(input);
    return { ok: true, data: { version_id: started.version_id, upload_url: started.upload_url } };
  } catch (e) {
    return toError(e);
  }
}

export async function finishUpload(
  versionId: string,
  contentSha256: string,
): Promise<ActionResult<{ status: string }>> {
  try {
    const version = await apiCompleteUpload(versionId, contentSha256);
    revalidatePath("/datasets");
    return { ok: true, data: { status: version.status } };
  } catch (e) {
    return toError(e);
  }
}

export async function createRun(input: {
  dataset_version_id: string;
  question: string;
}): Promise<ActionResult<{ run_id: string }>> {
  try {
    const run = await apiCreateRun(input);
    revalidatePath("/runs");
    return { ok: true, data: { run_id: run.id } };
  } catch (e) {
    return toError(e);
  }
}

export async function cancelRun(runId: string): Promise<ActionResult<{ status: string }>> {
  try {
    const run = await apiCancelRun(runId);
    revalidatePath(`/runs/${runId}`);
    revalidatePath("/runs");
    return { ok: true, data: { status: run.status } };
  } catch (e) {
    return toError(e);
  }
}

export async function claimReview(runId: string): Promise<ActionResult<{ status: string }>> {
  try {
    const review = await apiClaimReview(runId);
    revalidatePath("/reviews");
    return { ok: true, data: { status: review.status } };
  } catch (e) {
    return toError(e);
  }
}

export async function updateBudget(
  monthlyLimitUsd: number,
): Promise<ActionResult<{ remaining_usd: number | null }>> {
  try {
    const budget = await apiSetBudget(monthlyLimitUsd);
    revalidatePath("/settings");
    revalidatePath("/dashboard");
    return { ok: true, data: { remaining_usd: budget.remaining_usd } };
  } catch (e) {
    return toError(e);
  }
}

export async function submitReview(
  runId: string,
  decision: "approve" | "reject",
  grades: { groundedness: number; provenance: number; usefulness: number; uncertainty: number },
): Promise<ActionResult<{ status: string }>> {
  try {
    const review = await apiSubmitReview(runId, { decision, grades });
    revalidatePath("/reviews");
    revalidatePath(`/runs/${runId}`);
    return { ok: true, data: { status: review.status } };
  } catch (e) {
    return toError(e);
  }
}
