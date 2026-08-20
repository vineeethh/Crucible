"""Managed microVM executor — the production contract (master plan §9.2, ADR-003).

Production and staging run untrusted code in a managed microVM sandbox (an
E2B-class provider), never in Docker. This module defines the adapter contract
so the seam exists and the worker can select it; the provider SDK is wired in
when a real environment is provisioned (Phase 9/10). Until then it is
deny-by-default: without credentials it raises ExecutorNotConfigured rather than
falling back to a weaker boundary.

The provider MUST satisfy the same fixed policy the Docker backend applies:

  - a fixed, pinned template image chosen by us, never by the model;
  - network egress disabled by default (no DNS, no metadata endpoint);
  - a fresh microVM per attempt, destroyed after artifact collection;
  - CPU / memory / wall-clock / output caps enforced by the provider;
  - the dataset supplied by a short-lived, run-scoped storage grant, never a
    long-lived credential mounted into the guest;
  - provider control-plane credentials held only by this host adapter and never
    exposed inside the guest.

The request/response mapping is identical to the Docker backend: the same
ExecutionRequest goes in, the same ExecutionResult (exit class, validated
result, artifact hashes, resource usage) comes out, so the worker is agnostic.
"""

from __future__ import annotations

from crucible.execution.errors import ExecutorNotConfigured
from crucible.execution.protocol import ExecutionRequest, ExecutionResult


class MicroVMExecutor:
    """`backend == "microvm"`. Contract-only until a provider is provisioned."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        template_id: str | None = None,
        provider: str = "e2b",
    ) -> None:
        self._api_key = api_key
        self._template_id = template_id
        self._provider = provider

    @property
    def backend(self) -> str:
        return "microvm"

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._template_id)

    async def healthcheck(self) -> bool:
        return self.configured

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if not self.configured:
            raise ExecutorNotConfigured(
                "the microVM backend requires api_key and template_id; no weaker "
                "fallback is permitted (ADR-003)"
            )
        # Provider integration (Phase 9/10). The intended flow, documented so the
        # contract is unambiguous:
        #   1. create a fresh microVM from the fixed template_id (egress off);
        #   2. upload program + dataset via a run-scoped grant;
        #   3. run the same harness contract; enforce the wall-clock budget;
        #   4. download /results; validate with parser.collect_results;
        #   5. destroy the microVM; return the mapped ExecutionResult.
        raise ExecutorNotConfigured("microVM provider integration is not provisioned yet")
