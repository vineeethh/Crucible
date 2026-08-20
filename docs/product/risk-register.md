# Crucible Risk Register v0.1.0

Status: Living document, reviewed at each phase exit · Date: 2026-07-14
Scale: Likelihood/Impact = Low/Med/High. Owner is the project owner unless noted.

| ID | Risk | L | I | Mitigation | Trigger to act |
|---|---|---|---|---|---|
| R1 | **No safe execution boundary** — generated code reaches host/CI trust | Med | High | Fake executor until Phase 3 completes; microVM adapter in prod; canary suite gates exposure | Any canary failure; any plan to demo before P3 exit |
| R2 | **Weak or unreviewed gold data** — eval claims collapse under scrutiny | Med | High | Hand-verified seed suite with reference programs + independent second calculation; lineage rules; no LLM-generated labels without verification | Any case merged without a reference artifact |
| R3 | **Model/provider instability** (API changes, quota, pricing, deprecation) | High | Med | Provider-neutral gateway; config manifests; declared fallback policy; bounded budgets; staging canaries | Provider deprecation notice; sustained error-rate alert |
| R4 | **Judge–human disagreement** — judge cannot be calibrated to useful agreement | Med | Med | Judge restricted to explanation-quality diagnostics; never a correctness gate; human review absorbs adjudication | Held-out κ below agreed floor after rubric iteration |
| R5 | **Eval CI too costly/flaky** — gates get ignored or disabled | Med | High | Small deterministic PR smoke suite; nightly full suite; provider failures classified as operational, not quality | Smoke flake rate > ~2%; PR gate runtime > ~10 min |
| R6 | **Scope creep** — generic agent/browsing/connectors dilute the evidence story | High | High | PRD non-goals (§4); ADR-006; every scope addition requires a charter amendment | Any backlog item outside the reference workload before v1 |
| R7 | **Solo-developer schedule risk** — 706h plan slips | High | Med | 20% contingency budgeted; 8-week MVP cut line = P0–P5 + minimal P6; never cut sandbox, eval harness, or regression evidence | Two consecutive phases exceed estimate by >30% |
| R8 | **Sensitive data in traces/fixtures** — privacy incident or unlaunchable telemetry | Med | High | Synthetic-only fixtures (enforced rule); redaction before export; data classification; retention policy before live traces | Any real dataset appearing outside tenant-scoped storage |
| R9 | **Cache correctness/privacy bug** — semantic cache returns wrong or cross-tenant answer | Low | High | No cache during baseline; exact cache only with tenant+dataset+config key; semantic cache deferred behind measured false-hit study | Any false hit in exact-cache instrumentation |
| R10 | **Benchmark leakage/contamination** — synthetic descendants of test cases tune the system | Med | Med | Frozen test manifest; lineage recording for synthetic cases; dev/test/calibration split policy | Lineage field missing on any generated case |
| R11 | **CI/CD compromise** — poisoned action or untrusted PR with secrets | Low | High | SHA-pinned actions; read-only default token; OIDC; no `pull_request_target` with secrets; CODEOWNERS on workflows | Dependabot/security advisory on a pinned action |
| R12 | **Cost overrun** on provider/eval spend | Med | Med | Per-org and per-run budgets; nightly suite quotas; cost attribution completeness metric | Monthly spend > budget; any run without cost metadata |

Retired risks and resolution evidence are appended below on phase exits (none yet).
