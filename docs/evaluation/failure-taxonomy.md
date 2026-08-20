# Crucible Failure Taxonomy v0.1.0

Status: Frozen for Phase 0 · Date: 2026-07-14

Stable categories for trending failures over time. Each failure record carries one
category plus a free-text diagnostic and the evaluator version. Adding a category is a
reviewed governance change, not dashboard improvisation.

| Category | Meaning | Retryable? |
|---|---|---|
| `INPUT_INVALID` | Request fails validation (size, type, malformed question) | No — user-correctable |
| `INJECTION_SUSPECTED` | Direct or indirect prompt-injection indicators | **Never** — terminal + audit |
| `DATASET_PARSE_ERROR` | Upload cannot be parsed into a valid dataset version | No — user-correctable |
| `SCHEMA_MISMATCH` | Question/plan references columns or types that do not exist | Bounded repair with schema context |
| `PLAN_INVALID` | Planner output fails schema or semantic validation | One structured-output retry, then abstain |
| `TOOL_POLICY_DENIED` | Requested operation outside the allowlist | **Never** — no retry with more access |
| `CODE_SYNTAX_ERROR` | Generated program fails to parse/compile | Bounded repair (max 2) |
| `CODE_RUNTIME_ERROR` | Deterministic runtime failure in sandbox | Bounded repair (max 2) |
| `SANDBOX_TIMEOUT` | Wall-clock limit exceeded | No automatic retry with more time |
| `SANDBOX_RESOURCE_LIMIT` | CPU/memory/process/disk/output limit hit | No automatic retry with more resources |
| `RESULT_SERIALIZATION_ERROR` | Program ran but result artifact violates the contract | Bounded repair |
| `RESULT_ORACLE_MISMATCH` | Eval-only: computed result fails the case oracle | n/a (scoring outcome) |
| `EXPLANATION_UNGROUNDED` | Answer text contradicts or exceeds the verified result | No — regenerate synthesis only, never facts |
| `JUDGE_DISAGREEMENT` | Judge and deterministic/human signals conflict | Routes to human review |
| `CACHE_FALSE_HIT` | Cache returned an answer that fails the current oracle | Immediate cache invalidation + alert |
| `MODEL_PROVIDER_ERROR` | Transient provider/network failure | Exponential backoff with jitter, bounded |
| `BUDGET_EXHAUSTED` | Token/cost/time budget consumed | Terminal, truthful status |
| `HUMAN_REVIEW_REQUIRED` | Confidence policy routed to a reviewer | n/a (workflow state) |

Repeated code/error fingerprints terminate the repair loop regardless of remaining
attempts (oscillation guard).
