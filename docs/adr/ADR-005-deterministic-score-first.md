# ADR-005: Deterministic score first, LLM judge second

Status: Accepted · Date: 2026-07-14

## Context
The reference workload was chosen precisely because most answers admit an executable
oracle. LLM judges carry position, verbosity, self-preference, and familiarity biases,
and no model may certify itself (charter principle 3).

## Decision
The scorer hierarchy in the metric contract is binding: Tier 1 deterministic result
oracles are the primary correctness gate; policy checks are hard gates; a calibrated
LLM judge scores only explanation quality against a frozen rubric, calibrated on
held-out human labels, and can never override a Tier 1 result.

## Alternatives considered
- **Judge-only scoring** — rejected: less defensible, biased, and unnecessary for a
  workload with executable ground truth.
- **Blended single quality score** — rejected: a high prose score must never mask a
  failed oracle; tiers are stored separately.

## Consequences
- Every deterministic case requires a trusted reference program (cost accepted; the
  seed suite demonstrates the pattern including an independent second calculation).
- Judge development is deferred until Phase 6 and gated on a published calibration report.
- Some qualities (usefulness, tone) are trends, not gates, until human labels exist.

## Revisit trigger
A future workload without executable oracles — which would require new oracle design,
not a relaxation of this hierarchy.
