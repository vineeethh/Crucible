"""In-sandbox execution harness (trusted; baked into the runner image).

Runs inside the locked-down container as the entrypoint. It is the *only*
trusted code in the sandbox. It:

  1. reads the untrusted program from /sandbox/program.py (read-only mount),
  2. runs it as a subprocess with additional per-process resource limits and a
     minimal environment (the dataset path and result path, nothing else),
  3. captures and truncates stdout/stderr,
  4. writes an authoritative manifest.json to /results describing what happened.

The host does not trust the program's stdout for the result: it reads
/results/result.json (written by the program) and /results/manifest.json
(written here) directly from the results mount after the container exits. The
untrusted subprocess cannot forge this parent's file writes.

Standard library only — the image has no other trusted dependencies.
"""

from __future__ import annotations

import contextlib
import json
import os
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime

RESULTS_DIR = os.environ.get("CRUCIBLE_RESULTS_DIR", "/results")
PROGRAM_PATH = os.environ.get("CRUCIBLE_PROGRAM_PATH", "/sandbox/program.py")
DATASET_PATH = os.environ.get("CRUCIBLE_DATASET_PATH", "")
RESULT_PATH = os.path.join(RESULTS_DIR, "result.json")
MANIFEST_PATH = os.path.join(RESULTS_DIR, "manifest.json")

# Limits passed by the host as environment (all belt-and-suspenders with the
# container-level cgroup limits, which are the primary control).
CPU_SECONDS = int(os.environ.get("CRUCIBLE_CPU_SECONDS", "15"))
FILE_BYTES = int(os.environ.get("CRUCIBLE_FILE_BYTES", str(8 * 1024 * 1024)))
STDOUT_BYTES = int(os.environ.get("CRUCIBLE_STDOUT_BYTES", str(64 * 1024)))
WALL_SECONDS = float(os.environ.get("CRUCIBLE_WALL_SECONDS", "20"))


def _set_limits() -> None:
    """preexec_fn for the untrusted subprocess (runs in the child, pre-exec)."""
    # CPU seconds: SIGXCPU at soft, SIGKILL shortly after.
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 2))
    # Largest single file the program may write (SIGXFSZ on overflow).
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
    # No core dumps.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)


def _truncate(raw: bytes) -> tuple[str, bool]:
    if len(raw) <= STDOUT_BYTES:
        return raw.decode("utf-8", "replace"), False
    marker = b"\n...[truncated]..."
    return (raw[: STDOUT_BYTES - len(marker)] + marker).decode("utf-8", "replace"), True


def _write_manifest(manifest: dict[str, object]) -> None:
    # Written last, atomically enough for a single reader: temp then replace.
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    os.replace(tmp, MANIFEST_PATH)


def main() -> int:
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()

    if not os.path.isfile(PROGRAM_PATH):
        _write_manifest(
            {
                "schema": 1,
                "harness_error": "program not found",
                "program_exit_code": None,
                "soft_timeout": False,
                "result_present": False,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration_ms": 0,
                "started_at": started_at,
            }
        )
        return 0

    # Minimal environment: the program sees only where to read the dataset and
    # where to write its result. No inherited host variables, no secrets.
    child_env = {
        "CRUCIBLE_DATASET_PATH": DATASET_PATH,
        "CRUCIBLE_RESULT_PATH": RESULT_PATH,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    soft_timeout = False
    try:
        # Running the untrusted program is this harness's entire purpose, and it
        # is already fully contained: list-form args (no shell), a fixed
        # PROGRAM_PATH, a curated env (child_env), CPU/mem/file rlimits via
        # preexec_fn, a wall-clock timeout, and -I/-B interpreter isolation —
        # inside a non-root, network-disabled, read-only container. The
        # nosemgrep directive is on the call line (where semgrep anchors it).
        argv = [sys.executable, "-I", "-B", PROGRAM_PATH]
        completed = subprocess.run(
            argv,  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            cwd=RESULTS_DIR,
            env=child_env,
            capture_output=True,
            timeout=WALL_SECONDS,
            preexec_fn=_set_limits,
            check=False,
        )
        exit_code: int | None = completed.returncode
        out, err = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        soft_timeout = True
        exit_code = None
        out = exc.stdout or b""
        err = exc.stderr or b""

    stdout, out_trunc = _truncate(out or b"")
    stderr, err_trunc = _truncate(err or b"")

    result_present = os.path.isfile(RESULT_PATH)
    result_bytes = os.path.getsize(RESULT_PATH) if result_present else 0

    # The untrusted program runs under umask 0o077, so result.json and any
    # artifacts are mode 0600 owned by this container UID. The host reads only
    # the top-level files back (subdirectories are not part of the contract —
    # see parser.collect_results) after the container exits, and on a
    # native-Linux host runs as a different UID — so make those files readable.
    # This harness owns them (same UID). Host read-back only: the container is
    # ephemeral and destroyed after the run, so these modes carry no security
    # weight (containment is enforced by the container). Regular files only, so
    # a program-created symlink is never chmod-ed through to its target.
    for entry in os.scandir(RESULTS_DIR):
        if entry.is_file(follow_symlinks=False):
            with contextlib.suppress(OSError):
                os.chmod(entry.path, 0o644)

    _write_manifest(
        {
            "schema": 1,
            "harness_error": None,
            "program_exit_code": exit_code,
            "soft_timeout": soft_timeout,
            "result_present": result_present,
            "result_bytes": result_bytes,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": out_trunc,
            "stderr_truncated": err_trunc,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "started_at": started_at,
        }
    )
    # The harness itself always succeeds; the program's outcome is in the
    # manifest. A non-zero harness exit would be indistinguishable from a
    # sandbox startup fault.
    return 0


if __name__ == "__main__":
    sys.exit(main())
