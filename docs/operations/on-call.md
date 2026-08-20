# On-call

Status: Phase 10 · Owner: project owner
Related: [incident-response.md](incident-response.md) ·
[alert-runbook.md](alert-runbook.md) · [support-runbook.md](support-runbook.md)

Who responds, to what, and how it is tested. During the private beta the cohort
is small and the rotation is minimal — but the *route* and the *test* are real.

## Ownership

- **On-call owner (beta):** the project owner is the single on-call and default
  incident owner. As the cohort grows, this becomes a named weekly rotation.
- **Escalation:** none above the owner in beta; document the security contact
  from [SECURITY.md](../../SECURITY.md) for external reports.

## What pages

Paging maps to the observability-as-code alert policies
(`infra/observability/alerts.yaml`), which mirror the app's SLO rules:

| Alert | Severity | Meaning |
|---|---|---|
| `sandbox_containment` | SEV1 | Confirmed containment breach → sandbox runbook |
| `readiness` | SEV1 | `/readyz` down (a dependency probe failing) |
| `trace_completeness` | SEV2 | Fleet trace completeness < 99% |
| `technical_completion` | SEV2 | Completion rate < 80% |
| `abstention_spike` | SEV3 | Abstention rate > 50% (often *correct*; investigate) |
| `budget_admission_denials` | SEV3 | Elevated budget refusals |

Runbook per alert: [alert-runbook.md](alert-runbook.md).

## Alert test (exercised, not assumed)

The alert path is verified two ways, so a silent alerting failure is caught:

1. **Rule logic** is unit-tested — the SLO rules are pure functions
   (`tests/unit/test_observability_metrics_trace.py`:
   `test_alerts_fire_on_low_completeness_and_containment`,
   `test_alerts_clear_when_healthy`).
2. **Delivery** is tested by a scheduled synthetic: the production canary
   (`scripts/prod_canary.py`) runs post-deploy and on a schedule; a red canary
   must produce a page. Confirm the notification channel actually delivers by
   firing a test alert each on-call handover.

## Handover checklist

- [ ] Paging channel verified (a test alert delivered).
- [ ] `scripts/prod_canary.py` green against production.
- [ ] No open SEV1/SEV2; open action items noted.
- [ ] Weekly review (`scripts/weekly_review.py`) read for trends.
