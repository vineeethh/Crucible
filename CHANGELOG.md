# Changelog

All notable changes to Crucible. Dates are the phase-completion dates.
Format follows [Keep a Changelog](https://keepachangelog.com/) and the project
follows [Semantic Versioning](https://semver.org/) from v1.0.0 onward.

## [1.0.0] — 2026-08-06

First tagged release. Packages Phases 0–10 into a reproducible, honestly-scoped
v1 under the **Apache-2.0** license. See the
[v1.0.0 release report](docs/release/v1.0.0.md) for the measured evidence.

### Added
- **License & governance.** Apache-2.0 `LICENSE` + `NOTICE`; `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1); GitHub issue templates and a pull-request template
  mirroring the shared code-review checklist.
- **Release documentation.** [v1.0.0 release report](docs/release/v1.0.0.md)
  (measured results only), a README documentation index, an explicit
  **Non-goals & limitations** section, and a top-level local quickstart +
  reproduction guide.
- **Maintenance cadence.** [docs/operations/maintenance-cadence.md](docs/operations/maintenance-cadence.md)
  — issue triage, dependency/security update cadence, and release process.

### Changed
- Web app degrades gracefully on a stale/missing API key or unreachable API
  (friendly setup state instead of a crash) and adds a route error boundary;
  `<body suppressHydrationWarning>` silences browser-extension hydration noise.
- Workspace version set to `1.0.0`; README reframed from "Phase 10 complete" to
  the v1.0.0 release.

### Security
- Dependency CVE fixes carried in: `cryptography` → 50, `next` → 15.5.22,
  `postcss`/`sharp`/`js-yaml` pinned to fixed versions.

## [Phase 10] — Private beta deployment & reliability operations — 2026-07-21

### Added
- **Beta allowlist / org lifecycle.** Organizations carry a `status`
  (`active`/`suspended`); a suspended org is refused at the authentication
  boundary for both API keys and OIDC. (migration 0006)
- **Data retention.** A daily worker job deletes terminal runs and their
  evidence (and old cache entries) past a window (platform default 90 days,
  per-tenant override via `retention_days`); audit events and datasets are out
  of scope. Dry-run supported.
- **Right-to-erasure.** `purge-org` removes all of a tenant's data and the org
  itself, dry-run first.
- **Operator tooling.** `scripts/admin.py` (list/suspend/activate/set-budget/
  set-retention/retention/purge-org), `scripts/onboard_beta_tenant.py`,
  `scripts/weekly_review.py` (reliability + eval review artifact), and
  `scripts/prod_canary.py` (synthetic production canary).
- **Public edge IaC.** Cloud Armor WAF (rate limiting, OWASP SQLi/XSS/LFI,
  Log4Shell) + global HTTPS load balancer + Google-managed TLS in front of the
  API, with HTTP→HTTPS redirect.
- **Beta ops & legal docs.** Retention policy, beta onboarding, support/
  incident-response/on-call runbooks, and draft Terms of Service + Data-
  Processing Notice.

### Changed
- Cloud SQL hardened: TLS-only, connection/checkpoint/lock/hostname/statement
  logging and pgAudit; deployer `serviceAccountUser` scoped per runtime SA
  (not project-wide); explicit default-deny firewall. IaC passes `tofu validate`
  and Checkov (0 failed).

## Phase 9 — Production CI/CD, staging, load & hardening — 2026-07-20
Federated (OIDC/WIF) keyless deploys; digest-pinned, cosign-signed images with
SBOM; staging deploy + production promotion + rollback workflows; OpenTofu GCP
reference IaC; layered security scanning (CodeQL/Semgrep/Trivy/gitleaks/zizmor);
load/soak harness; provider-outage, queue-loss, and crash-recovery game days; a
non-destructive DR drill with committed evidence.

## Phase 8 — Measured routing, exact cache & budgets — 2026-07-19
Declared two-tier router (identical accuracy at 63% lower cost on the held-out
experiment); exact cache that cannot cross tenant/dataset/config; per-tenant
budget ledger that refuses runs before spending.

## Phase 7 — Product dashboard, review UX & docs — 2026-07-18
Design system (`packages/ui`); the full journey (upload → run → evidence →
compare → review) completable in the UI; report export; demo seeding.

## Phase 6 — Observability, online eval & human review — 2026-07-18
Single redaction boundary for all exported telemetry (threat T8); reliability/
cost/latency/trace-completeness metrics; SLO alerts; human review queue;
calibrated, secondary LLM judge.

## Phases 0–5
Platform bootstrap; identity & data plane; isolated execution sandbox with
containment canaries; durable data-agent; offline evaluation harness with a
paired-bootstrap regression gate. See git history and per-phase commits.
