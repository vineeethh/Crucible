# Crucible Evaluation Assets

Ground-truth governance for the reference workload (data-analysis over tabular files).
These rules are binding from Phase 0 onward.

## Layout

```
evals/
├── suites/        # Versioned suite manifests pinning case versions (immutable once released)
├── cases/         # One YAML per case version: question, dataset hash, answer contract, oracle, verification provenance
├── fixtures/      # Synthetic/public datasets ONLY + content-hash manifests. Never production data or credentials.
└── references/    # Trusted reference calculators (pure stdlib Python) + independent second checks
```

## Reproducing the seed suite golden values

```
python evals/references/run_all.py          # one JSON line per case; nonzero exit on failure
python evals/references/independent_check_hv.py   # second independent calc for seed-01/seed-02
```

Verified 2026-07-14 on Python 3.14.2. Fixture hash pinned in every case:
`sha256:347e147d4e1f5709250a759f56924c837adc5d24795ded8d8964e6dcc9d6c849`.

## Ground-truth rules (from the master plan §10.2 and study guide §4.2)

1. Every deterministic case has a trusted reference program; high-value cases get a
   second independently written calculation or manual review.
2. Cases and suites are **immutable once released** — edits create a new version with lineage.
3. Store dataset hash, reference code, expected output, tolerance, and canonicalization
   with each case; comparison rules are declared, never implicit in scorer code.
4. Order-insensitive comparison for tables where order carries no meaning; deliberate
   `abs_tol`/`rel_tol`, never hidden rounding.
5. Invalid/ambiguous questions are first-class cases whose expected outcome is
   abstention or a clarifying question.
6. **Never** use an LLM-generated expected answer without reference-program or human verification.
7. Synthetic descendants of a test case record lineage and stay out of the frozen test split.
8. Re-baselining requires an explicit reviewed PR with rationale — never silent.
