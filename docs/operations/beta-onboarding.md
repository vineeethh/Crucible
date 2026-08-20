# Private beta: onboarding & offboarding

Status: Phase 10 · Owner: project owner
Related: [support-runbook.md](support-runbook.md) ·
[retention-policy.md](retention-policy.md) ·
[../legal/terms-of-service.md](../legal/terms-of-service.md)

The private beta is an **allowlist**: access is granted per organization, one
named cohort member at a time. There is no self-service signup.

## Onboard a tenant

```bash
uv run python scripts/onboard_beta_tenant.py \
  --slug acme --name "Acme Inc" --owner-email ops@acme.example --budget-usd 25
```

This creates, in one transaction:
- the organization (`status = active` — allowlisted);
- an owner user + membership;
- an **owner API key** (printed once — share over a secure channel);
- a **monthly budget** so spend is bounded from the first run.

Then send the cohort member:
1. their API key and the base URL;
2. the [product tour](product-tour.md) and API guide;
3. the [terms of service](../legal/terms-of-service.md) and
   [data-processing notice](../legal/data-processing-notice.md) to accept.

The documented flow they complete: **upload a dataset → run a question → inspect
the evidence → (optionally) compare an experiment → complete a review.**

## The beta acceptance checklist (DoD)

A cohort member has "completed the flow" when:
- [ ] they uploaded a dataset and it profiled to `ready`;
- [ ] they ran a question that reached a terminal state with provenance;
- [ ] they viewed the run's trace/config/attempts;
- [ ] they hit no unhandled error and no cross-tenant data;
- [ ] their feedback is captured (see [support-runbook.md](support-runbook.md)).

## Suspend / reactivate (allowlist control)

```bash
uv run python scripts/admin.py suspend  --slug acme   # blocks all access; data kept
uv run python scripts/admin.py activate --slug acme   # restores access
```

A suspended org is refused at the authentication boundary (both API keys and
OIDC), for every endpoint — the data is retained, access is not.

## Offboard / erasure

At the end of the engagement, or on request:

```bash
uv run python scripts/admin.py purge-org --slug acme            # dry run
uv run python scripts/admin.py purge-org --slug acme --apply    # irreversible
```

See [retention-policy.md](retention-policy.md) for exactly what is removed.

## Cost & limits per tenant

- Monthly budget: `scripts/admin.py set-budget --slug … --usd …` (admission
  refuses runs before spending once the budget is reached).
- Retention override: `scripts/admin.py set-retention --slug … --days …`.
