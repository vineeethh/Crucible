# Contributing to Crucible

## Quickstart

```bash
git clone <repo> && cd crucible
uv sync --dev            # Python workspace (uv installs Python 3.12 if needed)
uv run pre-commit install
pnpm install             # web workspace
docker compose up -d     # Postgres+pgvector, Redis, MinIO, OTel collector
uv run alembic -c packages/db/alembic.ini upgrade head
make check               # or: pwsh scripts/check.ps1
```

Run the API: `uv run uvicorn --factory crucible_api.main:create_app --reload`
Run the worker: `uv run arq crucible_worker.main.WorkerSettings`
Run the web shell: `pnpm dev` (http://localhost:3000)

## Branch and commit model (plan §19)

- `main` is always releasable and protected. No permanent development branch.
- Short-lived branches: `feat/<area>-<topic>`, `fix/`, `chore/`, `docs/`, `security/`.
- Conventional Commits: `feat(agent):`, `fix(eval):`, `test(security):`, `docs(adr):`.
- Feature flags shield incomplete paths — not long-lived branches.

## Pull request standard

One concern per PR. The description states: objective, design/ADR link, test
evidence, eval impact, security/data impact, rollout/rollback notes.

Every PR must answer the shared checklist (master plan §20):

- [ ] Names its affected tenant/data/security/evaluation boundary.
- [ ] Has unit/integration/e2e/eval coverage appropriate to risk.
- [ ] Does not log, trace, cache, or return sensitive data unintentionally.
- [ ] Documents API/schema/migration/config/flag/rollback implications.
- [ ] New model/prompt/router/evaluator policy is immutable + versioned.
- [ ] Error, cancellation, timeout, retry, degraded paths considered.
- [ ] UI changes accessible, responsive, authorized server-side.
- [ ] Docs/ADR/runbook/changelog updates included.

AI-generated changes follow the same review standard — no exemptions.

## Hard rules

- Migration, evaluator/baseline, security, and infra changes are called out
  explicitly and owned via CODEOWNERS.
- Eval fixtures are synthetic only; released cases/suites are immutable
  (new versions, never edits) — see `evals/README.md`.
- `packages/domain` imports nothing but stdlib; `packages/application` imports
  only domain. `uv run lint-imports` enforces this and CI blocks violations.
- No business code reads environment variables directly — typed settings only.
