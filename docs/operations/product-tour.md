# Product tour (Phase 7)

Status: Phase 7 · Related: [web-frontend.md](../architecture/web-frontend.md) ·
[local-development.md](local-development.md)

A five-to-seven minute walkthrough of the whole user journey — **upload → run →
evidence → compare → review** — completable entirely in the UI, no internal tools.
This doubles as the acceptance script for the Phase 6 DoD.

## Setup (once)

```bash
docker compose up -d                     # postgres, redis, minio, api, worker
uv run alembic -c packages/db/alembic.ini upgrade head
uv run python scripts/seed_demo.py --slug demo   # prints an API key
# apps/web/.env.local:
#   CRUCIBLE_API_URL=http://localhost:8100
#   CRUCIBLE_API_KEY=ck_...   (from the seed output)
pnpm --filter web dev                    # http://localhost:3100
```

The seed creates a `sales` dataset and three finished runs (answered, waiting for
review, abstained) so every page has real content on first load.

## The journey

1. **Landing (`/`)** — confirms the API is reachable and lays out the five steps.
   Toggle light/dark in the header; the choice persists.

2. **Upload a dataset (`/datasets`)** — pick a `.csv`/`.parquet` file and a name.
   The bytes upload **directly to storage** (they never touch the API or the web
   server); the browser hashes them and the version is registered, then profiled
   in the background. Versions are immutable and content-addressed — re-uploading
   the same bytes reuses the version.

3. **Start a run (`/runs`)** — choose a *ready* version, ask a question
   (e.g. "What is the total amount by region?"), and start it. The agent plans,
   generates and runs code in the sandbox, verifies, and answers with provenance —
   or abstains truthfully, or routes to review.

4. **See the evidence (`/runs/[id]`)** — the answer and its provenance
   (operation, columns used, code hash, executor), the verification vector, the
   **redacted trace** (tenant pseudonym, model versions, span timeline — never a
   raw prompt or data), the config manifest, the node timeline, and per-step
   attempts. A non-terminal run can be cancelled here.

5. **Compare experiments (`/evaluations`)** — the versioned suites and the latest
   candidate-vs-baseline comparison with its gate decision, paired Δ and 95% CI.
   Export the report as **JSON** (the exact CI-gated bytes) or **Markdown** (the
   shareable form).

6. **Complete a review (`/reviews`)** — claim an ambiguous run (an exclusive
   optimistic lock — a second reviewer gets a clear conflict), grade it against
   the rubric (groundedness / provenance / usefulness / uncertainty, 0–2 each),
   and approve or reject. Grades are recorded as evidence, never a correctness
   gate; approve resumes the agent to synthesize, reject abstains.

7. **Check your authority (`/settings`)** — the org, actor, role, effective
   permissions, and the org's API keys. This mirrors the API's authorization
   exactly.

## Screenshots

Capture with the E2E harness once browsers are installed:

```bash
pnpm --filter web exec playwright install chromium
pnpm --filter web test:e2e            # runs the critical-flow specs
```

Recommended shots for a demo/README: the dashboard, a run detail with its trace,
the experiment comparison, and the review queue mid-grade.
