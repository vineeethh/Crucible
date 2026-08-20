# ADR-008: Implement durable-graph semantics now; defer the LangGraph library

Status: Accepted · Date: 2026-07-16 · Supplements ADR-004

## Context

Phase 4 needs a durable agent workflow: a graph of typed nodes
(validate → profile → plan → code → execute → observe → repair → verify →
synthesize) with checkpointing so a worker restart resumes safely, and an
interrupt for human review. The master plan and §4 tech table name **LangGraph**
for this, while explicitly qualifying it as "major-pinned **after API
validation**" and noting a "handwritten loop is viable but costs persistence/
interrupt semantics."

Two facts shape the decision:

1. The platform already has a Postgres-backed durable run with a compare-and-set
   state machine, append-only events, and SSE (Phase 2). That is the system of
   record for run status and history.
2. LangGraph is a fast-moving dependency whose current API cannot be validated
   in this build environment, and its Postgres checkpointer introduces a second
   store of run state alongside `agent_runs` — two sources of truth for "where
   is this run."

## Decision

Implement the **durable-graph semantics** ourselves in `packages/agent`, on top
of the existing Postgres run store, and defer adopting the LangGraph **library**.
Concretely:

- The agent is an explicit typed graph: each node is a small async function over
  a serializable `AgentState`, with the exact node contract from master plan §8.2.
- The runner persists a checkpoint (state + last node) to `agent_checkpoints`
  after every node, so re-delivery of the job resumes from the last completed
  node — this is the durable-execution and resume guarantee.
- Human review is an interrupt: the graph transitions the run to `waiting_review`
  and stops; a review resolution re-enters the graph at that node.
- `agent_runs` remains the single source of truth for business status; the
  checkpoint holds only what is needed to resume (plan §8.3, "run memory").

The node interfaces are kept clean so LangGraph (or Temporal) can be adopted
later behind the same seam without touching the node logic.

## Alternatives considered

- **Adopt LangGraph now** — rejected for this phase: an unvalidated fast-moving
  API plus a second run-state store, for semantics we can implement directly on
  the store we already have. The plan itself gates LangGraph on API validation.
- **No checkpointing (re-run from scratch on restart)** — rejected: violates the
  Phase 4 DoD ("worker restart resumes safely") and can double-charge model/
  sandbox cost.

## Consequences

- Full control over the exact §8.2 semantics, deterministic and offline-testable
  (no library API surface to mock), and one source of truth for run state.
- We own the checkpoint format and resume logic (covered by tests).
- Revisit trigger: a LangGraph spike validates the current API and shows enough
  value (e.g., sub-graph reuse, streaming tokens) to justify migrating behind the
  existing node interfaces — at which point `agent_runs` stays authoritative and
  LangGraph owns only in-flight graph state.
