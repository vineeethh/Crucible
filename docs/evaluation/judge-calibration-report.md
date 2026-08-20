# Judge calibration report

- generated: 2026-07-18
- rubric: `judge-rubric@1`  holdout: `judge-rubric@1`  items: 12
- judge: `fake-judge` (deterministic heuristic; the real judge is a different
  model family from the generator — bias reduction, not independence)

The judge scores **explanation quality only**. It is a secondary trend and
never overrides a Tier 1 oracle (ADR-005, metric contract). This report is the
evidence that licenses that limited use.

**Overall raw agreement with human labels: 0.8333**  
**Mean quadratic-weighted kappa: 0.7483**

| dimension | raw agreement | weighted kappa | n |
|---|---|---|---|
| groundedness | 0.8333 | 0.7656 | 12 |
| provenance | 0.8333 | 0.8992 | 12 |
| usefulness | 0.75 | 0.4 | 12 |
| uncertainty | 0.9167 | 0.9286 | 12 |

## Notable disagreements (|human - judge| >= 2)

| item | dimension | human | judge |
|---|---|---|---|
| h03 | usefulness | 0 | 2 |
| h05 | groundedness | 2 | 0 |
| h11 | usefulness | 0 | 2 |

## Limitations

- Small holdout (n per dimension is the item count); treat kappa as directional.
- The judge is calibrated for *this* rubric and workload; recalibrate when the
  judge model, rubric, prompt, or workload changes materially.
- Agreement is not correctness: the judge measures explanation quality, and a
  high score never implies the numeric answer is right — that is the oracle's job.
