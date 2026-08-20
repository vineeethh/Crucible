"""Serializable agent state and the graph node identifiers.

The state is a Pydantic model so the runner can checkpoint it to Postgres after
every node (`model_dump_json`) and resume from it after a worker restart. It
holds only what is needed to resume — not the dataset bytes, which are re-read
from immutable storage.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from crucible.agent.schemas import AnalysisPlan, Answer, ChallengeOutcome, VerificationVector
from crucible.execution import ArtifactRef


class Node(StrEnum):
    VALIDATE = "validate"
    PROFILE = "profile"
    EXACT_CACHE = "exact_cache"
    ROUTE = "route"
    PLAN = "plan"
    CODE = "code"
    EXECUTE = "execute"
    OBSERVE = "observe"
    REFLECT = "reflect"
    CHALLENGE = "challenge"
    VERIFY = "verify"
    HUMAN_REVIEW = "human_review"
    SYNTHESIZE = "synthesize"
    OUTPUT_GUARD = "output_guard"
    DONE = "done"


class TerminalReason(StrEnum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"
    NEEDS_REVIEW = "needs_review"  # waiting for a reviewer (an interrupt, not final)
    POLICY_DENIED = "policy_denied"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"


class ColumnView(BaseModel):
    name: str
    dtype: str
    # Column-level statistic from the storage-layer profiler (never a cell
    # value). Optional: populated on the real dataset-load path
    # (apps/worker/agent_runtime.py); left None on eval-harness/fake paths.
    # Never rendered into a prompt — prompts._schema_block prints name+dtype
    # only — it exists solely for the host-side anti-fabrication guard in
    # policy.py.
    distinct_count: int | None = None


class ExecutionEvidence(BaseModel):
    """A compact record of one Execute attempt (never the full result payload if
    it is large — the artifact store holds that)."""

    exit_class: str
    ok: bool
    failure_category: str | None = None
    result: dict[str, object] | None = None
    stderr_excerpt: str = ""
    error_detail: str | None = None
    image_ref: str = ""
    backend: str = ""
    code_sha256: str = ""
    # Non-result files the sandboxed program wrote (e.g. a TABLE plan's
    # table.csv), already host-validated by execution.parser.collect_results.
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class AgentState(BaseModel):
    run_id: str
    organization_id: str
    dataset_version_id: str
    question: str

    # Populated as the graph runs.
    profile: list[ColumnView] = Field(default_factory=list)
    dataset_sha256: str | None = None
    dataset_ready: bool = True
    cache_key: str | None = None
    config_signature: str | None = None  # gateway config digest bound into the cache key

    plan: AnalysisPlan | None = None
    plan_retry_used: bool = False  # the one structured-output retry for the planner
    code_source: str | None = None
    code_sha256: str | None = None
    code_retry_used: bool = False  # the one structured-output retry for the coder

    last_execution: ExecutionEvidence | None = None
    repair_count: int = 0
    fingerprints: list[str] = Field(default_factory=list)  # code+error signatures seen

    # Metamorphic re-executions of the SAME program against transformed
    # datasets (Node.CHALLENGE), gathered before verify() decides.
    challenge_results: list[ChallengeOutcome] = Field(default_factory=list)

    verification: VerificationVector | None = None
    review_decision: str | None = None  # "approve" | "reject" once a reviewer acts

    answer: Answer | None = None
    terminal_reason: TerminalReason | None = None
    detail: str = ""
