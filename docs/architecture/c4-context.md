# Crucible — C4 Level 1 Context (with plane separation)

Status: Phase 0 baseline · Date: 2026-07-14

## System context

```mermaid
flowchart LR
  subgraph People
    AE[Applied AI engineer]
    PE[Platform engineer]
    RV[Reviewer]
    DU[Demo user]
  end

  AE & PE & RV & DU --> CR[Crucible platform<br/>evaluates and operates the<br/>data-analysis reference agent]

  CR --> IDP[OIDC identity provider]
  CR --> MP[LLM model providers<br/>provider-neutral gateway]
  CR --> SBX[Managed microVM sandbox<br/>untrusted code boundary]
  CR --> OST[(Object storage<br/>datasets + artifacts)]
  CR --> OBS[Langfuse + OTel backends<br/>redacted telemetry only]
  GH[GitHub Actions CI/CD] --> CR
```

## Plane separation (the core architectural claim)

```mermaid
flowchart TB
  subgraph Serving[Serving plane — must stay available and bounded]
    API[API + auth + quotas] --> Job[Durable job]
    Job --> Agent[Agent workflow: profile→plan→code→execute→observe→repair→verify→synthesize]
    Agent --> Sandbox[Constrained execution]
    Agent --> Answer[Answer / abstain / review]
  end

  subgraph Evaluation[Evaluation plane — async, expensive, evidence-preserving]
    Cases[Versioned cases + references] --> Runner[Experiment runner]
    Runner --> Scorers[Tier 1 oracle → policy → calibrated judge]
    Scorers --> Metrics[Immutable comparison results]
    Metrics --> Gate[CI release gate]
  end

  Agent -. sampled redacted traces .-> Runner
  Agent -. versions, cost, latency .-> Tele[Observability plane]
  Runner -. scores .-> Tele
```

Rules encoded by this diagram:

1. The serving plane answers a request; the evaluation plane judges *changes to the
   agent*. They fail independently — analytics delay never degrades serving.
2. The evaluation plane never silently rewrites baselines.
3. The sandbox is outside the API/worker trust boundary (see ADR-003 and the threat model).
4. Only redacted, hashed, access-controlled content crosses into observability providers.

## Agent graph (Phase 4)

The durable data-agent is an explicit typed graph (ADR-008): each node has one
job, a typed output, and emits a trace event; the runner checkpoints after every
node so a worker restart resumes from the last completed node.

```mermaid
stateDiagram-v2
  [*] --> Validate
  Validate --> Profile
  Validate --> Done: policy denied
  Profile --> ExactCache
  ExactCache --> Route: miss
  Route --> Plan
  Plan --> Code
  Plan --> Done: abstain (unsupported)
  Code --> Execute
  Execute --> Observe
  Observe --> Verify: execution ok
  Observe --> Reflect: correctable & attempts remain
  Observe --> Done: abstain (fatal / exhausted / oscillation)
  Reflect --> Execute: repaired code (bounded, max 2)
  Verify --> Synthesize: answer
  Verify --> HumanReview: ambiguous
  Verify --> Done: abstain (below threshold)
  HumanReview --> Synthesize: approved (resume)
  HumanReview --> Done: rejected
  HumanReview --> [*]: interrupt (waiting_review)
  Synthesize --> OutputGuard
  OutputGuard --> Done: answered
```

Terminal reasons map to the Phase 2 run state machine; `agent_runs` stays the
single source of truth for status, and `agent_checkpoints` holds only what is
needed to resume. Model plan/code/repair use a provider-neutral gateway
(`fake` deterministic backend by default; OpenAI-compatible contract for real
models); generated code always runs in the Phase 3 sandbox.

Container- and component-level diagrams (C4 L2/L3) beyond this are created as the
corresponding services come into existence — not speculated here.
