# Evaluation Guide (Phase 5)

How the offline evaluation harness turns the metric contract into an executable
regression gate. Read the [metric contract](metric-contract.md) first — this
document is how it is enforced.

## What the harness does

For each case in a versioned suite it runs the **real agent graph** (the same
one that serves requests), scores the answer against a trusted oracle, and
compares the candidate config to a **frozen baseline** with a paired bootstrap
confidence interval. It never blends correctness and policy into one number, and
it never claims an answer is correct just because code ran.

```
case (question + oracle) ──▶ agent (plan→code→sandbox→verify→answer)
                              │
                              ▼
                     Tier 1 correctness  +  Tier 3 policy
                              │
          candidate vs frozen baseline (paired bootstrap CI)
                              │
                     gate: PASS / FLAG / BLOCK
```

## Ground truth

Every gold answer in `evals/suites/core-v1.0.0.yaml` is cross-checked against an
independent, executable reference calculator
(`evals/references/eval_sales_v1_reference.py`) — verified by
`tests/unit/test_eval_governance.py::test_gold_answers_match_the_independent_reference`.
Fixtures are pinned by SHA-256 and re-verified on load; a tampered fixture is
rejected. Cases are immutable once released: the baseline pins the suite content
hash, so editing a released case fails the lineage test until the baseline is
reviewed and regenerated.

## Running it

```bash
# Build the sandbox runner (needed for real code execution):
make sandbox-image

# Compare the reference config against the frozen baseline and gate:
python -m crucible.evaluation run \
    --suite evals/suites/core-v1.0.0.yaml \
    --baseline evals/baseline.json --executor docker --out evals/reports
#   -> writes report.json + report.md; exit code 1 if the gate BLOCKs.

# Fast smoke subset (6 cases) — the PR gate:
python -m crucible.evaluation run --suite evals/suites/core-v1.0.0.yaml \
    --baseline evals/baseline.json --smoke --executor docker --out evals/reports
```

The report carries everything needed to reproduce and audit the score: git SHA,
suite/fixture/config hashes, scorer version, per-case results, the paired delta
with its confidence interval, the gate verdict, efficiency, and the failure
taxonomy. A `content_sha256` over the deterministic parts (everything except the
timestamp) lets a reader confirm a re-run produced the identical result — the
bootstrap uses a fixed seed, so the interval is reproducible.

## The gate (metric contract §5)

| Outcome | Condition |
|---|---|
| **BLOCK** | any candidate policy/contract hard failure, **or** the upper 95% CI bound of the paired correctness delta is below `-tolerance` |
| **FLAG** | correctness regressed (negative delta) but the interval is inconclusive — human review |
| **PASS** | no regression |

Tolerance is stored in `evals/baseline.json` (default 0.02).

## Baseline governance

The baseline is frozen evidence — the reviewed per-case results of the approved
config. A candidate is compared against it **without re-running it**, so baseline
evidence is never overwritten by a candidate run. Re-baselining is an explicit,
reviewed edit:

```bash
python -m crucible.evaluation baseline \
    --suite evals/suites/core-v1.0.0.yaml --executor docker \
    --out evals/baseline.json --approved-by "you" --notes "why"
```

`evals/baseline.json` is CODEOWNER-protected; changing it requires a reviewed PR
with rationale (a re-baseline changes what "correct" means).

## Where it runs in CI

- **Every PR (fast lane):** the scorer, comparator, gate, reference-verification,
  fixture-integrity, lineage, and reproducibility tests — including a
  deliberately injected regression that the gate must block
  (`tests/unit/test_eval_comparator.py`).
- **Sandbox job:** the full harness against the real Docker sandbox — the
  reference config reproduces the baseline (PASS) and a regressed config is
  caught, plus the CLI smoke gate produces a report artifact
  (`tests/sandbox/test_eval_harness.py`).

## Scope notes

- The `fake` executor returns no value, so it is only a wiring dry-run; real
  evidence requires the `docker` (or, in cloud, `microvm`) executor.
- A live evaluation service + score database and a richer comparison dashboard
  are Phase 7 (product dashboard) work; Phase 5 ships the file-based report that
  CI gates on, and a read-only comparison page (`/evaluations`) over the
  committed example report.
