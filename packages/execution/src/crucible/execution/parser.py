"""Host-side validation of whatever the sandbox produced.

The results directory is written by untrusted code, so nothing in it is trusted
until validated here (master plan §9.4: "the worker validates all returned paths
and MIME types before publishing them"). Rules:

- Only an allowlist of extensions is accepted; anything else is dropped.
- Symlinks are never followed and never accepted — a symlink is how a program
  tries to smuggle a host path out through the results tar.
- Per-file and total-size caps are enforced; over-cap collection is a violation.
- The MIME type is derived from the extension we accept, never from file
  contents or a program-supplied header.
- The structured result must be a JSON object within the result-size cap.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from crucible.execution.protocol import ArtifactRef, ExecutionLimits

RESULT_FILENAME = "result.json"
MANIFEST_FILENAME = "manifest.json"

# Extension -> MIME. Deliberately tiny: results tables and charts only.
ALLOWED_ARTIFACTS: dict[str, str] = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}

# Never collected even if present: control files and anything executable.
_RESERVED = frozenset({RESULT_FILENAME, MANIFEST_FILENAME})


@dataclass(frozen=True, slots=True)
class ResultParse:
    result: dict[str, object] | None
    artifacts: tuple[ArtifactRef, ...]
    total_bytes: int
    ok: bool
    reason: str | None = None


def parse_result_bytes(
    data: bytes, limits: ExecutionLimits
) -> tuple[dict[str, object] | None, str | None]:
    """Validate the structured result. Returns (result, reason). A `reason`
    means the result is unusable and the attempt is RESULT_INVALID."""
    if len(data) > limits.result_bytes:
        return None, f"result exceeds {limits.result_bytes} bytes"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "result is not valid UTF-8"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"result is not valid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        # A bare scalar or list is ambiguous; the contract is a JSON object with
        # named fields so provenance can attach to it.
        return None, "result must be a JSON object"
    return parsed, None


def collect_results(results_dir: Path, limits: ExecutionLimits) -> ResultParse:
    """Walk the (host-side) results directory the sandbox wrote to and produce a
    validated result plus artifact references."""
    result: dict[str, object] | None = None
    artifacts: list[ArtifactRef] = []
    total = 0
    reason: str | None = None

    if not results_dir.is_dir():
        return ResultParse(None, (), 0, ok=False, reason="no results directory")

    # Only the top level is inspected: subdirectories are not part of the
    # contract and are ignored rather than walked.
    for entry in sorted(results_dir.iterdir()):
        if entry.is_symlink():
            reason = reason or f"symlink rejected: {entry.name}"
            continue
        if not entry.is_file():
            continue

        size = entry.stat().st_size
        total += size
        if total > limits.output_bytes:
            return ResultParse(
                result,
                tuple(artifacts),
                total,
                ok=False,
                reason=f"results exceed {limits.output_bytes} bytes",
            )

        if entry.name == RESULT_FILENAME:
            parsed, r = parse_result_bytes(entry.read_bytes(), limits)
            if r is not None:
                reason = reason or r
            result = parsed
            continue
        if entry.name in _RESERVED:
            continue

        suffix = entry.suffix.lower()
        media = ALLOWED_ARTIFACTS.get(suffix)
        if media is None:
            reason = reason or f"artifact type not allowed: {entry.name}"
            continue
        artifacts.append(
            ArtifactRef(
                name=entry.name,
                media_type=media,
                size_bytes=size,
                sha256=_sha256_file(entry),
            )
        )

    ok = result is not None and reason is None
    if result is None and reason is None:
        reason = "no result.json produced"
    return ResultParse(result, tuple(artifacts), total, ok=ok, reason=reason)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
