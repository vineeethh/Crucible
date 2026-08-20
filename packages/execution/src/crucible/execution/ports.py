"""The Executor port.

The worker/agent (Phase 4) depends on this interface, never on a concrete
backend. Every backend is deny-by-default and constructs its own fixed sandbox
configuration from the request — the request cannot widen it.
"""

from __future__ import annotations

from typing import Protocol

from crucible.execution.protocol import ExecutionRequest, ExecutionResult


class Executor(Protocol):
    @property
    def backend(self) -> str: ...

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run one attempt to completion. Must not raise for a program that
        merely fails, loops, or exhausts a resource — those are returned as a
        non-OK ExecutionResult. It may raise SandboxError only when the executor
        itself cannot operate."""
        ...

    async def healthcheck(self) -> bool:
        """True when the backend is reachable and ready."""
        ...
