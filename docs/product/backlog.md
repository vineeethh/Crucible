# Crucible Six-Month Backlog v0.1.0

Status: Phase 0 baseline · Date: 2026-07-14 · Assumes ~25 focused h/week; totals include work only, +20% contingency applied at the bottom.
Critical path: **P0 → P1 → P2 → P3 → P4 → P5 → P6 → P9 → P10 → P11** (P7 and P8 hang off it).

| Phase | Window (target) | Hours | Exit milestone (Definition of Done) |
|---|---|---:|---|
| **P0 Charter + ADRs** ✅ this deliverable | 2026-07-14 → 07-20 | 16 | Reviewer can state workload, per-case oracle, exclusions, first gate; ADR-001..007; 10 verified seed cases |
| **P1 Repo foundation + local platform** | 07-20 → 08-03 | 32 | Fresh clone boots Compose stack; green CI (format/type/unit/migration/container-health); version endpoint reports Git SHA |
| **P2 Identity + dataset ingestion + data plane** | 08-03 → 08-17 | 40 | Upload → immutable version + profile → placeholder async run with durable events; cross-tenant access impossible by guessed ID |
| **P3 Isolated execution + safety canaries** | 08-17 → 08-31 | 48 | Fixed safe program reads only its dataset; all escape/egress/resource/secret canaries terminate safely; incident runbook exists |
| **P4 Durable data-agent MVP** | 08-31 → 09-21 | 64 | Real question → answer with provenance / truthful abstain / review; worker restart resumes; retry caps enforced; all nodes traced |
| **P5 Offline eval harness + regression evidence** | 09-21 → 10-12 | 72 | PR smoke suite catches a deliberately injected regression; per-case baseline/candidate report with CIs and config hashes is reproducible |
| **P6 Observability + online eval + human review** | 10-12 → 10-26 | 48 | Every terminal run shows trace/cost/versions/taxonomy; reviewer can score safely; judge has held-out agreement report; alert exercised |
| **P7 Product dashboard + docs polish** | 10-26 → 11-09 | 56 | Full user journey without internal tools; keyboard-accessible; no tenant leakage |
| **P8 Measured routing + exact cache** (parallel after P5) | 10-26 → 11-09 | 52 | Held-out quality–cost–latency report incl. retries; exact cache cannot cross tenant/dataset/config; semantic cache stays off |
| **P9 CI/CD, staging, load, security hardening** | 11-09 → 11-23 | 56 | OIDC protected staging deploy + rollback rehearsed; restore drill evidenced; scans enforced |
| **P10 Private beta + reliability operations** | 11-23 → 12-07 | 48 | Named beta cohort completes flow; on-call/support/rollback/retention documented and exercised; no open critical security issue |
| **P11 v1.0.0 release + open-source package** | 12-07 → 12-21 | 56 | Clean-clone reproducible demo + eval report; real CI regression gate visible; measured release claims with suite versions/dates |
| Subtotal | | **588** | |
| Contingency (20%): docs, bugs, provider churn | | 118 | |
| **Total** | | **~706** | ≈28 weeks at 25 h/week |

## Parallel workstreams (start early, off critical path)

| Workstream | Starts | Constraint |
|---|---|---|
| Eval case authoring + reference calculators | P0 (started — seed suite shipped) | Full integration waits for P4; grow toward 40–60 core cases |
| Documentation/ADRs | P0 | Updated with decisions, not written at release |
| Basic CI + security scanning | P1 | Gates expand as services exist |
| Frontend shell/design system | P1–P2 | No detailed dashboards before API/metric shapes stabilize |
| Observability conventions | P1 | Full instrumentation follows agent runtime |
| IaC research | P1 | Production apply waits for staging-capable system |
| Router/cache study | P5 | No policy optimization before outcome data |

## Cut line (8-week MVP, if forced)

P0–P5 + minimal tracing/CI from P6 + very small UI. **Never cut:** the sandbox
boundary, the deterministic eval harness, or regression evidence.

## Standing backlog rules

- One concern per PR; migrations, evaluator/baseline, security, and infra changes are
  called out explicitly.
- Conventional Commits; `main` always releasable; feature flags over long-lived branches.
- Every phase exit runs the phase checklist matrix in the master plan and updates the
  risk register.
