"""Host-side result parsing: the sandbox output is untrusted until validated."""

import json
import os
from pathlib import Path

import pytest

from crucible.execution import ExecutionLimits, collect_results, parse_result_bytes
from crucible.execution.parser import RESULT_FILENAME


def _limits(**kw: int) -> ExecutionLimits:
    return ExecutionLimits(**kw)


def test_valid_result_object_parses() -> None:
    result, reason = parse_result_bytes(b'{"answer": 42}', _limits())
    assert result == {"answer": 42}
    assert reason is None


def test_non_object_result_is_rejected() -> None:
    for body in (b"42", b'"a string"', b"[1, 2, 3]"):
        result, reason = parse_result_bytes(body, _limits())
        assert result is None
        assert reason is not None


def test_invalid_json_is_rejected() -> None:
    result, reason = parse_result_bytes(b"{not json", _limits())
    assert result is None
    assert "JSON" in (reason or "")


def test_oversize_result_is_rejected() -> None:
    big = json.dumps({"x": "a" * 5000}).encode()
    result, reason = parse_result_bytes(big, _limits(result_bytes=1024))
    assert result is None
    assert "exceeds" in (reason or "")


def test_collect_reads_result_and_artifacts(tmp_path: Path) -> None:
    (tmp_path / RESULT_FILENAME).write_text('{"rows": 3}')
    (tmp_path / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
    (tmp_path / "table.csv").write_text("a,b\n1,2\n")

    parse = collect_results(tmp_path, _limits())
    assert parse.ok
    assert parse.result == {"rows": 3}
    names = {a.name for a in parse.artifacts}
    assert names == {"chart.png", "table.csv"}
    png = next(a for a in parse.artifacts if a.name == "chart.png")
    assert png.media_type == "image/png"
    assert png.sha256  # hashed


def test_disallowed_artifact_type_is_dropped(tmp_path: Path) -> None:
    """A program that writes an executable or archive gets it rejected, and the
    whole result is flagged rather than silently published."""
    (tmp_path / RESULT_FILENAME).write_text('{"ok": true}')
    (tmp_path / "payload.sh").write_text("#!/bin/sh\nrm -rf /\n")
    (tmp_path / "evil.exe").write_bytes(b"MZ")

    parse = collect_results(tmp_path, _limits())
    assert not parse.ok
    assert "not allowed" in (parse.reason or "")
    assert all(a.name not in ("payload.sh", "evil.exe") for a in parse.artifacts)


def test_total_output_cap_is_enforced(tmp_path: Path) -> None:
    (tmp_path / RESULT_FILENAME).write_text('{"ok": true}')
    (tmp_path / "big.csv").write_bytes(b"x" * 4096)
    parse = collect_results(tmp_path, _limits(output_bytes=1024))
    assert not parse.ok
    assert "exceed" in (parse.reason or "")


def test_missing_result_is_reported(tmp_path: Path) -> None:
    (tmp_path / "table.csv").write_text("a\n1\n")
    parse = collect_results(tmp_path, _limits())
    assert parse.result is None
    assert "no result" in (parse.reason or "").lower()


def test_no_results_directory(tmp_path: Path) -> None:
    parse = collect_results(tmp_path / "does-not-exist", _limits())
    assert not parse.ok
    assert parse.result is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_symlink_artifact_is_rejected(tmp_path: Path) -> None:
    """A symlink is how a program tries to exfiltrate a host path through the
    results directory; it must never be followed or collected."""
    (tmp_path / RESULT_FILENAME).write_text('{"ok": true}')
    secret = tmp_path / "secret_target"
    secret.write_text("host secret")
    (tmp_path / "leak.csv").symlink_to(secret)

    parse = collect_results(tmp_path, _limits())
    assert not parse.ok
    assert "symlink" in (parse.reason or "").lower()
    assert all(a.name != "leak.csv" for a in parse.artifacts)
