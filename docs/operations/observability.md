# Observability & Online Evaluation

Status: Phase 6 · Owner: on-call / project owner
Related: [alert-runbook.md](alert-runbook.md) ·
[sandbox-incident-runbook.md](sandbox-incident-runbook.md) ·
[threat-model.md](../security/threat-model.md) ·
[judge-calibration-report.md](../evaluation/judge-calibration-report.md)

Crucible's reliability story is *evidence, not vibes*: every terminal run carries
a trace, a cost, a latency, its versions, and — on failure — a taxonomy category.
This document is the map: what the signals are, where they come from, and the
one boundary that must never be crossed (redaction before export).

## Layering

Observability is a leaf package (`crucible.observability`) that imports **only**
the domain. It holds no database or transport dependency; it is a set of pure
functions over plain telemetry rows. The API composes it: the application layer
reads the rows (`GetRunTelemetry`, `ListRunEvents`, `ListRunAttempts`), the
router hands them to `reliability()`, `cost_latency()`, `build_run_trace()`, and
returns the result. This keeps the evaluation/observability plane decoupled from
the serving plane (ADR-001) — a metrics change cannot reach into request
handling, and the aggregation functions are unit-testable without a stack.

## The redaction boundary (threat model T8)

Nothing leaves the trust boundary — an exported trace, a third-party judge call,
a shared debugging bundle — without passing through `crucible.observability.redaction`:

- `redact_text` strips secrets (Crucible `ck_…` keys, provider `sk-`/`AKIA`/`ghp_`
  tokens, credentialed URLs, bearer/token/key assignments) and PII (email, SSN,
  card, phone), replacing each with a typed `[REDACTED:secret|pii]` marker.
- `export_safe_excerpt` redacts, then bounds length, and attaches the SHA-256 of
  the **original** so two runs with the same prompt are still correlatable
  without exposing the prompt.
- `redact_payload` walks nested structures, dropping sensitive keys wholesale
  (`*_hash`, `code_source`, `secret`, …) and redacting free-text values.

Exported traces carry a **tenant pseudonym** (`pseudonymize(org_id)`, a salted
one-way hash), never the raw organization id, and never dataset contents. The
run trace's `redaction_state` records that this pass happened.

## Signals

### Trace completeness (the DoD metric)

A terminal run's trace is complete when it has its config manifest, its version
metadata (release + at least one model attribution, unless it never reached a
model), node-level events, and a terminal event. `build_run_trace` assembles the
trace from the run's append-only events and attempts; `_completeness` lists what
is missing. Fleet-wide completeness is `reliability(...).trace_completeness`.
Target: **≥ 0.99**. A run you cannot fully explain is a reliability defect.

### Reliability

`reliability(runs)` returns totals, terminal/answered/abstained counts, the
**technical completion rate** (terminal-and-not-operationally-cancelled ÷
terminal), trace completeness, and the **failure taxonomy** histogram. Cancelled
runs are operational, not quality failures, and are excluded from the completion
rate. The failure taxonomy is the categorized `failure_category` of abstentions
(see [failure-taxonomy.md](../evaluation/failure-taxonomy.md)).

### Cost & latency

`cost_latency(runs)` sums per-run cost, reports **cost attribution completeness**
(fraction of runs with a non-null cost — an unattributed run is a blind spot),
and latency p50/p95/p99 (nearest-rank). Cost and latency are attributed per run
from the agent attempts, so a spend or latency spike is traceable to the runs
that caused it.

## SLIs, SLOs, and alerts

Alerts (`evaluate_slo_alerts`) are pure functions over the reliability metrics
plus a containment-breach count, so they are exercised in unit tests and in a
staging drill — not only in production. Rules fire on user-impacting symptoms and
security events, never on a single transient model failure.

| Rule | Severity | Fires when | Runbook |
|------|----------|-----------|---------|
| `sandbox_containment` | SEV1 | any confirmed containment breach | [sandbox-incident-runbook.md](sandbox-incident-runbook.md) |
| `trace_completeness` | SEV2 | completeness < 0.99 | [alert-runbook.md](alert-runbook.md#trace-completeness) |
| `technical_completion` | SEV2 | completion rate < 0.80 | [alert-runbook.md](alert-runbook.md#technical-completion) |
| `abstention_spike` | SEV3 | abstention rate > 0.50 | [alert-runbook.md](alert-runbook.md#abstention-spike) |

The containment rule is **always** reported (firing or not) so its health is
visible at a glance; the others appear only when firing. Thresholds live in
`SloThresholds` and are overridable per deployment.

## Scores: typed, sourced, never silently a gate

Every observation about a run or dataset is a typed `Score`
(boolean/numeric/categorical/text) tagged with its **source**:

- `deterministic` — the online sampler's checks (below) and Tier-1 oracle results.
- `human` — reviewer rubric grades from the review queue.
- `judge` — the LLM-as-judge, **secondary criteria only** (see below).

The Tier-1 deterministic oracle is the only thing that gates correctness. Human
and judge scores are recorded as evidence and trends; they never override the
oracle (master plan §10).

## Human review

A reviewer claims a run awaiting review (`WAITING_REVIEW`), applies the versioned
rubric (`review-rubric@1`: groundedness, provenance, usefulness, uncertainty,
each 0–2), and submits approve/reject. Claims are **optimistic and exclusive**: a
`SELECT … FOR UPDATE` plus a unique `run_id` means exactly one reviewer holds a
run; a second claim gets a 409. Only the claimant may submit. A claim lapses
after `CLAIM_TTL_SECONDS` (900s) so an abandoned claim does not wedge the queue.
Submitting records the grades as `human` scores and enqueues the Phase-4
review-resolution job (approve → synthesize, reject → abstain).

Reviewer identity is the generic `actor_id`, so both OIDC users and API-key
service accounts can review; `human_reviews` carries no `users` foreign key.

## Online evaluation

`run_online_checks` (worker cron, hourly) samples terminal runs **per tenant**
(deterministic stratified sample: most-recent N per status) and records cheap
deterministic checks — currently trace completeness — as `deterministic` scores.
This is the drift signal that costs no model call; model/human scoring of a
smaller sample is layered on top by the review queue and the calibrated judge.
The job holds no user, so it synthesizes a per-org **system principal** scoped to
one organization; the command still enforces `EVAL_WRITE` and reads only that
tenant's runs (T5).

## LLM-as-a-judge (secondary, calibrated, held-out)

The judge scores **explanation quality only** (groundedness, provenance,
usefulness, uncertainty) — never correctness. Before use it is calibrated against
a held-out set of human-labelled examples using **quadratic-weighted Cohen's
kappa** per dimension. The published agreement report lives at
[judge-calibration-report.md](../evaluation/judge-calibration-report.md) and is
regenerated by `scripts/generate_calibration_report.py`. A judge whose agreement
regresses is pulled from the secondary criteria until re-calibrated.

## Where the signals surface

- `GET /v1/metrics/reliability` — reliability metrics.
- `GET /v1/metrics/cost` — cost & latency.
- `GET /v1/metrics/alerts` — current alert states (with runbook links).
- `GET /v1/runs/{id}/trace` — the redacted, export-safe trace for one run.
- `GET /v1/reviews`, `POST /v1/reviews/{id}/claim|submit` — the review queue.
- Web: `/dashboard` (metrics) and `/reviews` (queue).
