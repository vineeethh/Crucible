# Crucible

**An open-source evaluation and reliability platform for LLM agents**, with a
self-correcting data-analysis agent as its bounded reference workload.

> A language-model agent should be trusted only to the degree that its behavior is
> **measured, reproducible, observable, bounded, and independently checked.**

Crucible's differentiator is not the agent loop — it is the evidence around the loop:
executable offline evaluation, versioned experiment comparisons, production tracing,
constrained execution, regression gates, and a stable failure taxonomy.

## Status: v1.0.0

Crucible **v1.0.0** is the first tagged release. Phases 0–10 of the
implementation plan are complete, and this release packages them honestly:
measured claims only, fully synthetic fixtures, and a reproducible local demo.
The evidence behind every claim below lives in the
**[v1.0.0 release report](docs/release/v1.0.0.md)** and the
**[CHANGELOG](CHANGELOG.md)**.

**What v1 is:** a multi-tenant, API-first platform that evaluates and operates
*one* bounded workload — a data-analysis agent answering questions over uploaded
CSV/Parquet datasets with constrained Python execution. The differentiator is
the evidence around the loop (deterministic evaluation, regression gates,
tracing, sandboxing, provenance, failure taxonomy), not the loop itself.

**What v1 is *not*:** see [Non-goals & limitations](#non-goals--limitations) —
several capabilities are deliberately out of scope, and some parts are a
reference/adapter contract rather than a hosted service. It is not represented
as a certified or production-hardened multi-customer SaaS.

<details><summary><b>v1.0.0 highlights — Phase 10: private beta ops &amp; reliability</b></summary>

- **Beta allowlist.** Access is per-organization: a `suspended` org is refused at
  the authentication boundary (API keys and OIDC alike). No self-service signup;
  `scripts/onboard_beta_tenant.py` brings a named cohort member on with an owner
  key and a budget in one command.
- **Data minimization, executed.** A daily job deletes terminal runs and their
  evidence past a retention window (per-tenant override); non-terminal runs are
  never reaped; audit and datasets are scoped out. Right-to-erasure
  (`purge-org`) removes a tenant's data and the org, dry-run first.
- **A public edge.** Cloud Armor WAF (rate limiting + OWASP + Log4Shell) and a
  global HTTPS load balancer with managed TLS front the API. The whole IaC
  passes `tofu validate` and Checkov with **zero failures**.
- **Operator surface.** An admin CLI (suspend/activate, budgets, retention,
  erasure), a synthetic production canary, and a weekly reliability + evaluation
  review that keeps "it seemed fine" from being mistaken for measured quality.
- **Beta discipline, documented.** Onboarding, support, incident-response, and
  on-call runbooks; a retention policy; and draft terms + data-processing notice.
  See [beta onboarding](docs/operations/beta-onboarding.md).

</details>

<details><summary>Earlier: Phase 9 — production CI/CD, staging, load & hardening</summary>

Federated (OIDC/WIF) keyless deploys; digest-pinned, cosign-signed images with
SBOM; staging deploy + production promotion + rollback; OpenTofu GCP reference
IaC; layered security scanning; load/soak harness; provider-outage, queue-loss,
and crash-recovery game days; a non-destructive DR drill with committed
evidence. ([ADR-009](docs/adr/ADR-009-deployment-security.md),
[deployment runbook](docs/operations/deployment-runbook.md))

</details>

<details><summary>Earlier: Phase 8 — measured routing, exact cache, budgets</summary>

Every efficiency lever is declared, evidence-gated, and reversible with one
setting: a two-tier router (identical accuracy at 63% less cost on the held-out
experiment), an exact cache that cannot cross tenant/dataset/config, and a
budget ledger that refuses runs before spending. See
[docs/operations/efficiency.md](docs/operations/efficiency.md).

</details>

## Quickstart (local, synthetic data only)

Prerequisites: Docker, [`uv`](https://docs.astral.sh/uv/), Node 20+ with
[`pnpm`](https://pnpm.io/). A fresh clone to a running demo:

```bash
git clone https://github.com/saiabhinav001/crucible.git && cd crucible
uv sync --dev                                              # Python 3.12 workspace
pnpm install                                               # web workspace
docker compose up -d postgres redis minio                  # local infra
uv run alembic -c packages/db/alembic.ini upgrade head     # schema
make sandbox-image                                         # build the hardened runner
uv run python scripts/seed_demo.py --slug demo             # synthetic org + runs; prints an API key
uv run uvicorn --factory crucible_api.main:create_app --port 8100   # API
```

Then point the web app at it and open the dashboard:

```bash
printf 'CRUCIBLE_API_URL=http://localhost:8100\nCRUCIBLE_API_KEY=<key from seed_demo>\n' > apps/web/.env.local
pnpm --filter web dev            # http://localhost:3100
```

> On Windows, run the API in Docker (`docker compose up -d api`) — a bare
> `uvicorn` there hits a known async-Postgres event-loop quirk. Everything else
> is cross-platform. Full guide: [docs/operations/local-development.md](docs/operations/local-development.md).

**The demo story** — `upload → run → evidence → compare → review`: upload a
synthetic CSV, ask a question, watch the agent plan → generate code → execute it
in the sandbox → verify → answer *with provenance* (or abstain truthfully);
open the run to see the redacted trace and config manifest; compare a candidate
config against the frozen baseline; and claim/grade a review. See the
[product tour](docs/operations/product-tour.md).

**Reproduce the evaluation evidence** — no cloud model or API key required (the
default `fake` backend runs real generated code in the sandbox):

```bash
make sandbox-image
make eval-run                    # scores the core suite vs the frozen baseline and applies the gate
```

The committed example reports are in
[`evals/reports/examples/`](evals/reports/examples/) — the exact CI-gated bytes.

## Verify it yourself (the gates)

```bash
make check                       # ruff · mypy (strict) · import-linter · unit + integration tests
uv run pytest -m sandbox         # agent computes real answers in the hardened sandbox
make eval-run                    # regression gate: candidate vs frozen baseline, paired bootstrap CI
```

<details><summary>Earlier: Phase 7 — product dashboard, review UX, and docs</summary>

The whole user journey — upload → run → evidence → compare → review — is
completable in the UI, with no internal tools.

- **A real design system** (`packages/ui`): theme-aware tokens (light/dark), and
  reusable `StatusBadge` / `DataTable` / `Trace` / `ConfigView` / `MetricCard`
  components, shipped as source and transpiled into the app.
- **The full journey in the browser.** Upload straight to storage (bytes never
  touch the API or the web server), start runs, inspect the redacted trace and
  provenance behind every answer, compare a candidate against the baseline, and
  claim → grade → resolve a review — each an authenticated, tenant-scoped action.
- **The credential is the session.** The web app authenticates with a
  server-side, org-scoped API key that never reaches the browser; the UI mirrors
  the API's authorization (see `/settings`) rather than inventing its own, so it
  cannot leak another tenant's data.
- **Accessible and responsive.** Semantic landmarks, a skip link, keyboard-first
  controls with visible focus, status never by colour alone, fluid layouts, and
  tables that scroll inside their panel — light and dark.
- **Report export + demo seeding.** Download a comparison as JSON (the exact
  CI-gated bytes) or Markdown; `scripts/seed_demo.py` populates a demo org so the
  dashboard has real content in one command.

See the [product tour](docs/operations/product-tour.md) and the
[web architecture](docs/architecture/web-frontend.md).

```bash
uv run python scripts/seed_demo.py --slug demo   # populate a demo org
pnpm --filter web dev                            # http://localhost:3100
```

</details>

<details><summary>Earlier: Phase 6 — observability, online eval, and human review</summary>

Every terminal run shows a redacted trace, cost, latency, versions, and a failure
taxonomy; a reviewer can safely score a run; the judge is calibrated against
held-out human labels and confined to secondary criteria; reliability alerts are
exercised. One redaction boundary (`crucible.observability.redaction`) gates
everything that leaves the trust boundary (threat T8); trace completeness is the
DoD metric. See [docs/operations/observability.md](docs/operations/observability.md).

</details>

<details><summary>Earlier: Phase 5 — offline evaluation harness + regression gate</summary>

Phase 5 is an executable regression gate. It runs the real agent over versioned
cases, scores against trusted oracles, and compares a candidate to a frozen
baseline with a paired bootstrap confidence interval.

- **Versioned suites, verified gold.** Every gold answer in the core suite is
  cross-checked against an independent, executable reference calculator; fixtures
  are pinned by SHA-256; released cases are immutable (the baseline pins the
  suite hash, so an edit fails the lineage test).
- **Scorer hierarchy, kept separate.** Tier 1 correctness (exact / numeric-
  tolerance / result-set / behavioral-abstention) is the gate; Tier 3 policy
  checks are hard gates. They never blend — a wrong answer is never rescued by a
  clean policy check, and code running is never mistaken for a correct answer.
- **Paired comparison + gate.** The gate BLOCKs a material regression (upper CI
  bound below tolerance) or any policy failure, FLAGs an inconclusive regression
  for review, and never calls a change an improvement when the interval spans
  zero. The bootstrap uses a fixed seed, so the interval is reproducible.
- **It catches real regressions.** Building it surfaced two genuine agent bugs
  (fixed); a deliberately injected regression is blocked end-to-end through the
  real sandbox.

```bash
make sandbox-image                          # build the runner
make eval-run                               # score the core suite vs the frozen baseline, gate
```

</details>

<details><summary>Earlier: Phase 4 — durable data-agent MVP</summary>

The agent plans an analysis, generates code, runs it in the Phase 3 sandbox,
verifies, and either answers with provenance, abstains truthfully, or routes to
human review.

- **Explicit durable graph** (ADR-008): validate → profile → plan → code →
  execute → observe → repair (bounded, max 2) → verify → synthesize. It
  checkpoints after every node, so a worker restart resumes from where it left
  off rather than re-running model calls and sandbox executions.
- **Provider-neutral model gateway**: a deterministic `fake` backend (template
  planner/coder — offline, no cloud LLM) and an OpenAI-compatible contract. The
  fake produces *real, correct* answers because the generated code runs for real
  in the sandbox.
- **Honest terminal states**: `answered` (with provenance pointing at the
  computed result), `abstained` (unsupported question, or a failure that repair
  can't fix), `waiting_review` (an ambiguous result, e.g. a tie), `cancelled`.
  The answer text is synthesized mechanically from the verified result, so it
  can never claim more than the number.
- **Proven end to end**: the agent computes real sums, distinct counts, and
  group-maxima through the actual Docker sandbox; the durable resume, bounded
  repair, oscillation guard, and review flow are all tested.

```bash
make sandbox-image                    # build the runner
uv run pytest -m sandbox              # agent computes real answers in the sandbox
```

</details>

<details><summary>Earlier: Phase 3 — isolated execution boundary + safety canaries</summary>

The highest-risk phase, deliberately built before any agent existed to run code
through it.

- **Fixed protocol, no model-controlled config.** The execution request carries
  only a program and one dataset; it has no field for an image, mount, network
  flag, capability, package, or environment variable.
- **Hardened runner (local dev):** non-root, all Linux capabilities dropped,
  no-new-privileges, read-only root, network disabled (no egress/DNS/metadata),
  no Docker socket, memory/CPU/pids/wall-clock/file-size/output caps, fresh
  container per attempt, force-destroyed.
- **Backends** (ADR-003): `FakeExecutor` (tests, never runs code), `DockerExecutor`
  (dev), `MicroVMExecutor` (staging/prod, deny-by-default with no weaker fallback).
- **20 containment canaries** run real hostile programs against the real runner
  and prove each control holds — network exfiltration, host escape, privilege
  escalation, memory/CPU/fork/output bombs, malicious artifacts, and secret
  disclosure are all contained. See [docs/security/sandbox.md](docs/security/sandbox.md).

```bash
make sandbox-image && make sandbox      # build the runner and run the canaries
```

</details>

Earlier phases (identity, dataset ingestion, durable runs) below.

```bash
uv sync --dev && docker compose up -d                       # full local stack
uv run alembic -c packages/db/alembic.ini upgrade head
uv run python scripts/bootstrap_org.py --slug demo          # prints an API key once
pwsh scripts/check.ps1                                      # or: make check
```

- **Identity:** OIDC JWT *or* Argon2id-hashed API keys; five roles, default-deny RBAC
  checked inside every use case. A key can never exceed its creator's permissions.
- **Datasets:** presigned direct-to-storage uploads (file bytes never touch the API),
  immutable **content-addressed** versions, worker-side parsing/profiling with hash
  verification. Identical bytes reuse the existing version.
- **Runs:** durable async jobs with a guarded state machine, append-only event history,
  SSE streaming, `Idempotency-Key` support, and real cancellation.
- **Evidence:** append-only audit log, including denials — written in their own
  transaction so they survive the rolled-back request that produced them.
- **Tests:** 180 passing, including a 20-case tenant-isolation suite proving a second
  organization cannot reach anything by guessed ID.

The agent itself is deliberately absent until Phase 4: a run today is accepted,
claimed, and terminated as `abstained` with an explicit reason rather than
fabricating an answer.

See the [API guide](docs/operations/api-guide.md) and
[local development guide](docs/operations/local-development.md).

| Artifact | Location |
|---|---|
| Product charter (workload, non-goals, first release gate) | [docs/product/prd.md](docs/product/prd.md) |
| Metric contract (scorer hierarchy, gates vs trends, δ policy) | [docs/evaluation/metric-contract.md](docs/evaluation/metric-contract.md) |
| Failure taxonomy | [docs/evaluation/failure-taxonomy.md](docs/evaluation/failure-taxonomy.md) |
| Threat model (boundary × control × test matrix) | [docs/security/threat-model.md](docs/security/threat-model.md) |
| C4 context + plane separation | [docs/architecture/c4-context.md](docs/architecture/c4-context.md) |
| ADR-001 … ADR-007 | [docs/adr/](docs/adr/) |
| Risk register | [docs/product/risk-register.md](docs/product/risk-register.md) |
| Six-month backlog | [docs/product/backlog.md](docs/product/backlog.md) |
| **10-case hand-verified seed suite** | [evals/](evals/README.md) |

## Try the seed suite now

```bash
python evals/references/run_all.py
```

Ten reference calculators (pure stdlib, no dependencies) compute golden answers over a
fully synthetic 40-row retail fixture, including deliberate edge cases: missing
discounts, an unknown region, tie-margin checks, and an unanswerable question whose
correct outcome is abstention. High-value cases carry an independently written second
calculation. Every case pins the fixture's SHA-256 and its canonicalization contract.

## Non-goals & limitations

v1 is scoped on purpose. The following are **explicitly out of scope**, and
saying so is part of the design — not an omission:

- **No generic/autonomous agent.** One bounded workload (tabular data analysis).
  No web browsing, email, SaaS connectors, or acting on a user's behalf.
- **No arbitrary execution.** Generated code cannot install packages, open the
  network, choose its image/mounts, or get a shell. GPU execution and
  user-provided container images are out of scope.
- **No multi-agent delegation** or cross-user/long-term conversational memory.
- **No compliance certification.** Crucible adopts useful controls and evidences
  them, but makes **no** SOC 2 / HIPAA / GDPR *certification* claim (see
  [SECURITY.md](SECURITY.md)).
- **No universal agent benchmark.** One rigorous reference workload plus a
  generic harness seam; broader workload adapters are post-v1.

Honest limitations of *this* release:

- The **production microVM sandbox** and **GCP deployment** are a provider
  adapter + reviewed OpenTofu reference (validated with `tofu validate` /
  Checkov), not a live hosted service. Local execution uses the hardened
  **Docker** runner; production isolation requires wiring a microVM provider.
- The default model backend is a deterministic **`fake`** (it runs *real*
  generated code in the sandbox, so answers are genuinely computed). A real
  model requires configuring the OpenAI-compatible gateway; its quality is not
  claimed without eval evidence.
- Numbers quoted anywhere (e.g. the routing cost delta) are from the committed
  **synthetic** eval reports on a small suite, with their sample size and date —
  they are illustrative of the method, not production benchmarks.

Roadmap (clearly *not* shipped in v1): [docs/product/backlog.md](docs/product/backlog.md).

## Non-negotiable principles

1. Correctness is not a vibe — executable ground truth first.
2. The serving plane and evaluation plane are different products.
3. No model certifies itself.
4. Generated code is hostile until contained.
5. Version every behavior-changing input.
6. Do not overbuild before the scorecard works.

## Documentation index

| Area | Start here |
|---|---|
| Release evidence | [v1.0.0 release report](docs/release/v1.0.0.md) · [CHANGELOG](CHANGELOG.md) |
| Architecture | [C4 context + planes](docs/architecture/c4-context.md) · [web frontend](docs/architecture/web-frontend.md) · [ADRs](docs/adr/) |
| Evaluation | [metric contract](docs/evaluation/metric-contract.md) · [failure taxonomy](docs/evaluation/failure-taxonomy.md) · [seed suite](evals/README.md) |
| Security | [SECURITY.md](SECURITY.md) · [threat model](docs/security/threat-model.md) · [sandbox](docs/security/sandbox.md) |
| Operations | [local dev](docs/operations/local-development.md) · [API guide](docs/operations/api-guide.md) · [deployment](docs/operations/deployment-runbook.md) · [runbooks](docs/operations/) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) · [maintenance cadence](docs/operations/maintenance-cadence.md) |
| Product | [PRD](docs/product/prd.md) · [roadmap/backlog](docs/product/backlog.md) · [risk register](docs/product/risk-register.md) |

## License & security

Licensed under the **Apache License 2.0** — see [LICENSE](LICENSE) and
[NOTICE](NOTICE). Contributions are accepted under the same license (Apache-2.0
§5); see [CONTRIBUTING.md](CONTRIBUTING.md).

Report vulnerabilities privately per [SECURITY.md](SECURITY.md) — never in a
public issue. All fixture and demo data in this repository is **synthetic**; no
real persons, prices, or transactions.
