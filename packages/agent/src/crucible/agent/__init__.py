"""Crucible durable data-agent graph.

Boundary rule (import-linter): imports domain + execution + pydantic only. It
defines its own persistence and model-gateway ports; the worker injects concrete
adapters.
"""

from crucible.agent.cache import (
    compute_cache_key,
    config_signature,
    normalize_question,
    question_sha256,
)
from crucible.agent.errors import AgentError, ModelNotConfigured, ModelUnavailable
from crucible.agent.evaluate import EphemeralPersistence, EvalTrace, run_to_completion
from crucible.agent.graph import GraphRunner
from crucible.agent.models import (
    JUDGE_RUBRIC_VERSION,
    FakeJudge,
    FakeLiteModel,
    FakeModel,
    Judge,
    ModelSpec,
    OpenAICompatJudge,
    OpenAICompatModel,
    register_openrouter_free_model,
)
from crucible.agent.nodes import AgentContext, AgentNodes
from crucible.agent.orchestrator import resolve_review, run_agent
from crucible.agent.ports import (
    AgentPersistence,
    AnswerCache,
    AttemptRecord,
    CachedAnswer,
    DatasetView,
    ModelConfig,
    ModelGateway,
    ModelRole,
    ModelUsage,
    RunView,
)
from crucible.agent.router import ROUTER_POLICY_VERSION, RouterPolicy, TieredModelGateway
from crucible.agent.schemas import (
    JUDGE_DIMENSIONS,
    MONETARY_AGGREGATE_OPS,
    AnalysisPlan,
    Answer,
    AnswerKind,
    GeneratedCode,
    JudgeRubricScore,
    Operation,
    PlanStep,
    Provenance,
    VerificationDecision,
    VerificationVector,
)
from crucible.agent.state import (
    AgentState,
    ColumnView,
    ExecutionEvidence,
    Node,
    TerminalReason,
)

__all__ = [
    "JUDGE_DIMENSIONS",
    "JUDGE_RUBRIC_VERSION",
    "MONETARY_AGGREGATE_OPS",
    "ROUTER_POLICY_VERSION",
    "AgentContext",
    "AgentError",
    "AgentNodes",
    "AgentPersistence",
    "AgentState",
    "AnalysisPlan",
    "Answer",
    "AnswerCache",
    "AnswerKind",
    "AttemptRecord",
    "CachedAnswer",
    "ColumnView",
    "DatasetView",
    "EphemeralPersistence",
    "EvalTrace",
    "ExecutionEvidence",
    "FakeJudge",
    "FakeLiteModel",
    "FakeModel",
    "GeneratedCode",
    "GraphRunner",
    "Judge",
    "JudgeRubricScore",
    "ModelConfig",
    "ModelGateway",
    "ModelNotConfigured",
    "ModelRole",
    "ModelSpec",
    "ModelUnavailable",
    "ModelUsage",
    "Node",
    "OpenAICompatJudge",
    "OpenAICompatModel",
    "Operation",
    "PlanStep",
    "Provenance",
    "RouterPolicy",
    "RunView",
    "TerminalReason",
    "TieredModelGateway",
    "VerificationDecision",
    "VerificationVector",
    "compute_cache_key",
    "config_signature",
    "normalize_question",
    "question_sha256",
    "register_openrouter_free_model",
    "resolve_review",
    "run_agent",
    "run_to_completion",
]
