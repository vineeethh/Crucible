"""Local-development Docker executor (ADR-003: Docker is dev-only).

Every containment control is set explicitly here, and every one is deny-by-
default. The model contributes the program source and the dataset bytes; it
contributes nothing to the container configuration. There is no code path by
which a value from the request becomes an image name, a mount, a capability, a
network setting, or an environment variable beyond the two fixed paths.

Controls applied to every run (master plan §9.3):
  - network_disabled: no egress, no DNS, no cloud-metadata endpoint
  - read-only root filesystem
  - writable space only via a dedicated per-run results mount and a tmpfs /tmp
  - the dataset mounted read-only
  - non-root user, all Linux capabilities dropped, no-new-privileges
  - memory (no swap), pids, and CPU caps; wall-clock kill from the host
  - RLIMIT_CPU / RLIMIT_FSIZE inside, enforced by the harness
  - a fresh container per attempt, force-removed afterwards
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from crucible.execution.errors import ExecutorUnavailable
from crucible.execution.parser import collect_results
from crucible.execution.protocol import (
    ExecutionRequest,
    ExecutionResult,
    ExitClass,
    ResourceUsage,
)

DEFAULT_IMAGE = "crucible-sandbox-runner:local"

_SIGKILL, _SIGXFSZ, _SIGXCPU = 9, 25, 24


class DockerExecutor:
    """`backend == "docker"`. Constructs a fixed, hardened container per attempt."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        work_root: str | Path | None = None,
        seccomp_profile_path: str | Path | None = None,
    ) -> None:
        self._image = image
        self._work_root = (
            Path(work_root) if work_root else Path(tempfile.gettempdir()) / "crucible-sandbox"
        )
        self._seccomp = Path(seccomp_profile_path) if seccomp_profile_path else None
        self._client: Any = None  # lazily created docker client

    @property
    def backend(self) -> str:
        return "docker"

    @property
    def image_ref(self) -> str:
        return self._image

    def _client_or_connect(self) -> Any:
        if self._client is None:
            try:
                import docker  # imported lazily: dev-only optional dependency
            except ImportError as exc:  # pragma: no cover - env without docker sdk
                raise ExecutorUnavailable("the docker SDK is not installed") from exc
            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as exc:
                raise ExecutorUnavailable(f"cannot reach the Docker daemon: {exc}") from exc
        return self._client

    async def healthcheck(self) -> bool:
        try:
            await asyncio.to_thread(lambda: self._client_or_connect().ping())
            return True
        except Exception:
            return False

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return await asyncio.to_thread(self._run_blocking, request)

    # ------------------------------------------------------------------ blocking
    def _run_blocking(self, request: ExecutionRequest) -> ExecutionResult:
        client = self._client_or_connect()
        limits = request.limits
        work = self._work_root / f"{request.run_id}_{request.attempt_id}_{uuid.uuid4().hex[:8]}"
        in_dir, out_dir = work / "in", work / "out"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        # The container runs as a fixed non-root UID (10001) that maps to no host
        # user; on a native-Linux host the bind-mounted results dir would be owned
        # by the host user and unwritable by 10001, so the harness could not write
        # its manifest. Make this ephemeral per-run scratch dir writable. It is not
        # a containment control (it is deleted in `finally`); every real control —
        # non-root, read-only root, no network, dropped caps, resource limits —
        # is enforced on the container in `_container_config`.
        out_dir.chmod(0o777)

        dataset_name = request.dataset.safe_name
        (in_dir / "program.py").write_text(request.program.source, encoding="utf-8")
        if request.dataset.content is not None:
            (in_dir / dataset_name).write_bytes(request.dataset.content)

        container = None
        try:
            container = client.containers.create(
                **self._container_config(request, in_dir, out_dir, dataset_name)
            )
            container.start()
            wall_killed, oom_killed = self._await_exit(container, limits.wall_seconds)
            return self._classify(request, out_dir, wall_killed=wall_killed, oom_killed=oom_killed)
        except ExecutorUnavailable:
            raise
        except Exception as exc:
            return ExecutionResult(
                exit_class=ExitClass.STARTUP_ERROR,
                image_ref=self._image,
                limits=limits,
                usage=ResourceUsage(wall_ms=0),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.remove(force=True)  # fresh + destroyed per attempt
            shutil.rmtree(work, ignore_errors=True)

    def _container_config(
        self, request: ExecutionRequest, in_dir: Path, out_dir: Path, dataset_name: str
    ) -> dict[str, Any]:
        limits = request.limits
        environment = {
            "CRUCIBLE_DATASET_PATH": f"/sandbox/{dataset_name}" if request.dataset.content else "",
            "CRUCIBLE_RESULTS_DIR": "/results",
            "CRUCIBLE_CPU_SECONDS": str(limits.cpu_seconds),
            "CRUCIBLE_FILE_BYTES": str(limits.file_bytes),
            "CRUCIBLE_STDOUT_BYTES": str(limits.stdout_bytes),
            "CRUCIBLE_WALL_SECONDS": str(limits.wall_seconds),
        }
        security_opt = ["no-new-privileges:true"]
        if self._seccomp and self._seccomp.is_file():
            security_opt.append("seccomp=" + self._seccomp.read_text(encoding="utf-8"))

        config: dict[str, Any] = {
            "image": self._image,
            "environment": environment,
            "user": "10001:10001",
            "network_disabled": True,  # no egress, DNS, or metadata endpoint
            "read_only": True,  # read-only root filesystem
            "tmpfs": {"/tmp": f"size={4 * 1024 * 1024},mode=1777,nosuid,nodev,noexec"},
            "volumes": {
                str(in_dir): {"bind": "/sandbox", "mode": "ro"},
                str(out_dir): {"bind": "/results", "mode": "rw"},
            },
            "mem_limit": limits.memory_bytes,
            "memswap_limit": limits.memory_bytes,  # equal to mem => swap disabled
            "pids_limit": limits.pids,
            "nano_cpus": int(limits.cpus * 1_000_000_000),
            "cap_drop": ["ALL"],
            "security_opt": security_opt,
            "ipc_mode": "private",
            "network_mode": "none",
            "labels": {
                "crucible.run_id": request.run_id,
                "crucible.attempt_id": request.attempt_id,
            },
            "detach": True,
        }
        return config

    def _await_exit(self, container: Any, wall_seconds: float) -> tuple[bool, bool]:
        """Enforce the wall-clock budget from the host. Returns (wall_killed,
        oom_killed)."""
        wall_killed = False
        try:
            container.wait(timeout=wall_seconds + 2)
        except Exception:  # timeout/connection error => over budget
            wall_killed = True
            with contextlib.suppress(Exception):
                container.kill()
            with contextlib.suppress(Exception):
                container.wait(timeout=5)
        oom_killed = False
        with contextlib.suppress(Exception):
            container.reload()
            oom_killed = bool(container.attrs.get("State", {}).get("OOMKilled", False))
        return wall_killed, oom_killed

    def _classify(
        self, request: ExecutionRequest, out_dir: Path, *, wall_killed: bool, oom_killed: bool
    ) -> ExecutionResult:
        import json

        manifest_path = out_dir / "manifest.json"
        if not manifest_path.is_file():
            # The harness never ran (or could not write): the sandbox failed to
            # start. Operational, not the program's fault.
            return ExecutionResult(
                exit_class=ExitClass.STARTUP_ERROR,
                image_ref=self._image,
                limits=request.limits,
                usage=ResourceUsage(
                    wall_ms=0, wall_clock_killed=wall_killed, oom_killed=oom_killed
                ),
                error_detail="harness produced no manifest",
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return ExecutionResult(
                exit_class=ExitClass.INTERNAL,
                image_ref=self._image,
                limits=request.limits,
                usage=ResourceUsage(wall_ms=0),
                error_detail=f"unreadable manifest: {exc}",
            )

        child_code = manifest.get("program_exit_code")
        soft_timeout = bool(manifest.get("soft_timeout"))
        usage = ResourceUsage(
            wall_ms=int(manifest.get("duration_ms", 0)),
            program_exit_code=child_code,
            oom_killed=oom_killed,
            wall_clock_killed=wall_killed,
        )
        stdout = str(manifest.get("stdout", ""))
        stderr = str(manifest.get("stderr", ""))
        truncated = bool(manifest.get("stdout_truncated")) or bool(manifest.get("stderr_truncated"))

        def build(
            exit_class: ExitClass,
            result: dict[str, object] | None = None,
            detail: str | None = None,
            artifacts: tuple[Any, ...] = (),
        ) -> ExecutionResult:
            return ExecutionResult(
                exit_class=exit_class,
                image_ref=self._image,
                limits=request.limits,
                usage=usage,
                result=result,
                stdout=stdout,
                stderr=stderr,
                output_truncated=truncated,
                artifacts=artifacts,
                error_detail=detail,
            )

        if wall_killed or soft_timeout:
            return build(ExitClass.TIMEOUT, detail="wall-clock budget exceeded")
        if oom_killed:
            return build(ExitClass.OOM, detail="memory limit exceeded")
        if child_code is None:
            return build(ExitClass.RESOURCE_KILLED, detail="program killed without exit code")
        if child_code < 0:
            signal_no = -child_code
            reason = {
                _SIGKILL: "killed (SIGKILL: memory or pids limit)",
                _SIGXFSZ: "killed (SIGXFSZ: file-size limit)",
                _SIGXCPU: "killed (SIGXCPU: CPU-time limit)",
            }.get(signal_no, f"killed by signal {signal_no}")
            return build(ExitClass.RESOURCE_KILLED, detail=reason)
        if child_code > 0:
            return build(ExitClass.RUNTIME_ERROR, detail=f"program exited {child_code}")

        # child_code == 0: collect and validate whatever it produced.
        parse = collect_results(out_dir, request.limits)
        if parse.result is None:
            missing = parse.reason is not None and "no result" in parse.reason.lower()
            return build(
                ExitClass.RESULT_MISSING if missing else ExitClass.RESULT_INVALID,
                detail=parse.reason,
            )
        if not parse.ok:
            # A result exists but something else was rejected (bad artifact,
            # over-cap): surface as invalid rather than silently publishing it.
            return build(
                ExitClass.RESULT_INVALID,
                result=None,
                detail=parse.reason,
                artifacts=parse.artifacts,
            )
        return build(ExitClass.OK, result=parse.result, artifacts=parse.artifacts)
