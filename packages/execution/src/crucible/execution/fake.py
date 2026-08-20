"""Deterministic in-memory executor for tests and the Phase 4 workflow seam.

The fake NEVER executes the program source. It reads a directive from the
program (a `# fake: <exit_class>` comment, or a JSON body after `# fake-result:`)
and returns the corresponding ExecutionResult. This lets the agent's graph
branches — success, runtime error, timeout, resource kill, missing result — be
tested cheaply and deterministically, with no Docker and no untrusted execution.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from crucible.execution.protocol import (
    ExecutionLimits,
    ExecutionRequest,
    ExecutionResult,
    ExitClass,
    ResourceUsage,
)

FAKE_IMAGE = "fake-executor:deterministic"

_DIRECTIVE = re.compile(r"^#\s*fake:\s*(?P<exit>[a-z_]+)\s*$", re.MULTILINE)
_RESULT = re.compile(r"^#\s*fake-result:\s*(?P<json>.+)$", re.MULTILINE)


class FakeExecutor:
    """`backend == "fake"`. Optionally takes a handler for full control; by
    default it interprets directives embedded in the program source."""

    def __init__(
        self, handler: Callable[[ExecutionRequest], ExecutionResult] | None = None
    ) -> None:
        self._handler = handler

    @property
    def backend(self) -> str:
        return "fake"

    async def healthcheck(self) -> bool:
        return True

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if self._handler is not None:
            return self._handler(request)
        return self._from_directives(request)

    @staticmethod
    def _from_directives(request: ExecutionRequest) -> ExecutionResult:
        source = request.program.source
        exit_match = _DIRECTIVE.search(source)
        exit_class = ExitClass(exit_match.group("exit")) if exit_match else ExitClass.OK

        result: dict[str, object] | None = None
        if exit_class is ExitClass.OK:
            body = _RESULT.search(source)
            result = json.loads(body.group("json")) if body else {"value": None}

        return ExecutionResult(
            exit_class=exit_class,
            image_ref=FAKE_IMAGE,
            limits=request.limits,
            usage=ResourceUsage(
                wall_ms=1,
                program_exit_code=0 if exit_class is ExitClass.OK else 1,
                oom_killed=exit_class is ExitClass.OOM,
                wall_clock_killed=exit_class is ExitClass.TIMEOUT,
            ),
            result=result,
            stdout="",
            stderr="" if exit_class is ExitClass.OK else f"fake {exit_class.value}",
            error_detail=None if exit_class is ExitClass.OK else f"fake {exit_class.value}",
        )


def ok_result(value: object, *, limits: ExecutionLimits | None = None) -> ExecutionResult:
    """Convenience for handlers that just want a successful result."""
    return ExecutionResult(
        exit_class=ExitClass.OK,
        image_ref=FAKE_IMAGE,
        limits=limits or ExecutionLimits(),
        usage=ResourceUsage(wall_ms=1, program_exit_code=0),
        result={"value": value},
    )
