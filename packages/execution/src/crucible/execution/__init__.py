"""Crucible constrained execution.

Boundary rule (import-linter): imports the domain layer and the standard
library only; the Docker SDK is an optional, lazily imported backend dependency
and never touched by the protocol, fake executor, or parser.
"""

from crucible.execution.docker_runner import DEFAULT_IMAGE, DockerExecutor
from crucible.execution.errors import (
    ExecutorNotConfigured,
    ExecutorUnavailable,
    SandboxError,
)
from crucible.execution.fake import FAKE_IMAGE, FakeExecutor, ok_result
from crucible.execution.microvm import MicroVMExecutor
from crucible.execution.parser import (
    ALLOWED_ARTIFACTS,
    ResultParse,
    collect_results,
    parse_result_bytes,
)
from crucible.execution.policy import Finding, Severity, scan_source
from crucible.execution.ports import Executor
from crucible.execution.protocol import (
    CONTAINMENT_EXITS,
    ArtifactRef,
    DatasetInput,
    ExecutionLimits,
    ExecutionProgram,
    ExecutionRequest,
    ExecutionResult,
    ExitClass,
    ResourceUsage,
)

__all__ = [
    "ALLOWED_ARTIFACTS",
    "CONTAINMENT_EXITS",
    "DEFAULT_IMAGE",
    "FAKE_IMAGE",
    "ArtifactRef",
    "DatasetInput",
    "DockerExecutor",
    "ExecutionLimits",
    "ExecutionProgram",
    "ExecutionRequest",
    "ExecutionResult",
    "Executor",
    "ExecutorNotConfigured",
    "ExecutorUnavailable",
    "ExitClass",
    "FakeExecutor",
    "Finding",
    "MicroVMExecutor",
    "ResourceUsage",
    "ResultParse",
    "SandboxError",
    "Severity",
    "collect_results",
    "ok_result",
    "parse_result_bytes",
    "scan_source",
]
