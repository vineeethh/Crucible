# Runbook: Incident response

Status: Phase 10 · Owner: on-call / project owner
Related: [on-call.md](on-call.md) · [alert-runbook.md](alert-runbook.md) ·
[sandbox-incident-runbook.md](sandbox-incident-runbook.md) ·
[rollback-runbook.md](rollback-runbook.md) ·
[disaster-recovery.md](disaster-recovery.md)

The general process; the specific playbooks (sandbox breach, SLO alerts,
rollback, DR) are linked and take precedence for their domain.

## Severity

| Sev | Definition | Response |
|---|---|---|
| **SEV1** | Security/containment breach, cross-tenant data exposure, or full outage | Page immediately; drop other work |
| **SEV2** | User-impacting reliability regression (SLO breach), partial outage | Page; respond within the hour |
| **SEV3** | Degraded/annoying, no data or availability impact | Next business day |

A suspected sandbox containment breach is **always SEV1** →
[sandbox-incident-runbook.md](sandbox-incident-runbook.md).

## The loop: Detect → Contain → Eradicate → Recover → Review

1. **Detect.** Source: a firing alert (`/v1/metrics/alerts`, the
   observability-as-code policies), a failed canary (`scripts/prod_canary.py`),
   or a support report. Declare severity and an incident owner.
2. **Contain.** Stop the bleeding *before* diagnosing:
   - bad release → roll back traffic to the prior revision
     ([rollback-runbook.md](rollback-runbook.md));
   - sandbox suspicion → `EXECUTOR_BACKEND=fake` / scale worker to zero;
   - a single abusive/compromised tenant → `scripts/admin.py suspend --slug …`;
   - a leaked credential → revoke the API key (`DELETE /v1/api-keys/{id}`) and
     rotate the affected secret.
3. **Preserve evidence.** Do not delete traces, audit events, containers, or work
   dirs yet. The audit log (actor + action) and run traces are the record.
4. **Eradicate & recover.** Fix forward or restore
   ([disaster-recovery.md](disaster-recovery.md) for data). Verify with
   `/readyz`, the canary, and the relevant alert clearing.
5. **Review.** Blameless write-up: timeline, root cause, what detection/response
   worked, action items. Update the threat model and the relevant runbook with
   what was learned (the review-cadence rule in the threat model).

## Data-exposure incidents (privacy)

If tenant data may have crossed a boundary: treat as SEV1, identify the affected
tenants from the audit log, contain (suspend / revoke / rotate), and follow the
notification duties in the [data-processing notice](../legal/data-processing-notice.md).
The redaction boundary (T8) and per-tenant scoping exist precisely to make this
rare; a breach of them is a top-severity event.

## Contacts & ownership

On-call owner and escalation are in [on-call.md](on-call.md). During the private
beta the project owner is the default incident owner.
