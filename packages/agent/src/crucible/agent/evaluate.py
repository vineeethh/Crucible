"""Run the agent graph to completion for offline evaluation.

The evaluation plane runs the *same* agent graph as serving, but decoupled from
the durable run store: it uses an in-memory persistence and returns the terminal
state plus the recorded attempts and latency. Reusing the real graph is
deliberate — the eval measures the behavior we actually ship, not a reimplementation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from crucible.agent.graph import GraphRunner
from crucible.agent.nodes import AgentContext
from crucible.agent.ports import (
    AgentPersistence,
    AnswerCache,
    AttemptRecord,
    DatasetView,
    ModelGateway,
    RunView,
)
from crucible.agent.state import AgentState, Node
from crucible.execution import ExecutionLimits, Executor


@dataclass
class EphemeralPersistence(AgentPersistence):
    """In-memory AgentPersistence for offline evaluation. Transitions always
    succeed (there is no durable run to guard), and everything is captured so the
    evaluator can inspect attempts and events."""

    attempts: list[AttemptRecord] = field(default_factory=list)
    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    result: tuple[dict[str, Any] | None, dict[str, Any] | None] | None = None
    _run: RunView | None = None
    _dataset: DatasetView | None = None
    _bytes: bytes = b""

    async def load_run(self, run_id: str) -> RunView | None:
        return self._run

    async def load_dataset(self, version_id: str) -> DatasetView | None:
        return self._dataset

    async def load_dataset_bytes(self, object_key: str) -> bytes:
        return self._bytes

    async def is_cancel_requested(self, run_id: str) -> bool:
        return False

    async def emit_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((run_id, event_type, payload))

    async def append_attempt(self, run_id: str, org_id: str, attempt: AttemptRecord) -> None:
        self.attempts.append(attempt)

    async def save_checkpoint(self, run_id: str, node: str, state_json: str) -> None:
        return None

    async def load_checkpoint(self, run_id: str) -> tuple[str, str] | None:
        return None

    async def transition(
        self,
        run_id: str,
        *,
        expected: str,
        target: str,
        detail: str | None = None,
        failure_category: str | None = None,
    ) -> bool:
        return True

    async def set_result(
        self, run_id: str, *, answer: dict[str, Any] | None, verification: dict[str, Any] | None
    ) -> None:
        self.result = (answer, verification)


@dataclass(slots=True)
class EvalTrace:
    state: AgentState
    attempts: list[AttemptRecord]
    events: list[tuple[str, str, dict[str, Any]]]
    latency_ms: int


async def run_to_completion(
    *,
    model: ModelGateway,
    executor: Executor,
    limits: ExecutionLimits,
    question: str,
    dataset: DatasetView,
    dataset_bytes: bytes,
    cache: AnswerCache | None = None,
) -> EvalTrace:
    # `cache` defaults to None in evaluation: cached replays would corrupt the
    # latency/cost measurements a policy report depends on. Cache-behavior
    # tests inject an in-memory implementation deliberately.
    persistence = EphemeralPersistence(_dataset=dataset, _bytes=dataset_bytes)
    ctx = AgentContext(
        persistence=persistence,
        model=model,
        executor=executor,
        dataset=dataset,
        dataset_bytes=dataset_bytes,
        limits=limits,
        cache=cache,
    )
    state = AgentState(
        run_id=f"eval-{uuid.uuid4().hex[:8]}",
        organization_id="eval",
        dataset_version_id=dataset.version_id,
        question=question,
    )
    runner = GraphRunner(ctx)
    start = time.monotonic()
    await runner.run(state, start=Node.VALIDATE)
    latency_ms = int((time.monotonic() - start) * 1000)
    return EvalTrace(
        state=state, attempts=persistence.attempts, events=persistence.events, latency_ms=latency_ms
    )
