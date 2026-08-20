"""Executor selection for the worker (composition root).

The backend is chosen by configuration, never by the request. The compose
worker defaults to `fake` because it deliberately has no Docker socket
(ADR-003); a developer running the worker on the host can select `docker`, and
staging/production select `microvm`.
"""

from __future__ import annotations

from crucible.execution import DockerExecutor, Executor, FakeExecutor, MicroVMExecutor
from crucible_worker.settings import WorkerAppSettings


def build_executor(settings: WorkerAppSettings) -> Executor:
    backend = settings.executor_backend
    if backend == "docker":
        return DockerExecutor(image=settings.sandbox_image, work_root=settings.sandbox_work_root)
    if backend == "microvm":
        return MicroVMExecutor(
            api_key=settings.microvm_api_key, template_id=settings.microvm_template_id
        )
    return FakeExecutor()
