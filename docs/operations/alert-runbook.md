# Runbook: Reliability Alerts

Status: Phase 6 · Owner: on-call / project owner
Related: [observability.md](observability.md) ·
[sandbox-incident-runbook.md](sandbox-incident-runbook.md) ·
[failure-taxonomy.md](../evaluation/failure-taxonomy.md)

This runbook covers the reliability alerts emitted by `evaluate_slo_alerts`
(`GET /v1/metrics/alerts`). Each alert names the section here it links to. A
containment-breach alert (`sandbox_containment`, SEV1) is **not** here — go
straight to [sandbox-incident-runbook.md](sandbox-incident-runbook.md).

The alert rules are pure functions over the reliability metrics, so any of these
scenarios can be reproduced in a staging drill by feeding synthetic telemetry
through `reliability()` + `evaluate_slo_alerts()` — do this after any change to
the thresholds or the metric definitions.

## General approach

1. **Confirm the signal is real, not a sampling artefact.** The metrics endpoints
   aggregate the most recent runs (`limit`, default 500). A tiny denominator can
   swing a rate. Widen the window before acting.
2. **Localize.** Pull `GET /v1/metrics/reliability` and the failure taxonomy.
   One category dominating points at a specific regression; a broad spread points
   at an infrastructure or model-provider event.
3. **Attribute.** Cost/latency are per-run; the trace endpoint explains a single
   run end to end. Find the runs driving the metric and read their traces.

---

## trace-completeness

**SEV2 · fires when fleet trace completeness < 0.99.**

A run we cannot fully explain is a reliability defect: the DoD requires every
terminal run to show its trace, cost, latency, versions, and taxonomy.

1. Find incomplete runs: the online sampler records `online.trace_complete`
   deterministic scores; a run trace's `complete=false` lists what is missing
   (`manifest`, `node_trace`, `terminal_event`, `release`, `model_versions`).
2. Common causes and fixes:
   - **`terminal_event` missing** — a worker died between the status transition
     and the terminal event append. The compare-and-set transitions make this
     rare; check for crash-looping workers.
   - **`model_versions` / `release` missing** — the config manifest or attempt
     records are not carrying version metadata. A recent deploy that changed the
     manifest shape is the usual culprit; check the release that correlates with
     the drop.
   - **`node_trace` missing** — the agent short-circuited before emitting node
     events (e.g. an early policy denial). Confirm this is expected for that run
     class; if not, it is an orchestration bug.
3. Fix the source of the missing span; re-run the online sampler to confirm the
   metric recovers. Do **not** backfill fabricated spans — an incomplete trace is
   recorded honestly.

## technical-completion

**SEV2 · fires when the technical completion rate < 0.80.**

Completion rate = terminal-and-not-operationally-cancelled ÷ terminal. A drop
means runs are failing to reach a clean terminal state.

1. Read the failure taxonomy. Map the dominant category via
   [failure-taxonomy.md](../evaluation/failure-taxonomy.md).
2. If dominated by `SANDBOX_*` (timeout/OOM/resource): the execution plane is
   under-provisioned or a question class is too heavy — tune `ExecutionLimits`,
   or investigate the generating question. If a *breach* is suspected, escalate
   to the sandbox runbook (SEV1).
3. If dominated by model/provider errors: check the provider status and the model
   backend config. Operational faults (`ExecutorUnavailable`) are **not** quality
   failures and carry no taxonomy category — a spike here is an outage, handle it
   as one.
4. If broad-spectrum with no dominant category: suspect a recent release. Compare
   completion rate across releases (the trace carries the release id) and roll
   back the correlated deploy if it regressed.

## abstention-spike

**SEV3 · fires when the abstention rate > 0.50.**

Informational: a high abstention rate can be *correct* (the system refusing to
fabricate) or a *regression* (over-cautious verification, or a capability gap).

1. Distinguish honest refusal from regression: sample abstained runs' traces. If
   the questions are genuinely unsupported, the system is working — consider
   whether the question mix changed upstream.
2. If runs that used to answer now abstain: a verification threshold or the model
   changed. Compare against the calibration/eval baseline; check the release that
   correlates with the rise.
3. This is a trend signal — it does not page. Track it against the eval suite
   before changing verification behaviour, so a fix does not trade abstention for
   fabrication.

---

## Verification before closing

- [ ] The alert has cleared on `GET /v1/metrics/alerts` over a full window.
- [ ] Root cause identified and the correlated release/config named.
- [ ] If a metric definition or threshold changed, the SLO drill was re-run.
- [ ] No honest signal was suppressed to clear the alert (no fabricated traces,
      no abstention traded for fabrication).
- [ ] Timeline and root cause recorded; this runbook updated with what was learned.
