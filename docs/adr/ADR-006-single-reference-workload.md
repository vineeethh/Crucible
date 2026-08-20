# ADR-006: One reference workload before an adapter SDK

Status: Accepted · Date: 2026-07-14

## Context
The temptation is to build an agent-agnostic evaluation framework immediately. But
abstractions designed before a real, complete workload tend to become generic plumbing
with no proof of value, and the project's story depends on honest, end-to-end
reliability claims.

## Decision
v1 ships exactly one workload — data-analysis over uploaded tabular datasets — carried
through the full story: ingestion, sandboxed execution, offline evaluation, tracing,
regression gates, and operations. A harness seam (case schema, scorer interfaces,
executor port) is kept clean so post-v1 adapters (e.g., read-only text-to-SQL) are
possible, but no adapter SDK is built in v1.

## Alternatives considered
- **Generic agent-benchmark platform first** — rejected: produces breadth without a
  single defensible reliability claim.
- **Two workloads in parallel** — rejected: doubles eval authoring and sandbox surface
  for a solo developer without doubling the evidence value.

## Consequences
- All v1 claims are scoped to one workload and say so explicitly.
- Case/scorer/executor interfaces are designed as seams from Phase 1, resisting
  workload-specific leakage into `packages/evaluation`.
- Post-v1 adapter work (v1.1) has a proven template to generalize from.

## Revisit trigger
v1.0 shipped with its evidence, or a committed external user whose verifiable workload
fits the existing seams.
