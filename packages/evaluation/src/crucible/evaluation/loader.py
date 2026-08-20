"""Load suites and fixtures from the evals/ directory, verifying content hashes.

Loading a fixture re-computes its SHA-256 and refuses to proceed if it does not
match the manifest — frozen fixtures are pinned by content, so a swapped or
edited file cannot silently change the gold answers (master plan §10.4).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from crucible.evaluation.schemas import EvalFixture, EvalSuite


def repo_evals_dir() -> Path:
    # packages/evaluation/src/crucible/evaluation/loader.py -> repo/evals
    return Path(__file__).resolve().parents[5] / "evals"


class FixtureIntegrityError(Exception):
    pass


def load_suite(path: str | Path) -> EvalSuite:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return EvalSuite.model_validate(data)


def load_fixture(fixture_id: str, *, evals_dir: Path | None = None) -> tuple[EvalFixture, bytes]:
    base = evals_dir or repo_evals_dir()
    manifest_path = base / "fixtures" / f"{fixture_id}.manifest.yaml"
    manifest = EvalFixture.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
    content = (base / "fixtures" / manifest.file).read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != manifest.sha256:
        raise FixtureIntegrityError(
            f"fixture {fixture_id}: content hash {actual} != manifest {manifest.sha256}"
        )
    return manifest, content
