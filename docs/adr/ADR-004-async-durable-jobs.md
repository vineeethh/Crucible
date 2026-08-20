# ADR-004: Asynchronous jobs with durable state

Status: Accepted · Date: 2026-07-14

## Context
Agent + sandbox work routinely exceeds HTTP request budgets, needs resume after worker
interruption, and can terminate in human review — a state that outlives any connection.

## Decision
`POST /v1/runs` returns `202` with a run ID and SSE URL. Runs are durable rows with an
explicit state machine (`queued → running → … → terminal`), an immutable config
manifest, append-only run events, and idempotency keys. Workers claim runs from a
Redis-backed queue (arq); progress streams over SSE with polling fallback.

## Alternatives considered
- **Synchronous endpoint** — rejected: ties availability to model/sandbox duration and
  precludes review/resume semantics.
- **Temporal/Celery** — Temporal is excellent but over-scoped for a solo v1; Celery is
  heavier than needed for async Python. arq is sufficient and replaceable behind a port.

## Consequences
- Every state transition is explicit and auditable; worker restart resumes safely
  (tested in Phase 4).
- Clients must handle async semantics; SSE reconnect/backoff is a frontend requirement.
- Cancellation must propagate API → queue → worker → sandbox and leave a truthful
  terminal status.

## Revisit trigger
Workflow complexity (multi-step human interactions, long timers, compensation) that
would materially benefit from Temporal-class orchestration.
