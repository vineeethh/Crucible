# Runbook: Sandbox Execution Incident

Status: Phase 3 · Severity: treat any suspected containment breach as SEV-1
Owner: on-call / project owner · Related: [sandbox.md](../security/sandbox.md)

Use this when a sandbox behaves outside its contract: a canary regresses, a
suspected escape, network egress observed, resource exhaustion on a host, or a
runaway spend/latency traced to execution.

## Immediate triage (first 15 minutes)

1. **Contain.** Stop scheduling new executions:
   - set `EXECUTOR_BACKEND=fake` for the worker and redeploy, or scale the
     worker to zero. Runs then abstain instead of executing (safe by default).
2. **Preserve evidence.** Do **not** delete containers, work dirs, or traces
   yet. Capture:
   - `docker ps -a --filter ancestor=crucible-sandbox-runner:local`
   - the run's `manifest.json` and `result.json` from the work dir if present
   - the `agent_runs` / `run_events` rows and the `sandbox.execute` span
3. **Classify.** Confirm whether this is a *contained* failure (a canary-style
   outcome: timeout, OOM, resource-kill — the system working) or a *breach*
   (network reached, host file read, another tenant's data, privilege gained).

## If a containment breach is suspected (SEV-1)

1. Disable the execution plane entirely (backend `fake`, worker scaled to zero).
2. Rotate any credential that *could* have been reachable, even though the
   design mounts none into the guest — assume-breach on secrets first.
3. Snapshot the runner image digest, the `DockerExecutor` config in effect, and
   the offending program source (from the attempt record).
4. Reproduce in isolation: run the program through the canary harness on an
   isolated host. Add a new canary that captures the breach before any fix.
5. Fix, prove the new canary fails-closed, then re-enable behind a flag.

## Contained resource exhaustion (not a breach)

A memory/CPU/pids/output bomb that hit its cap is the system working. If it is
degrading a *host* (Docker backend only):
1. Lower the relevant `ExecutionLimits` default and redeploy.
2. Confirm `docker stats` returns to baseline; orphaned containers are
   force-removed by the executor's `finally` block — list and remove any strays.
3. In production this cannot affect neighbors: each attempt is its own microVM.

## Provider / daemon outage

- `ExecutorUnavailable` / `ExecutorNotConfigured` are operational faults, not
  program failures: runs surface an operational error and are **not** recorded
  as a model quality failure (the exit class carries no taxonomy category).
- Docker backend: `docker info`; restart Docker Desktop / the daemon.
- microVM backend: check provider status and the control-plane credential; the
  adapter refuses to fall back to a weaker boundary by design (ADR-003).

## Verification before closing

- [ ] The full canary suite passes: `pytest -m sandbox`.
- [ ] Any new breach has a dedicated canary that fails on the old code.
- [ ] No sandbox container or work dir is orphaned.
- [ ] The threat model and this runbook are updated with what was learned.
- [ ] Root cause and timeline recorded; credentials rotated if in any doubt.
