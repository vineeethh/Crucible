# Runbook: Game days (resilience drills)

Status: Phase 9 · Owner: on-call / project owner
Related: [disaster-recovery.md](disaster-recovery.md) ·
[sandbox-incident-runbook.md](sandbox-incident-runbook.md) ·
[alert-runbook.md](alert-runbook.md)

Game days inject a realistic failure and confirm the system degrades the way the
design promises. Ours are **executable**: they run against the live stack and
assert the outcome, so a regression in resilience fails CI, not production.

Run them all: `uv run pytest -m load` (needs the compose stack). Source:
`tests/integration/test_resilience_gameday.py`.

## Game day 1 — provider outage

**Inject:** the sandbox executor is unreachable (`ExecutorUnavailable`) while a
run is in flight.

**Expected (and asserted):**
- The job **raises** (so the queue retries) — the fault is never swallowed.
- The run stays `running`; **no terminal event**, and **`failure_category` stays
  NULL**. An infrastructure outage is *operational*, never attributed to the
  model (that distinction is the whole point of the sandbox error types).
- When the provider recovers, the retried job **resumes from the checkpoint** and
  answers — exactly one terminal event.

**Real incident:** follow [sandbox-incident-runbook.md](sandbox-incident-runbook.md).
Contain by setting `EXECUTOR_BACKEND=fake` (runs abstain safely) or scaling the
worker to zero; runs already in flight are preserved by the checkpoint.

## Game day 2 — queue loss

**Inject:** Redis drops every enqueued job (a wipe/failover).

**Expected (and asserted):**
- The runs are still `queued` in Postgres — the source of truth (ADR-002/004).
- A recovery sweep re-drives every non-terminal run; each terminates **exactly
  once**.
- A late, duplicate delivery of an already-recovered job is a **no-op**
  (`already_terminal`) — at-least-once delivery + idempotent compare-and-set
  transitions.

**Real incident:** restore Redis (Memorystore failover / re-provision), then run
the reconcile sweep (re-enqueue non-terminal runs). No data restore is needed.

## Game day 3 — worker crash mid-run

**Inject:** the worker dies mid-execute (the job raises after claiming).

**Expected (and asserted):** the run is left `running` with a checkpoint; a
**fresh** worker picks it up and finishes it — no run is orphaned by a crash,
and it terminates exactly once.

## Cadence & evidence

- Run before each release that touches the agent graph, the queue, or the
  executor; and on a monthly schedule.
- The DR drill ([disaster-recovery.md](disaster-recovery.md)) writes a
  timestamped evidence file; the resilience drills produce their evidence as a
  green `pytest -m load` run (attach the run link/log to the game-day record).

## What "pass" means

Every assertion above holds. A failure here is a resilience regression: triage
before shipping — a run that terminates as an abstention on a provider outage,
or a duplicate terminal event, is exactly the kind of silent corruption these
drills exist to catch.
