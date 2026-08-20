"""Execution protocol: limits are always set, exit classes map to the taxonomy,
and the request schema cannot carry sandbox-configuration fields."""

import dataclasses

import pytest

from crucible.domain import FailureCategory
from crucible.execution import (
    CONTAINMENT_EXITS,
    DatasetInput,
    ExecutionLimits,
    ExecutionProgram,
    ExecutionRequest,
    ExecutionResult,
    ExitClass,
    ResourceUsage,
)


def test_default_limits_are_all_positive() -> None:
    limits = ExecutionLimits()
    assert limits.wall_seconds > 0
    assert limits.memory_bytes > 0
    assert limits.pids > 0
    assert limits.output_bytes > 0


@pytest.mark.parametrize("field", ["wall_seconds", "memory_bytes", "pids", "cpus", "file_bytes"])
def test_nonpositive_limit_is_rejected(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        ExecutionLimits(**{field: 0})


def test_request_schema_has_no_sandbox_config_fields() -> None:
    """The whole safety argument rests on the model being unable to ask for
    capabilities. The request must expose no image, mount, network, env, or
    package field — only the program, the dataset, and (host-set) limits."""
    fields = {f.name for f in dataclasses.fields(ExecutionRequest)}
    assert fields == {"run_id", "attempt_id", "program", "dataset", "limits", "trace_context"}
    forbidden = {
        "image",
        "network",
        "mounts",
        "volumes",
        "env",
        "environment",
        "packages",
        "privileged",
        "capabilities",
        "command",
    }
    assert not (fields & forbidden)


def test_dataset_safe_name_strips_traversal() -> None:
    # A traversal path is reduced to its basename, then sanitized; no separators
    # survive, so the name can never escape the sandbox input directory.
    assert DatasetInput("../../etc/passwd", "text/csv", "x").safe_name == "passwd.bin"
    assert DatasetInput("..\\..\\windows\\system32\\a.csv", "text/csv", "x").safe_name == "a.csv"
    assert DatasetInput("data.csv", "text/csv", "x").safe_name == "data.csv"
    assert DatasetInput("weird name!.csv", "text/csv", "x").safe_name == "weirdname.csv"
    assert DatasetInput("", "text/csv", "x").safe_name == "dataset.bin"
    assert "/" not in DatasetInput("a/b/c", "text/csv", "x").safe_name


def test_program_hash_is_content_addressed() -> None:
    a = ExecutionProgram("print(1)")
    b = ExecutionProgram("print(1)")
    c = ExecutionProgram("print(2)")
    assert a.sha256 == b.sha256
    assert a.sha256 != c.sha256


def _result(exit_class: ExitClass) -> ExecutionResult:
    return ExecutionResult(
        exit_class=exit_class,
        image_ref="img",
        limits=ExecutionLimits(),
        usage=ResourceUsage(wall_ms=1),
        result={"value": 1} if exit_class is ExitClass.OK else None,
    )


def test_exit_class_taxonomy_mapping() -> None:
    assert _result(ExitClass.OK).failure_category is None
    assert _result(ExitClass.RUNTIME_ERROR).failure_category is FailureCategory.CODE_RUNTIME_ERROR
    assert _result(ExitClass.TIMEOUT).failure_category is FailureCategory.SANDBOX_TIMEOUT
    assert _result(ExitClass.OOM).failure_category is FailureCategory.SANDBOX_RESOURCE_LIMIT
    assert (
        _result(ExitClass.RESOURCE_KILLED).failure_category
        is FailureCategory.SANDBOX_RESOURCE_LIMIT
    )
    assert (
        _result(ExitClass.POLICY_VIOLATION).failure_category is FailureCategory.TOOL_POLICY_DENIED
    )
    # Operational faults are not attributed to the model.
    assert _result(ExitClass.STARTUP_ERROR).failure_category is None
    assert _result(ExitClass.INTERNAL).failure_category is None


def test_ok_requires_a_result() -> None:
    assert _result(ExitClass.OK).ok
    missing = dataclasses.replace(_result(ExitClass.OK), result=None)
    assert not missing.ok


def test_contained_flags_hostile_containment() -> None:
    assert _result(ExitClass.TIMEOUT).contained
    assert _result(ExitClass.OOM).contained
    assert _result(ExitClass.RESOURCE_KILLED).contained
    assert not _result(ExitClass.OK).contained
    assert not _result(ExitClass.RUNTIME_ERROR).contained
    assert {
        ExitClass.TIMEOUT,
        ExitClass.OOM,
        ExitClass.RESOURCE_KILLED,
        ExitClass.POLICY_VIOLATION,
    } == CONTAINMENT_EXITS


def test_span_attributes_are_flat_and_complete() -> None:
    attrs = _result(ExitClass.OK).span_attributes()
    assert attrs["sandbox.exit_class"] == "ok"
    assert "sandbox.image" in attrs
    assert "sandbox.limit_memory_bytes" in attrs
    assert all(not isinstance(v, (dict, list)) for v in attrs.values())
