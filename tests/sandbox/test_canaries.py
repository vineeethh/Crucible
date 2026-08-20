"""Sandbox containment canaries (master plan §9.5).

Each test runs a real hostile program in the real hardened runner and asserts it
is contained: no network, no host access, no privilege, no resource runaway, no
secret disclosure, and no unsafe output. A program that succeeds in doing any of
these is a Phase 3 failure.

The programs write their observations to the result file with `emit(...)`, so a
*successful* breach would show up as a concrete value we assert against — the
tests fail loudly if containment ever regresses, rather than passing by accident.
"""

from __future__ import annotations

import pytest

from crucible.domain import FailureCategory
from crucible.execution import ExecutionLimits, ExitClass
from tests.sandbox.conftest import RunProgram, requires_sandbox

pytestmark = [pytest.mark.sandbox, requires_sandbox]

# Helper prepended to programs that report an observation.
EMIT = (
    "import json, os, socket, sys\n"
    "def emit(o):\n"
    "    open(os.environ['CRUCIBLE_RESULT_PATH'], 'w').write(json.dumps(o))\n"
)


# --------------------------------------------------------------- the safe path


def test_safe_program_reads_its_dataset_and_returns_a_result(run_program: RunProgram) -> None:
    """Definition of Done: a fixed safe analytical program can read only its
    assigned dataset and return a structured result."""
    source = (
        "import json, os\n"
        "import polars as pl\n"
        "frame = pl.read_csv(os.environ['CRUCIBLE_DATASET_PATH'])\n"
        "result = {'rows': frame.height, 'cols': frame.width, 'total': int(frame['amount'].sum())}\n"
        "open(os.environ['CRUCIBLE_RESULT_PATH'], 'w').write(json.dumps(result))\n"
    )
    result = run_program(source)
    assert result.ok
    assert result.exit_class is ExitClass.OK
    assert result.result == {"rows": 3, "cols": 2, "total": 60}
    assert result.image_ref == "crucible-sandbox-runner:local"


# --------------------------------------------------------------- least privilege


def test_program_runs_as_non_root(run_program: RunProgram) -> None:
    result = run_program(EMIT + "emit({'uid': os.getuid(), 'gid': os.getgid()})\n")
    assert result.ok
    assert result.result == {"uid": 10001, "gid": 10001}


def test_privilege_escalation_is_denied(run_program: RunProgram) -> None:
    """All capabilities are dropped and no-new-privileges is set, so setuid(0)
    cannot succeed."""
    source = EMIT + (
        "try:\n"
        "    os.setuid(0)\n"
        "    emit({'setuid_root': 'SUCCEEDED'})\n"
        "except Exception as e:\n"
        "    emit({'setuid_root': 'blocked', 'error': type(e).__name__})\n"
    )
    result = run_program(source)
    assert result.ok
    assert result.result["setuid_root"] == "blocked"


# ------------------------------------------------------------------- network


def test_outbound_tcp_is_blocked(run_program: RunProgram) -> None:
    source = EMIT + (
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 53))\n"
        "    emit({'tcp': 'REACHABLE'})\n"
        "except Exception as e:\n"
        "    emit({'tcp': 'blocked', 'error': type(e).__name__})\n"
    )
    result = run_program(source)
    assert result.ok
    assert result.result["tcp"] == "blocked"


def test_dns_resolution_is_blocked(run_program: RunProgram) -> None:
    source = EMIT + (
        "try:\n"
        "    ip = socket.gethostbyname('example.com')\n"
        "    emit({'dns': 'RESOLVED', 'ip': ip})\n"
        "except Exception as e:\n"
        "    emit({'dns': 'blocked', 'error': type(e).__name__})\n"
    )
    result = run_program(source)
    assert result.ok
    assert result.result["dns"] == "blocked"


def test_cloud_metadata_endpoint_is_unreachable(run_program: RunProgram) -> None:
    """The classic SSRF/credential-theft target: 169.254.169.254 must not be
    reachable from inside the sandbox."""
    source = EMIT + (
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('169.254.169.254', 80))\n"
        "    emit({'metadata': 'REACHABLE'})\n"
        "except Exception as e:\n"
        "    emit({'metadata': 'blocked', 'error': type(e).__name__})\n"
    )
    result = run_program(source)
    assert result.ok
    assert result.result["metadata"] == "blocked"


# ------------------------------------------------------------------- host access


def test_docker_socket_is_not_present(run_program: RunProgram) -> None:
    """No Docker socket is mounted, so generated code cannot control the daemon
    (the classic container-escape path)."""
    source = EMIT + "emit({'socket': os.path.exists('/var/run/docker.sock')})\n"
    result = run_program(source)
    assert result.ok
    assert result.result == {"socket": False}


def test_root_filesystem_is_read_only(run_program: RunProgram) -> None:
    source = EMIT + (
        "outcomes = {}\n"
        "for path in ('/evil', '/etc/cron.d/x', '/usr/bin/x'):\n"
        "    try:\n"
        "        open(path, 'w').write('x')\n"
        "        outcomes[path] = 'WROTE'\n"
        "    except Exception as e:\n"
        "        outcomes[path] = type(e).__name__\n"
        "emit(outcomes)\n"
    )
    result = run_program(source)
    assert result.ok
    assert all(v != "WROTE" for v in result.result.values())


def test_sandbox_exposes_only_the_assigned_dataset(run_program: RunProgram) -> None:
    """The input mount contains only this run's program and its one dataset —
    no other tenant's files, no host paths."""
    source = EMIT + "emit({'sandbox': sorted(os.listdir('/sandbox'))})\n"
    result = run_program(source)
    assert result.ok
    assert result.result == {"sandbox": ["program.py", "sample.csv"]}


def test_no_host_secrets_in_environment(run_program: RunProgram) -> None:
    """The program's environment holds only the two fixed sandbox paths and a
    minimal PATH/HOME — never a cloud credential, database URL, or API key."""
    source = EMIT + "emit({'env': sorted(os.environ.keys())})\n"
    result = run_program(source)
    assert result.ok
    env_keys = set(result.result["env"])
    # Only the two fixed sandbox paths plus benign runtime/locale defaults; the
    # host's real environment (cloud creds, DB/Redis URLs, provider keys) is not
    # inherited into the child at all (see the harness's minimal child_env).
    benign = {
        "CRUCIBLE_DATASET_PATH",
        "CRUCIBLE_RESULT_PATH",
        "PATH",
        "HOME",
        "PYTHONDONTWRITEBYTECODE",
        "LANG",
        "LC_CTYPE",
        "LC_ALL",
        "PYTHON_VERSION",
        "PYTHON_SHA256",
        "GPG_KEY",
        "HOSTNAME",
    }
    assert env_keys <= benign, f"unexpected env vars leaked into the sandbox: {env_keys - benign}"
    dangerous = {
        k
        for k in env_keys
        if any(
            token in k.upper()
            for token in ("SECRET", "TOKEN", "AWS", "PASSWORD", "DATABASE", "REDIS", "S3_", "KEY")
        )
        and k not in ("GPG_KEY",)  # the base image's package-signing key, not a Crucible secret
    }
    assert dangerous == set()


# ------------------------------------------------------------- resource runaway


def test_memory_bomb_is_contained(run_program: RunProgram) -> None:
    source = (
        "chunks = []\n"
        "while True:\n"
        "    b = bytearray(10 * 1024 * 1024)\n"
        "    for i in range(0, len(b), 4096):\n"
        "        b[i] = 1\n"
        "    chunks.append(b)\n"
    )
    result = run_program(
        source, limits=ExecutionLimits(memory_bytes=64 * 1024 * 1024, wall_seconds=15)
    )
    assert not result.ok
    assert result.result is None
    assert result.failure_category is FailureCategory.SANDBOX_RESOURCE_LIMIT


def test_cpu_spin_is_killed_by_wall_clock(run_program: RunProgram) -> None:
    result = run_program(
        "while True:\n    pass\n", limits=ExecutionLimits(wall_seconds=3, cpu_seconds=2)
    )
    assert not result.ok
    assert result.exit_class in {ExitClass.TIMEOUT, ExitClass.RESOURCE_KILLED}
    assert result.failure_category in {
        FailureCategory.SANDBOX_TIMEOUT,
        FailureCategory.SANDBOX_RESOURCE_LIMIT,
    }


def test_fork_bomb_is_contained(run_program: RunProgram) -> None:
    source = (
        "import os\nwhile True:\n    try:\n        os.fork()\n    except Exception:\n        pass\n"
    )
    result = run_program(source, limits=ExecutionLimits(pids=32, wall_seconds=5, cpu_seconds=4))
    # The invariant: a fork bomb never yields a successful result, and the host
    # survives (this test completing is itself part of the assertion). The exact
    # exit class is genuinely nondeterministic under pid starvation — the pid cap,
    # the wall clock, or harness starvation may win, and starvation can even tear
    # the sandbox down before it writes a manifest. Every one of those is
    # containment; only a successful result would be a breach.
    assert not result.ok
    assert result.result is None
    assert result.exit_class in {
        ExitClass.TIMEOUT,
        ExitClass.RESOURCE_KILLED,
        ExitClass.RUNTIME_ERROR,
        ExitClass.STARTUP_ERROR,  # harness starved of pids before writing a manifest
        ExitClass.INTERNAL,
    }, f"unexpected fork-bomb outcome: {result.exit_class} ({result.error_detail})"


def test_file_size_bomb_is_contained(run_program: RunProgram) -> None:
    """RLIMIT_FSIZE caps the largest file the program can write. Depending on
    timing the kernel either kills with SIGXFSZ or the write returns EFBIG
    ("File too large") which surfaces as a program error — both mean the giant
    file was never written."""
    source = (
        "with open('/results/big.bin', 'wb') as f:\n"
        "    for _ in range(100000):\n"
        "        f.write(b'x' * 10240)\n"
    )
    result = run_program(
        source,
        limits=ExecutionLimits(file_bytes=512 * 1024, output_bytes=1024 * 1024, wall_seconds=10),
    )
    assert not result.ok
    assert result.exit_class in {
        ExitClass.RESOURCE_KILLED,
        ExitClass.RESULT_INVALID,
        ExitClass.RUNTIME_ERROR,
        ExitClass.TIMEOUT,
    }


def test_output_bomb_is_rejected_by_total_cap(run_program: RunProgram) -> None:
    """Many small files that individually pass the per-file cap but together
    exceed the total output cap are rejected, not published."""
    source = EMIT + (
        "emit({'ok': True})\n"
        "for n in range(30):\n"
        "    with open(f'/results/part_{n}.csv', 'wb') as f:\n"
        "        f.write(b'a' * (400 * 1024))\n"
    )
    result = run_program(source, limits=ExecutionLimits(output_bytes=2 * 1024 * 1024))
    assert not result.ok
    assert result.exit_class is ExitClass.RESULT_INVALID


# ------------------------------------------------------------- result validation


def test_missing_result_is_reported(run_program: RunProgram) -> None:
    result = run_program("x = 1 + 1  # writes no result\n")
    assert not result.ok
    assert result.exit_class is ExitClass.RESULT_MISSING
    assert result.failure_category is FailureCategory.RESULT_SERIALIZATION_ERROR


def test_non_object_result_is_invalid(run_program: RunProgram) -> None:
    source = EMIT + "emit([1, 2, 3])  # a list, not an object\n"
    result = run_program(source)
    assert not result.ok
    assert result.exit_class is ExitClass.RESULT_INVALID


def test_program_crash_is_a_runtime_error(run_program: RunProgram) -> None:
    result = run_program("raise ValueError('boom')\n")
    assert not result.ok
    assert result.exit_class is ExitClass.RUNTIME_ERROR
    assert result.failure_category is FailureCategory.CODE_RUNTIME_ERROR
    assert "boom" in result.stderr


def test_malicious_artifact_is_dropped(run_program: RunProgram) -> None:
    """A valid result accompanied by an executable artifact: the executable is
    never collected, and the presence of a disallowed type flags the result."""
    source = EMIT + (
        "emit({'answer': 1})\n"
        "open('/results/evil.exe', 'wb').write(b'MZmalware')\n"
        "open('/results/script.sh', 'w').write('#!/bin/sh\\nrm -rf /\\n')\n"
    )
    result = run_program(source)
    assert not result.ok  # a disallowed artifact flags the whole result
    assert result.exit_class is ExitClass.RESULT_INVALID
    assert all(a.name not in ("evil.exe", "script.sh") for a in result.artifacts)


# ------------------------------------------------------------- lifecycle hygiene


def test_container_is_destroyed_after_the_run(
    run_program: RunProgram, docker_client: object
) -> None:
    """A fresh container per attempt, force-removed afterwards: no sandbox
    container survives the run."""
    source = EMIT + "emit({'ok': True})\n"
    result = run_program(source)
    assert result.ok

    leftover = docker_client.containers.list(  # type: ignore[attr-defined]
        all=True, filters={"ancestor": "crucible-sandbox-runner:local"}
    )
    assert leftover == [], f"sandbox containers were not destroyed: {leftover}"
