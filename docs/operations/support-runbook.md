# Runbook: Support & feedback (private beta)

Status: Phase 10 · Owner: project owner / on-call
Related: [on-call.md](on-call.md) · [incident-response.md](incident-response.md) ·
[beta-onboarding.md](beta-onboarding.md)

The support surface for a bounded, named cohort. Keep it light but real: a route
in, a triage rule, and a feedback loop that does not corrupt the quality signal.

## Support route

- **Channel:** a dedicated address / shared channel given to each cohort member
  at onboarding (e.g. `beta-support@crucible.example`). One route, so nothing is
  lost.
- **SLA (beta):** acknowledge within one business day; no uptime guarantee — the
  beta terms say so ([terms-of-service.md](../legal/terms-of-service.md)).

## Triage

1. **Is it an incident?** (multiple tenants, data exposure, sustained errors, a
   firing SEV1/SEV2 alert) → [incident-response.md](incident-response.md).
2. **Is it one tenant, one run?** Pull the run's trace
   (`GET /v1/runs/{id}/trace`) and attempts — the evidence is designed to answer
   "why did this run do that" without touching raw data.
3. **Is it a data/privacy request?** (export, deletion) →
   [retention-policy.md](retention-policy.md) (`scripts/admin.py`, dry-run
   first).
4. **Is it a quality complaint?** A wrong answer is an **evaluation** matter, not
   a support hotfix — capture the case, add it to a suite as a candidate, and
   let the gate decide. Never patch the agent off a single anecdote.

## Feedback loop (without polluting the quality signal)

Beta *usage* is not correctness evidence. The trap is "users said it's good, so
it's correct." Keep them separate:

- **Product feedback** (UX, gaps, requests) → the backlog.
- **Quality feedback** (a wrong/abstained answer that should differ) → a proposed
  eval case, scored against a trusted oracle, gated by the paired bootstrap
  (`python -m crucible.evaluation run`). Only the gate promotes a change.
- The **weekly review** (`scripts/weekly_review.py`) reconciles the two:
  reliability + cost + cache safety from telemetry, and the current eval gate
  status — together, anonymized.

## Common requests → action

| Request | Action |
|---|---|
| "Raise my limit" | `scripts/admin.py set-budget --slug … --usd …` |
| "Delete my data" | `scripts/admin.py purge-org --slug …` (dry run → `--apply`) |
| "Pause my access" | `scripts/admin.py suspend --slug …` |
| "New teammate needs access" | Mint a scoped API key (`POST /v1/api-keys`) or add a membership |
| "A run gave a wrong number" | Capture as an eval case; do not hotfix the agent |

## Verification before closing a ticket

- [ ] The tenant's issue is resolved or has a tracked follow-up.
- [ ] No cross-tenant data was exposed in the process.
- [ ] Quality complaints are in the eval pipeline, not patched ad hoc.
