"""In-memory fakes for testing the agent graph without a database.

`InMemoryPersistence` implements the agent's `AgentPersistence` protocol over
plain dicts, so the whole graph — claim, checkpoint, resume, review, terminal —
can be driven deterministically in unit tests. `exec_result` builds an
`ExecutionResult` so a `FakeExecutor` handler can script what "running the code"
returns without any Docker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crucible.agent import AnalysisPlan, ColumnView, DatasetView, FakeModel, ModelUsage, RunView
from crucible.execution import ExecutionLimits, ExecutionResult, ExitClass, ResourceUsage

_NUMERIC = ("int", "float", "uint", "decimal")


class RegressedFakeModel(FakeModel):
    """A deliberately regressed planner: it swaps a plan's target column for a
    different column of the same type, so computed answers come out wrong. Used
    to prove the evaluation harness catches an injected regression."""

    async def plan(
        self, *, question: str, profile: list[ColumnView]
    ) -> tuple[AnalysisPlan, ModelUsage]:
        plan, usage = await super().plan(question=question, profile=profile)
        target = plan.target_column
        if target is None:
            return plan, usage
        is_num = any(c.name == target and c.dtype.lower().startswith(_NUMERIC) for c in profile)
        pool = [
            c.name
            for c in profile
            if c.name != target and (c.dtype.lower().startswith(_NUMERIC) == is_num)
        ]
        if not pool:
            return plan, usage
        wrong = pool[0]
        refs = [wrong if r == target else r for r in plan.referenced_columns]
        new_step = plan.steps[0].model_copy(update={"target_column": wrong, "referenced_columns": refs})
        return plan.model_copy(update={"steps": [new_step]}), usage


@dataclass
class _Run:
    run_id: str
    organization_id: str
    dataset_version_id: str
    question: str
    status: str = "queued"
    cancel_requested: bool = False


@dataclass
class InMemoryPersistence:
    runs: dict[str, _Run] = field(default_factory=dict)
    datasets: dict[str, DatasetView] = field(default_factory=dict)
    blobs: dict[str, bytes] = field(default_factory=dict)
    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    attempts: list[Any] = field(default_factory=list)
    checkpoints: dict[str, tuple[str, str]] = field(default_factory=dict)
    results: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------- test helpers
    def add_run(
        self,
        run_id: str,
        *,
        question: str,
        profile: list[ColumnView],
        content: bytes = b"region,amount\nnorth,10\nsouth,20\n",
        org: str = "org-1",
        version_id: str = "ver-1",
    ) -> str:
        self.runs[run_id] = _Run(run_id, org, version_id, question)
        key = f"org/{org}/datasets/d/versions/{version_id}.csv"
        self.datasets[version_id] = DatasetView(
            version_id=version_id,
            object_key=key,
            content_sha256="sha-" + version_id,
            media_type="text/csv",
            filename=f"{version_id}.csv",
            profile=profile,
        )
        self.blobs[key] = content
        return run_id

    def status_of(self, run_id: str) -> str:
        return self.runs[run_id].status

    def event_nodes(self, run_id: str) -> list[str]:
        return [p.get("node") for rid, t, p in self.events if rid == run_id and "node" in p]

    def terminal_event(self, run_id: str) -> dict[str, Any] | None:
        for rid, t, p in reversed(self.events):
            if rid == run_id and t == "terminal":
                return p
        return None

    # ------------------------------------------------------ AgentPersistence API
    async def load_run(self, run_id: str) -> RunView | None:
        r = self.runs.get(run_id)
        if r is None:
            return None
        return RunView(
            r.run_id,
            r.organization_id,
            r.dataset_version_id,
            r.question,
            r.status,
            r.cancel_requested,
        )

    async def load_dataset(self, version_id: str) -> DatasetView | None:
        return self.datasets.get(version_id)

    async def load_dataset_bytes(self, object_key: str) -> bytes:
        return self.blobs[object_key]

    async def is_cancel_requested(self, run_id: str) -> bool:
        return self.runs[run_id].cancel_requested

    async def emit_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((run_id, event_type, payload))

    async def append_attempt(self, run_id: str, org_id: str, attempt: Any) -> None:
        self.attempts.append(attempt)

    async def save_checkpoint(self, run_id: str, node: str, state_json: str) -> None:
        self.checkpoints[run_id] = (node, state_json)

    async def load_checkpoint(self, run_id: str) -> tuple[str, str] | None:
        return self.checkpoints.get(run_id)

    async def transition(
        self,
        run_id: str,
        *,
        expected: str,
        target: str,
        detail: str | None = None,
        failure_category: str | None = None,
    ) -> bool:
        r = self.runs[run_id]
        if r.status != expected:
            return False
        r.status = target
        return True

    async def set_result(
        self, run_id: str, *, answer: dict[str, Any] | None, verification: dict[str, Any] | None
    ) -> None:
        self.results[run_id] = (answer, verification)


def exec_result(
    *,
    exit_class: ExitClass = ExitClass.OK,
    value: object = None,
    columns_used: list[str] | None = None,
    ambiguous: bool = False,
    stderr: str = "",
) -> ExecutionResult:
    result: dict[str, object] | None
    if exit_class is ExitClass.OK:
        result = {"value": value}
        if columns_used is not None:
            result["columns_used"] = columns_used
        if ambiguous:
            result["ambiguous"] = True
    else:
        result = None
    return ExecutionResult(
        exit_class=exit_class,
        image_ref="fake-image",
        limits=ExecutionLimits(),
        usage=ResourceUsage(wall_ms=5, program_exit_code=0 if exit_class is ExitClass.OK else 1),
        result=result,
        stderr=stderr,
        error_detail=None if exit_class is ExitClass.OK else stderr or exit_class.value,
    )
