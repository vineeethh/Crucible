# Efficiency: measured routing, exact cache, and budgets (Phase 8)

Status: Phase 8 · Related: [router-experiment.md](../evaluation/router-experiment.md) ·
[observability.md](observability.md) · [threat-model.md](../security/threat-model.md)

Phase 8's rule: **reduce cost/latency only after quality is measurable, and
never advertise savings that ignore retries, escalations, or false hits.** All
three features default OFF; each has a one-setting rollback.

## Model registry and cost accounting

`crucible.agent.models.registry` is the declared price book: per-model tier and
USD-per-million-token prices. Cost is always `reported/estimated tokens x the
declared price`; an unregistered model yields `cost_usd=None` — the explicit
"unknown cost" marker — never a fabricated zero, so the dashboard's
cost-attribution completeness stays honest. The shipped `fake` models carry
**synthetic** prices (flagged `synthetic_price=True`); they exist so the whole
accounting pipeline — per-attempt attribution, ledger settlement, experiment
deltas — is exercised end to end offline, and every report that uses them says
so. Deployments `register()` their real models and real prices at composition
time.

## The two-tier router

`TieredModelGateway` + `RouterPolicy` (`crucible.agent.router`,
`two-tier@1`) is a *static, declared* policy — never a learned one:

- **Planner**: tier 1 first; escalate to tier 2 when the cheap plan abstains or
  reports confidence below the threshold (0.8). The plan is the only
  pre-execution quality signal.
- **Coder/repair**: tier 1, because generated code is validated by execution
  and verification downstream — a weak program surfaces as a repairable
  failure, not a silent quality loss.
- **Any provider error** on the primary falls back to the secondary
  (`fallback_on_error`), recorded as `route_reason="primary_error"`.

Escalation evidence travels in the per-attempt usage (`escalated`,
`route_reason`), and an escalated call's tokens and cost **include the burned
tier-1 call**. Every run records a `route` attempt with the policy in effect,
so the trace shows which policy produced which answer.

**Enable**: `ROUTER_POLICY=two-tier` on the worker (for `openai_compat`, also
set `OPENAI_MODEL_LITE`). **Rollback**: set it back to `default` — no deploy,
no data change. The held-out experiment
([router-experiment.md](../evaluation/router-experiment.md), regenerate with
`python -m crucible.evaluation router --suite ... --executor docker`) is the
evidence that licenses enabling it: the routed policy must PASS the same paired
quality gate the release pipeline uses.

## The exact cache

`EXACT_CACHE` replays a **fully verified** answer when every identity input
matches. The key binds `tenant | dataset content sha | config signature
(models + prompts + router policy) | whitespace-normalized question`, and the
SQL lookup is *additionally* org-scoped — the key is defense in depth, not the
only control (threat T5). Consequences:

- a new dataset version, a model/prompt/policy change, or another tenant is a
  structurally different key → miss;
- normalization is whitespace-only: case changes may change meaning (a column
  name), so they miss rather than false-hit;
- only `answered` runs whose verification decision was `answer` are stored —
  review-approved and abstained runs are never cached;
- on a hit the stored identity inputs are **re-validated**; any mismatch is a
  *false hit*: counted (`/v1/metrics/cache`, the dashboard's "Exact cache
  safety" panel), the entry invalidated, and the run recomputed. A suspect
  entry is never served.

A replayed answer carries `cached: true` and the original provenance; the run's
attempts record `cache: hit|miss|false_hit|store` spans.

**Enable**: `EXACT_CACHE_ENABLED=true` on the worker. **Rollback**: unset it;
entries stay inert (and can be truncated without data loss — the cache is
derived state).

**Semantic caching is disabled and has no flag.** Master plan §12.3: it stays
off unless an approved evaluation demonstrates acceptable false-hit behavior.
Adding it requires a new evaluation, a new ADR, and a new threat-model pass.

## The budget ledger

`budgets` (one row per org: monthly USD limit; absent = unenforced) +
`budget_entries` (append-only ledger):

1. **Admission** (CreateRun): if `month spend + estimate > limit`, the run is
   refused with `409 budget-exhausted` *before* any spend, and the refusal is
   audited. Otherwise a `reserve` entry (a flat estimate) is written.
2. **Settlement** (worker, at terminal): a `settle` entry with the actual
   summed attempt cost plus a `release` entry reversing the reserve. A partial
   unique index on `(run_id, kind)` makes settlement idempotent under
   at-least-once job delivery.
3. **Month spend** = SUM of the month's entries, so in-flight reserves count —
   parallel submissions cannot stampede past the limit by racing settlement.

Surface: `GET/PUT /v1/budget` (PUT is owner-only and audited), the dashboard's
"Cost & budget" panel, and the Settings page form.

## Verification map

| Claim | Evidence |
|---|---|
| Router decisions deterministic; escalation/fallback per policy; burned-call accounting | `tests/unit/test_agent_router.py` (15 tests) |
| Cache key binds tenant/dataset/config/question; false hits quarantined; abstain/review never cached; hit skips the sandbox | `tests/unit/test_agent_cache.py` (9 tests) |
| Cache cannot cross tenants (API + stolen-key SQL probe) | `tests/integration/test_budget_and_cache.py` |
| Admission refuses at the limit; reserve→settle→release reconciles; settlement idempotent | `tests/integration/test_budget_and_cache.py` |
| Routed policy quality-gated vs default on the held-out suite (real sandbox) | [router-experiment.md](../evaluation/router-experiment.md) |
