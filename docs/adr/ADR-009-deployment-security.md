# ADR-009: Federated, digest-pinned, reversible deployment

Status: Accepted · Date: 2026-07-20

## Context
Phase 9 makes deployment repeatable before real users arrive. The delivery
pipeline is itself an attack surface (threat T9): the failure modes to design
against are long-lived cloud credentials, tampered CI actions, untrusted PR
execution, and destructive migration rollbacks. We also need deploys to be
*reversible fast* without risking data.

## Decision
1. **Federated, short-lived credentials.** GitHub Actions authenticates to GCP
   via OIDC / Workload Identity Federation. No static service-account key
   exists. The deployer SA is least-privilege and scoped to this repo on `main`;
   the API and worker run as separate, disjoint runtime SAs.
2. **Immutable, signed, digest-pinned artifacts.** Images are built
   reproducibly from `uv.lock`, referenced by `@sha256:…`, cosign-signed
   (keyless) with a CycloneDX SBOM. Production promotion deploys the exact
   digest that passed staging and verifies its signature first — never a
   rebuild.
3. **Protected, non-fork workflows.** Credential-bearing workflows run only on
   `push`/`workflow_dispatch` behind protected GitHub environments (required
   reviewers); never `pull_request`/`pull_request_target`. All third-party
   actions are pinned to commit SHAs; `zizmor` gates workflow security.
4. **Expand/contract migrations + traffic-shift rollback.** Schema changes are
   backward-compatible across two serving revisions; a rollback is a traffic
   shift to the prior (schema-compatible) revision, so a *code* rollback never
   needs a *data* rollback. Data recovery is a restore (PITR / logical backup),
   proven by a non-destructive DR drill.

## Alternatives considered
- **Long-lived SA keys in GitHub secrets** — rejected: a leaked key is standing
  production access; OIDC removes the secret entirely.
- **Deploy by tag** — rejected: mutable tags make rollback non-deterministic and
  break "what was tested is what ships."
- **Migrate on app startup** — rejected (also forbidden by a semgrep rule):
  couples schema changes to rollout, defeats expand/contract, and races across
  replicas.
- **Blue/green with DB downgrade on rollback** — rejected: schema downgrades are
  destructive and rarely tested; expand/contract makes them unnecessary.

## Consequences
- Deploys require the one-time bootstrap of a state bucket, WIF pool, and
  protected environments (admin, not CI). Documented in
  `infra/opentofu/README.md` and the deployment runbook.
- A contract (destructive) migration is always a separate, later deploy than its
  expand — never bundled — which is a deliberate process constraint.
- Portability is preserved at the adapter layer (ADR-007); the pipeline is
  GCP-specific by choice, reversible at the interface seam.

## Revisit trigger
A move off GCP, a hosting requirement from a real adopter, or a supply-chain
standard (e.g., SLSA level) that requires a stronger provenance chain.
