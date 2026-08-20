"""Fixtures for the sandbox canary suite.

These tests launch the real hardened runner image via the real Docker daemon and
assert that hostile programs are contained. They are skipped cleanly when Docker
is unavailable or the runner image has not been built, so the default test run
stays green without Docker.

Build the image first:
    docker build -f infra/docker/runner.Dockerfile -t crucible-sandbox-runner:local .
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from crucible.db import install_selector_event_loop_policy
from crucible.execution import (
    DatasetInput,
    DockerExecutor,
    ExecutionLimits,
    ExecutionProgram,
    ExecutionRequest,
    ExecutionResult,
)

install_selector_event_loop_policy()  # psycopg-style: selector loop on Windows

IMAGE = "crucible-sandbox-runner:local"
# Per-run work dirs live under the project by default: D: is a shared drive for
# Docker Desktop on the dev host (the compose stack binds from it), and on Linux
# CI a workspace path binds cleanly. SANDBOX_WORK_ROOT overrides it.
WORK_ROOT = Path(
    os.environ.get("SANDBOX_WORK_ROOT", str(Path(__file__).resolve().parents[2] / ".sandbox_runs"))
)

SAMPLE_CSV = b"region,amount\nnorth,10\nsouth,20\neast,30\n"


def _sandbox_available() -> bool:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        client.images.get(IMAGE)
        return True
    except Exception:
        return False


requires_sandbox = pytest.mark.skipif(
    not _sandbox_available(),
    reason="Docker daemon or the crucible-sandbox-runner:local image is unavailable",
)


@pytest.fixture(scope="session")
def executor() -> DockerExecutor:
    return DockerExecutor(image=IMAGE, work_root=WORK_ROOT)


@pytest.fixture(scope="session")
def docker_client() -> object:
    import docker

    return docker.from_env()


RunProgram = Callable[..., ExecutionResult]


@pytest.fixture
def run_program(executor: DockerExecutor) -> Iterator[RunProgram]:
    """Run one program in the sandbox. Returns the ExecutionResult. A fresh run
    id per call lets the destroy-after-run check target this attempt."""
    import asyncio

    def _run(
        source: str,
        *,
        dataset: bytes | None = SAMPLE_CSV,
        limits: ExecutionLimits | None = None,
    ) -> ExecutionResult:
        request = ExecutionRequest(
            run_id=f"canary-{uuid.uuid4().hex[:8]}",
            attempt_id="1",
            program=ExecutionProgram(source),
            dataset=DatasetInput(
                filename="sample.csv",
                media_type="text/csv",
                sha256="",
                content=dataset,
            ),
            limits=limits or ExecutionLimits(),
        )
        return asyncio.run(executor.execute(request))

    yield _run
