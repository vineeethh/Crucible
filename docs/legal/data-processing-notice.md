# Data-Processing & Privacy Notice — Private Beta (DRAFT)

Status: Phase 10 · **DRAFT — not legal advice; review by counsel before use.**
Related: [terms-of-service.md](terms-of-service.md) ·
[../operations/retention-policy.md](../operations/retention-policy.md) ·
[../security/threat-model.md](../security/threat-model.md)

> Plain-language draft describing what data Crucible processes, why, where it
> goes, and what it never does. It is deliberately narrow. Have counsel review
> before relying on it.

## What we process

| Data | Purpose | Notes |
|---|---|---|
| Account data (org, owner email, API keys) | Authenticate and authorize you | Minimal; no marketing use |
| Datasets you upload | Run the analyses you request | Content-addressed, immutable versions |
| Questions (prompts) | Produce answers | **Never** sent to traces or third parties in raw form |
| Run evidence (traces, attempts, verification) | Debugging, reliability, provenance | Redacted; carries a tenant *pseudonym*, not your identity |
| Audit events | Security and accountability | Retained as compliance evidence |

## Where it goes (and where it never goes)

- **Model providers.** If a run uses a hosted model, only the minimal derived
  input needed for the analysis is sent, after redaction; raw secrets and PII
  are stripped. (The default/offline configuration uses a local model and sends
  nothing externally.)
- **Telemetry/observability.** Only redacted, hashed, bounded data crosses this
  boundary — a salted tenant pseudonym, content hashes, and short excerpts.
  **Never** raw prompts or dataset contents (threat model T8).
- **Between tenants.** Never. Every read is organization-scoped; the exact cache
  and traces cannot cross a tenant, dataset, or configuration boundary.

## What we do not do

- We do **not** train models on your data.
- We do **not** sell or share your data with third parties for their own use.
- We do **not** retain raw prompts/data in logs or traces.

## Retention & your rights

- Operational data is minimized and deleted on a schedule
  ([retention policy](../operations/retention-policy.md)).
- You may request **export** or **deletion** of your organization's data; we
  execute deletion via an audited, dry-run-first procedure and confirm what was
  removed.
- Suspension retains your data but blocks access; erasure removes it.

## Security

Access is least-privilege and default-deny; generated code is sandboxed; the
delivery pipeline uses short-lived, federated credentials. See the
[threat model](../security/threat-model.md) and [SECURITY.md](../../SECURITY.md).

## Incident notification

If your data may have been exposed, we treat it as a top-severity incident
([incident response](../operations/incident-response.md)) and will notify
affected tenants promptly with what we know and what we are doing.

## Contact

Data requests and questions: the support route in
[beta onboarding](../operations/beta-onboarding.md). Security reports:
[SECURITY.md](../../SECURITY.md).
