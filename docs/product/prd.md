# Crucible v1 — Product Charter (PRD)

Status: Approved for Phase 0 · Date: 2026-07-14 · Owner: project owner

## 1. Problem

Teams shipping LLM agents cannot answer four questions with evidence: Did this change
improve the agent? Why did this run fail? Is it safe to let it execute code? Can we
control cost and latency? Crucible is the system that answers them.

## 2. Product thesis

**Crucible v1 is a multi-tenant, API-first platform that evaluates and operates one
bounded reference workload: a data-analysis agent answering questions over uploaded
tabular datasets.** The differentiator is not the agent loop — it is the evidence
around the loop: executable offline evaluation, versioned experiment comparisons,
production tracing, constrained execution, regression gates, and a stable failure
taxonomy.

## 3. The exact v1 workload

- **Input:** one uploaded CSV/Parquet file (immutable, content-addressed version), a
  natural-language question, and a bounded execution policy.
- **Supported question classes (v1):** scalar aggregates (sum/mean/count), grouped
  aggregates, filtered counts, date/period filters, argmax/argmin lookups, distinct
  counts, missing-value questions, small table answers, and invalid/unanswerable
  questions whose correct outcome is abstention or clarification.
- **Output:** a numeric/categorical/table answer with provenance pointing at the
  actually computed result artifact, or a truthful abstention / review request.
- **Terminal states (exhaustive):** `answered`, `abstained`, `needs_human_review`,
  `policy_denied`, `budget_exhausted`.
- **Why this workload:** most questions admit a Tier 1 programmatic oracle — a trusted
  reference program computes the expected value. Execution success alone is never
  treated as correctness.

## 4. Explicitly excluded capabilities (v1 non-goals)

1. Internet browsing, email, SaaS connectors, or acting on users' behalf.
2. Arbitrary package installation, arbitrary shell, user-supplied container images,
   GPU execution, or model-controlled sandbox configuration.
3. Multi-agent delegation and cross-agent or cross-user memory.
4. Open-ended "find insights" tasks (weak ground truth dilutes the evaluation story).
5. Autonomous remediation of production incidents.
6. Compliance certification claims (SOC 2 / HIPAA / GDPR). Controls may be adopted;
   certification is a separate workstream.
7. A universal "agent benchmark." v1 ships one rigorous reference workload plus a
   harness seam for future adapters.

## 5. Personas and primary workflows

| Persona | Job | Workflow |
|---|---|---|
| Applied AI engineer | Improve the agent without silent regression | Candidate config → experiment → per-case deltas → merge only after gate |
| Platform/reliability engineer | Diagnose failures, latency, spend | Trace → taxonomy filter → replay redacted case → fix + regression test |
| Reviewer/domain expert | Adjudicate uncertain answers | Review queue → versioned rubric → categorical score → taxonomy feed |
| Demo user | Ask a data question, trust the answer | Upload → run → answer + result artifact + provenance + confidence state |

## 6. First release gate (the gate that must exist before anything ships)

A pull request may merge only if:

1. **Deterministic smoke suite passes** — the seed suite (`evals/suites/seed-v0.1.0.yaml`,
   growing to 8–12 smoke cases) runs against the candidate config; any Tier 1 oracle
   failure vs the frozen baseline blocks.
2. **Zero critical policy/safety violations** — sandbox canaries, forbidden-import,
   no-network, and schema/contract checks are hard gates.
3. **Paired comparison discipline** — aggregate deltas use paired per-case outcomes
   with bootstrap confidence intervals; a release is blocked when the upper 95% bound
   of the quality delta is below −δ (δ documented per metric in the metric contract).
4. **No silent re-baselining** — baseline updates require an explicit reviewed PR with
   rationale and evidence links.
5. Provider outages / evaluator failures are classified as operational failures, never
   recast as model-quality results.

## 7. Measurable v1 outcomes (validated in staging, not marketed beforehand)

| Dimension | Target | Measurement |
|---|---|---|
| Offline correctness | Published frozen core suite; baseline reported, not preselected | Exact / result-set scorer per case |
| Regression detection | A deliberately introduced regression fails CI | Candidate vs baseline paired evaluation |
| Traceability | 100% of terminal runs have run manifest + node-level trace | Trace-completeness metric |
| Sandbox safety | Zero high-severity escape/secret/network violations | Deny-by-default execution test suite |
| Reliability | Retry and abstention measurable per failure class | Outcome + taxonomy dashboard |
| Performance | p95 target set only after baseline profiling | Load test + percentile dashboard |
| Cost | Every LLM call has provider/model/token/cost metadata or explicit `unknown cost` | Cost-attribution completeness |

## 8. Non-negotiable principles

1. Correctness is not a vibe — executable ground truth first; prose never masks a failed oracle.
2. Serving plane and evaluation plane are different products.
3. No model certifies itself.
4. Generated code is hostile until contained.
5. Version every behavior-changing input (prompt, model, router, dataset, evaluator, sandbox image, policy, release).
6. Do not overbuild before the scorecard works.

## 9. Definition of done for Phase 0 (this charter)

A reviewer can state, from these documents alone: the exact v1 workload (§3), the
strongest oracle for each seed case (`evals/cases/*.yaml`, `strongest_oracle_note`),
the excluded capabilities (§4), and the first release gate (§6). All seven ADRs record
alternatives and consequences. No ambiguous "AI quality score" exists anywhere in the
metric contract.
