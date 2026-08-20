"""The fixed execution protocol (master plan §9.4).

The control plane (worker) sends a *fixed* request: run/attempt IDs, program
source and its hash, one dataset input, resource limits, an allowed result
contract, and trace context. The sandbox returns an exit class, truncated
stdout/stderr, resource usage, a validated structured result, and artifact
hashes.

Nothing here is model-controlled beyond the program source and the dataset
bytes. There is no field for an image name, a mount, a network flag, a package,
or an environment variable — a hostile program cannot ask for capabilities it
was not given, because the schema has nowhere to put the request.

These are pure frozen dataclasses: the package imports only the domain layer and
the standard library (the Docker SDK is an optional, lazily imported backend).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

from crucible.domain import FailureCategory

# Bytes-per-unit helpers keep the limit definitions readable.
_MiB = 1024 * 1024
_KiB = 1024


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """Every limit is deliberately set; nothing defaults to "unlimited"
    (Docker's own docs warn that containers have no resource constraints by
    default — master plan §9.3)."""

    wall_seconds: float = 20.0
    cpu_seconds: int = 15  # RLIMIT_CPU inside the sandbox (belt for wall clock)
    memory_bytes: int = 256 * _MiB
    pids: int = 128
    cpus: float = 1.0
    output_bytes: int = 8 * _MiB  # total size collected from the results dir
    file_bytes: int = 8 * _MiB  # RLIMIT_FSIZE: largest single file the program may write
    stdout_bytes: int = 64 * _KiB  # captured stdout/stderr are truncated to this
    result_bytes: int = 2 * _MiB  # the structured result JSON must be smaller than this

    def __post_init__(self) -> None:
        for name in (
            "wall_seconds",
            "cpu_seconds",
            "memory_bytes",
            "pids",
            "cpus",
            "output_bytes",
            "file_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"execution limit {name!r} must be positive")


@dataclass(frozen=True, slots=True)
class DatasetInput:
    """The single read-only dataset the program may read.

    `filename` is sanitized to a safe basename before it reaches the sandbox;
    `content` is the bytes to expose (local Docker path). A microVM backend uses
    a short-lived storage grant instead and leaves `content` None.
    """

    filename: str
    media_type: str
    sha256: str
    content: bytes | None = None

    @property
    def safe_name(self) -> str:
        """A basename with no path separators, traversal, or surprising chars."""
        base = self.filename.replace("\\", "/").rsplit("/", 1)[-1]
        cleaned = "".join(c for c in base if c.isalnum() or c in ("-", "_", "."))
        cleaned = cleaned.lstrip(".") or "dataset"
        if "." not in cleaned:
            cleaned += ".bin"
        return cleaned[:128]


@dataclass(frozen=True, slots=True)
class ExecutionProgram:
    """Untrusted Python source. The only thing the model contributes."""

    source: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    run_id: str
    attempt_id: str
    program: ExecutionProgram
    dataset: DatasetInput
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    trace_context: dict[str, str] = field(default_factory=dict)


class ExitClass(StrEnum):
    """How a single execution attempt ended. Distinct from the failure
    taxonomy: several exit classes can map to one taxonomy category, and the
    executor never decides whether a result is *correct* — only what happened."""

    OK = "ok"
    RUNTIME_ERROR = "runtime_error"  # program raised / non-zero exit
    TIMEOUT = "timeout"  # wall-clock budget exceeded
    OOM = "oom"  # memory limit hit (cgroup OOM kill)
    RESOURCE_KILLED = "resource_killed"  # killed by a resource signal (fsize, pids, cpu)
    RESULT_MISSING = "result_missing"  # ran cleanly but wrote no result
    RESULT_INVALID = "result_invalid"  # result present but not valid/too large
    POLICY_VIOLATION = "policy_violation"  # sandbox refused the request up front
    STARTUP_ERROR = "startup_error"  # the sandbox/harness itself failed to start
    INTERNAL = "internal"  # executor-side fault, not attributable to the program


_TAXONOMY: dict[ExitClass, FailureCategory | None] = {
    ExitClass.OK: None,
    ExitClass.RUNTIME_ERROR: FailureCategory.CODE_RUNTIME_ERROR,
    ExitClass.TIMEOUT: FailureCategory.SANDBOX_TIMEOUT,
    ExitClass.OOM: FailureCategory.SANDBOX_RESOURCE_LIMIT,
    ExitClass.RESOURCE_KILLED: FailureCategory.SANDBOX_RESOURCE_LIMIT,
    ExitClass.RESULT_MISSING: FailureCategory.RESULT_SERIALIZATION_ERROR,
    ExitClass.RESULT_INVALID: FailureCategory.RESULT_SERIALIZATION_ERROR,
    ExitClass.POLICY_VIOLATION: FailureCategory.TOOL_POLICY_DENIED,
    # STARTUP/INTERNAL are operational faults: not the program's fault, so they
    # carry no taxonomy category and must not be recorded as a model failure.
    ExitClass.STARTUP_ERROR: None,
    ExitClass.INTERNAL: None,
}

# Exit classes that mean "the sandbox contained something", used by tests and
# dashboards to distinguish contained-hostile-behavior from ordinary errors.
CONTAINMENT_EXITS: frozenset[ExitClass] = frozenset(
    {ExitClass.TIMEOUT, ExitClass.OOM, ExitClass.RESOURCE_KILLED, ExitClass.POLICY_VIOLATION}
)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    name: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    wall_ms: int
    program_exit_code: int | None = None
    oom_killed: bool = False
    wall_clock_killed: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    exit_class: ExitClass
    image_ref: str
    limits: ExecutionLimits
    usage: ResourceUsage
    result: dict[str, object] | None = None
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    artifacts: tuple[ArtifactRef, ...] = ()
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_class is ExitClass.OK and self.result is not None

    @property
    def contained(self) -> bool:
        return self.exit_class in CONTAINMENT_EXITS

    @property
    def failure_category(self) -> FailureCategory | None:
        return _TAXONOMY[self.exit_class]

    def span_attributes(self) -> dict[str, object]:
        """Flat attributes for a `sandbox.execute` trace span (P6 attaches these
        to the OTel span; here they travel with the result)."""
        return {
            "sandbox.exit_class": self.exit_class.value,
            "sandbox.image": self.image_ref,
            "sandbox.wall_ms": self.usage.wall_ms,
            "sandbox.oom_killed": self.usage.oom_killed,
            "sandbox.wall_clock_killed": self.usage.wall_clock_killed,
            "sandbox.program_exit_code": self.usage.program_exit_code,
            "sandbox.limit_memory_bytes": self.limits.memory_bytes,
            "sandbox.limit_wall_seconds": self.limits.wall_seconds,
            "sandbox.limit_pids": self.limits.pids,
            "sandbox.artifact_count": len(self.artifacts),
            "sandbox.output_truncated": self.output_truncated,
        }
