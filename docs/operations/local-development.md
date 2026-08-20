# Local Development Guide

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| uv | ≥ 0.9 | Manages Python itself (downloads CPython 3.12 per `.python-version`) |
| Node.js | 22 LTS | Web workspace |
| pnpm | 10 | `npm i -g pnpm` or corepack |
| Docker | any recent | Compose v2 for the local stack |
| make (optional) | any | Windows: use `scripts/check.ps1` instead |

## First run

```bash
uv sync --dev                # creates .venv from uv.lock (reproducible)
uv run pre-commit install
pnpm install
cp .env.example .env         # local defaults; never put real secrets here
docker compose up -d         # postgres, redis, minio, otel-collector, api, worker
uv run alembic -c packages/db/alembic.ini upgrade head

# There is no self-service signup. Create the first org and API key:
uv run python scripts/bootstrap_org.py --slug demo --name "Demo Org"
# -> prints the token ONCE. Put it in apps/web/.env.local as CRUCIBLE_API_KEY
#    if you want the dashboard to show data.
```

## The one command (Phase 1 Definition of Done)

```bash
make check                   # or: pwsh scripts/check.ps1
```

Runs: format check → lint → mypy (strict) → import-boundary contracts →
unit tests → migration offline-SQL check → seed-suite reference calculators.

## Everyday commands

| Task | Command |
|---|---|
| API with reload | `uv run uvicorn --factory crucible_api.main:create_app --reload` |
| Worker | `uv run arq crucible_worker.main.WorkerSettings` |
| Web app | `pnpm --filter web dev` → http://localhost:3100 |
| Seed demo data | `uv run python scripts/seed_demo.py --slug demo` |
| Web typecheck / build | `pnpm --filter web typecheck` · `pnpm --filter web build` |
| OpenAPI docs | http://localhost:8000/docs |
| Unit tests | `uv run pytest -m "not integration"` |
| Integration tests | `docker compose up -d` then `uv run pytest -m integration` |
| New migration | `uv run alembic -c packages/db/alembic.ini revision -m "..."` |
| Full containerized stack | `docker compose up -d --build` (add `--profile full` for web) |
| MinIO console | http://localhost:9001 (crucible / crucible-local-only) |
| Build the sandbox runner | `make sandbox-image` |
| Run sandbox canaries | `make sandbox` (needs Docker + the runner image) |

### The web app (Phase 7)

The product UI (`apps/web`) is a Next.js App Router app over the public API plus
a design system (`packages/ui`, transpiled from source — no build step). It
authenticates with a server-side, org-scoped API key (`CRUCIBLE_API_KEY` in
`apps/web/.env.local`); the key never reaches the browser. `pnpm install` links
the workspace, then `scripts/seed_demo.py` populates a demo org so every page has
content. Full walkthrough: [product-tour.md](product-tour.md); architecture:
[web-frontend.md](../architecture/web-frontend.md). Critical-flow E2E tests live
in `apps/web/e2e` (Playwright; `pnpm --filter web test:e2e`, browsers installed
via `playwright install`).

### The execution sandbox (Phase 3)

Model-generated code runs in a hardened, deny-by-default container (ADR-003,
[docs/security/sandbox.md](../security/sandbox.md)). Backends are selected by
`EXECUTOR_BACKEND`: `fake` (default; never executes code), `docker` (local dev),
`microvm` (staging/prod). The compose worker uses `fake` on purpose — it has no
Docker socket, and giving it one would break the trust boundary. The Docker
backend is exercised from the host by the canary suite (`pytest -m sandbox`),
which is skipped automatically when Docker or the runner image is unavailable.

## Conventions that bite if missed

- Migrations run as an explicit step; the API never migrates on startup.
- `packages/domain` and `packages/application` must stay framework-free —
  `uv run lint-imports` fails the build otherwise.
- Settings: only `crucible_api/settings.py` and `crucible_worker/settings.py`
  read the environment. Staging/production profiles refuse localhost URLs,
  wildcard CORS, and unknown git SHAs at startup — by design.
- The `/version` endpoint reports the build's git SHA: injected via `GIT_SHA`
  in CI/images, `git rev-parse` fallback in local dev.
