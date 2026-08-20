"""Ports the agent graph depends on. Concrete adapters are injected by the
worker (composition root); the graph itself imports no infrastructure.

Boundary (import-linter): the agent package imports domain + execution +
pydantic only. It defines its own thin persistence protocol rather than
coupling to the full application port surface, which keeps the graph trivially
testable with in-memory fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from crucible.agent.schemas import AnalysisPlan, GeneratedCode
from crucible.agent.state import ColumnView

# --------------------------------------------------------------- model gateway


class ModelRole(StrEnum):
    CLASSIFIER = "classifier"
    PLANNER = "planner"
    CODER = "coder"
    REPAIR = "repair"
    JUDGE = "judge"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Immutable behavior configuration recorded in the run manifest (plan
    principle 5: version every behavior-changing input)."""

    provider: str
    model_id: str
    role: ModelRole
    prompt_version: str
    policy_version: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    provider: str
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None  # None => explicit "unknown cost" marker
    # Routing evidence (Phase 8): when a tiered gateway escalated or fell back,
    # the usage says so, and cost/tokens include the burned primary call — a
    # report that hides retry cost is advertising, not measurement.
    escalated: bool = False
    route_reason: str | None = None


class ModelGateway(Protocol):
    """Higher-level than a raw completion call: each method renders the prompt,
    calls the provider, and validates the JSON into a typed schema, returning
    the schema plus usage metadata. Nodes never see raw model text."""

    def manifest(self) -> dict[str, dict[str, Any]]:
        """Per-role config for the run manifest."""
        ...

    async def plan(
        self, *, question: str, profile: list[ColumnView]
    ) -> tuple[AnalysisPlan, ModelUsage]: ...

    async def code(
        self, *, plan: AnalysisPlan, profile: list[ColumnView]
    ) -> tuple[GeneratedCode, ModelUsage]: ...

    async def repair(
        self,
        *,
        plan: AnalysisPlan,
        profile: list[ColumnView],
        prior_code: str,
        error: str,
    ) -> tuple[GeneratedCode, ModelUsage]: ...


# ------------------------------------------------------------------ exact cache


@dataclass(frozen=True, slots=True)
class CachedAnswer:
    """A previously verified answer, replayed only when every identity input
    matches (the key is tenant + dataset content + config + question)."""

    cache_key: str
    dataset_sha256: str
    config_signature: str
    answer: dict[str, Any]
    verification: dict[str, Any] | None


class AnswerCache(Protocol):
    """Exact-match answer cache (Phase 8, feature-flagged; absent = disabled).

    Implementations MUST scope lookups by organization in the query itself —
    the org in the key is defense in depth, not the only control (threat T5).
    Semantic caching is intentionally not part of this contract; it stays
    disabled unless an approved evaluation supports it (master plan §12.3).
    """

    async def lookup(self, *, organization_id: str, cache_key: str) -> CachedAnswer | None: ...

    async def store(
        self,
        *,
        organization_id: str,
        cache_key: str,
        dataset_version_id: str,
        dataset_sha256: str,
        question_sha256: str,
        config_signature: str,
        answer: dict[str, Any],
        verification: dict[str, Any] | None,
    ) -> None: ...

    async def record_hit(self, *, organization_id: str, cache_key: str) -> None: ...

    async def invalidate(self, *, organization_id: str, cache_key: str) -> None: ...


# ------------------------------------------------------------------ persistence


@dataclass(frozen=True, slots=True)
class RunView:
    run_id: str
    organization_id: str
    dataset_version_id: str
    question: str
    status: str
    cancel_requested: bool


@dataclass(frozen=True, slots=True)
class DatasetView:
    version_id: str
    object_key: str
    content_sha256: str | None
    media_type: str
    filename: str
    profile: list[ColumnView]
    # Row count from the storage-layer profiler; None on paths that don't
    # populate it (see ColumnView.distinct_count). Used only by the host-side
    # anti-fabrication guard, never sent to a model.
    row_count: int | None = None


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    kind: str  # plan | code | execute | repair | verify
    sequence_no: int
    payload: dict[str, Any]
    model_provider: str | None = None
    model_id: str | None = None
    exit_class: str | None = None
    failure_category: str | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None
    source_sha256: str | None = None


class AgentPersistence(Protocol):
    """Everything the graph needs to read inputs, record evidence, checkpoint,
    and finalize — all injected, so the graph has no infrastructure imports."""

    async def load_run(self, run_id: str) -> RunView | None: ...

    async def load_dataset(self, version_id: str) -> DatasetView | None: ...

    async def load_dataset_bytes(self, object_key: str) -> bytes: ...

    async def is_cancel_requested(self, run_id: str) -> bool: ...

    async def emit_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None: ...

    async def append_attempt(self, run_id: str, org_id: str, attempt: AttemptRecord) -> None: ...

    async def save_checkpoint(self, run_id: str, node: str, state_json: str) -> None: ...

    async def load_checkpoint(self, run_id: str) -> tuple[str, str] | None: ...

    async def transition(
        self,
        run_id: str,
        *,
        expected: str,
        target: str,
        detail: str | None = None,
        failure_category: str | None = None,
    ) -> bool: ...

    async def set_result(
        self, run_id: str, *, answer: dict[str, Any] | None, verification: dict[str, Any] | None
    ) -> None: ...
