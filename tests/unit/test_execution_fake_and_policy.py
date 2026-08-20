"""FakeExecutor directives (Phase 4 seam) and the advisory static scanner."""

import asyncio

from crucible.execution import (
    DatasetInput,
    ExecutionProgram,
    ExecutionRequest,
    ExitClass,
    FakeExecutor,
    Severity,
    scan_source,
)


def _request(source: str) -> ExecutionRequest:
    return ExecutionRequest(
        run_id="r",
        attempt_id="1",
        program=ExecutionProgram(source),
        dataset=DatasetInput("d.csv", "text/csv", "x"),
    )


def _run(source: str):
    return asyncio.run(FakeExecutor().execute(_request(source)))


def test_fake_default_is_ok_with_result() -> None:
    result = _run("# fake-result: {\"answer\": 7}\nprint('hi')")
    assert result.exit_class is ExitClass.OK
    assert result.result == {"answer": 7}
    assert result.ok


def test_fake_directive_selects_exit_class() -> None:
    assert _run("# fake: timeout").exit_class is ExitClass.TIMEOUT
    assert _run("# fake: oom").exit_class is ExitClass.OOM
    assert _run("# fake: runtime_error").exit_class is ExitClass.RUNTIME_ERROR
    assert _run("# fake: resource_killed").exit_class is ExitClass.RESOURCE_KILLED


def test_fake_timeout_and_oom_set_usage_flags() -> None:
    assert _run("# fake: timeout").usage.wall_clock_killed
    assert _run("# fake: oom").usage.oom_killed


def test_fake_never_executes_source() -> None:
    """The directive wins even when the source would obviously do harm if run —
    the fake must never execute untrusted code."""
    result = _run("import os\nos.system('rm -rf /')\n# fake: ok")
    assert result.exit_class is ExitClass.OK


def test_fake_handler_override() -> None:
    from crucible.execution import ok_result

    executor = FakeExecutor(handler=lambda req: ok_result({"n": len(req.program.source)}))
    result = asyncio.run(executor.execute(_request("abc")))
    assert result.result == {"value": {"n": 3}}


# --------------------------------------------------------------- static scanner


def test_scan_flags_network_imports() -> None:
    findings = scan_source("import socket\nimport requests\n")
    codes = {f.detail for f in findings}
    assert "socket" in codes
    assert "requests" in codes
    assert all(f.severity is Severity.SUSPICIOUS for f in findings)


def test_scan_flags_dynamic_execution() -> None:
    findings = scan_source("eval('1+1')\nexec('x=1')\n")
    assert {f.detail for f in findings} == {"eval", "exec"}


def test_scan_is_clean_for_benign_analysis() -> None:
    assert scan_source("import polars as pl\nframe = pl.read_csv('x')\n") == []


def test_scan_reports_syntax_error_without_raising() -> None:
    findings = scan_source("def broken(:\n")
    assert findings and findings[0].code == "syntax_error"
