# Terms of Service — Private Beta (DRAFT)

Status: Phase 10 · **DRAFT — not legal advice; review by counsel before use.**
Applies to: the private-beta, allowlisted use of Crucible.

> This is a plain-language draft written by engineering to set honest
> expectations with a bounded beta cohort. It is intentionally conservative. It
> is **not** a substitute for review by a qualified lawyer.

## 1. Scope

These terms govern access to the Crucible private beta by an allowlisted
organization ("you"). Access is granted per organization and may be suspended or
revoked at any time.

## 2. Beta nature; no warranty

The service is provided **as-is**, for evaluation, with **no uptime, support, or
fitness guarantee**. Features may change or be removed. Do not rely on it for
production or business-critical workloads.

## 3. Acceptable use

You will not: upload data you lack the right to process; attempt to access other
tenants' data; probe or attack the platform outside a coordinated disclosure
(see [SECURITY.md](../../SECURITY.md)); or use the service to violate law.
Generated code runs only inside the platform's sandbox; you will not attempt to
escape or abuse it.

## 4. Your data

- You retain ownership of the datasets you upload and the answers produced.
- We process your data only to operate the service for you (see the
  [Data-Processing Notice](data-processing-notice.md)).
- We do **not** use your data to train models, and we do not sell it.
- Prompts and dataset contents are never placed in traces or third-party
  telemetry (they are redacted / pseudonymized).

## 5. Retention & deletion

Operational data is retained per the [Retention Policy](../operations/retention-policy.md)
(terminal runs and evidence ~90 days; datasets until you delete them; audit
records longer). You may request deletion of your organization's data at any
time; we will honour it (see the retention policy for exactly what is removed).

## 6. Cost & limits

Beta usage is subject to per-tenant budgets and rate limits. Runs are refused
once your monthly budget is reached.

## 7. Feedback

Feedback you provide may be used to improve the service. Quality claims are
validated by our evaluation gate, not by anecdote.

## 8. Confidentiality

The beta, its non-public features, and any performance figures shared with you
are confidential until publicly released.

## 9. Termination

Either party may end participation at any time. On termination we suspend access
and, on request, erase your organization's data.

## 10. Liability

To the maximum extent permitted by law, and given the no-fee beta nature, our
liability is limited; the service carries no warranty (section 2).

---

Questions: the support route in [beta onboarding](../operations/beta-onboarding.md).
Security issues: [SECURITY.md](../../SECURITY.md).
