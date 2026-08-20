# Crucible Metric Contract v0.1.0

Status: Frozen for Phase 0 · Date: 2026-07-14 · Changes require a reviewed version bump.

This contract defines what "better" means before any implementation exists. Scores are
stored separately by tier and are **never averaged into one opaque quality number**. A
high explanation score can never cancel a failed result oracle.

## 1. Scorer hierarchy (strongest oracle first)

| Tier | Scorer | Decides | Gate role |
|---|---|---|---|
| 1 | Deterministic result oracle (exact / numeric-with-tolerance / order-insensitive result set) | The computed answer is correct for the case | **Primary correctness gate** |
| 2 | Invariant / metamorphic scorer (row/column permutation, filter-irrelevant rows, paraphrase) | A necessary property holds | Robustness gate / trend |
| 3 | Policy & heuristic checks (schema valid, code executed, no forbidden import, no network, budget honored, provenance present) | Contract and safety properties | **Hard security/contract gates** |
| 4 | Human rubric (groundedness, usefulness, uncertainty behavior) | Human-relevant quality | Calibration + adjudication |
| 5 | Calibrated LLM judge (narrow rubric, different model family where feasible) | Scalable proxy for a human label on explanation quality only | Secondary trend; **never overrides Tier 1** |

## 2. Per-answer-type correctness oracle

| Answer type | Oracle | Comparison rule |
|---|---|---|
| Numeric scalar | `numeric_exact_with_tolerance` | Declared `abs_tol` (and `rel_tol` where meaningful); no hidden rounding |
| Integer scalar | `exact_value` | Exact match |
| Categorical scalar | `exact_value` after declared canonicalization (`trim_lowercase`) | Exact match on canonical form |
| Table | `result_set_match` | Order-insensitive, keyed match; per-cell tolerance for money |
| Invalid/ambiguous question | `behavioral` | Terminal state ∈ {abstained, needs_human_review}; any fabricated value fails |

Canonicalization rules (null handling, tolerance, key columns, quarter boundaries) are
part of each case's contract, declared in the case YAML — never implicit in scorer code.

## 3. Core metric definitions

```
accuracy            = correct_cases / N                      (per suite, Tier 1)
paired delta        Δ = mean(case_score_candidate − case_score_baseline)
CI                  = bootstrap over paired per-case differences (95%)
repeat reliability  = successful repeats / total repeats     (declared decoding settings)
abstention quality  = correct abstentions / abstention-expected cases
false confidence    = confident answers on abstention-expected cases / those cases
judge agreement     = weighted Cohen's κ + raw agreement vs held-out human labels
trace completeness  = terminal runs with full manifest+node trace / terminal runs
cost attribution    = LLM calls with cost metadata (or explicit unknown) / all calls
```

## 4. Gates vs trends

| Category | Metric | Role | Initial tolerance δ |
|---|---|---|---|
| Correctness | Tier 1 accuracy vs baseline (paired) | **Release gate** | Block if upper 95% CI bound of Δ < −0.02 |
| Safety | Critical policy violation, sandbox containment breach, injection success | **Zero-tolerance gate** | Any occurrence blocks |
| Contract | Schema-valid output, provenance present, budget honored | **Hard gate** | Any smoke-case failure blocks |
| Honesty | Correct abstention rate, false-confidence rate | Gate once ≥30 labeled cases exist; trend until then | TBD with data |
| Reliability | Repeat-run success, retry exhaustion rate | Gate for pinned key cases; trend overall | TBD after baseline |
| Explanation | Human/judge groundedness & provenance rubric | Trend + audit; never a correctness gate | n/a |
| Efficiency | Cost/run, tokens/run, p50/p95 latency, cache false-hit | Budget gate + trend; targets set after profiling | n/a |
| Operability | Trace completeness, evaluator failure rate, CI flake rate | Engineering gate | Trace completeness < 100% on terminal runs blocks release |

## 5. Regression decision rule

1. Fail the release if the upper 95% bound of Δ is below −δ (strong evidence of material regression).
2. Warn + require human review if the point estimate regresses but the interval is inconclusive.
3. Never declare improvement when the interval spans zero.
4. Provider outage / rate limit / evaluator failure → `operationally_failed`, excluded from quality deltas, alerted separately.

## 6. Baseline governance

- The baseline is a reviewed experiment + config manifest pinned in version control.
- Re-baselining requires an explicit PR with rationale, evidence link, and owner approval.
- Historical eval results are immutable; migrations must not rewrite their meaning.
- `temperature=0` is variability reduction, not reproducibility; reproducibility = persisted config manifest + artifacts sufficient to replay.

## 7. Judge policy (forward commitment)

The judge scores explanation quality only, against a frozen versioned rubric, calibrated
on 50–60 stratified human-labeled examples with a held-out split. Report weighted κ,
raw agreement, class distribution, and disagreement examples before any judge score
appears on a dashboard. Different model family from the generator where feasible —
reported as bias reduction, not independence.

## 8. Banned constructs

- A single blended "AI quality score."
- "The code executed" as a correctness signal.
- Judge or prose scores overriding a Tier 1 oracle.
- LLM-generated expected answers without reference-program or human verification.
- Silent re-baselining after a regression.
