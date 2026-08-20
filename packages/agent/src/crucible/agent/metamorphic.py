"""Metamorphic verification (master plan's Tier 2, metric-contract.md's
"invariant/metamorphic scorer" — previously specified, never implemented).

Re-runs the SAME generated program against a TRANSFORMED dataset and checks a
relation that needs no gold answer: a correct program's answer must not
change under a row shuffle or a column reorder, because none of the agent's
operations are legitimately row-order- or column-order-dependent (they read
columns by name and every reduction — sum/mean/count/count_distinct/argmax/
argmin/group-by — is order-invariant over its own input). A program whose
answer changes anyway is demonstrably wrong, independent of what the correct
answer actually is.

Runs entirely host-side (transform) + sandbox-side (re-execution, the SAME
untrusted program): zero LLM calls, zero prompt exposure, so T2 (no cell
values in a model prompt) is untouched — this module never imports anything
that talks to a model.
"""

from __future__ import annotations

import hashlib
import io

import polars as pl

from crucible.agent.schemas import ChallengeOutcome
from crucible.execution import (
    DatasetInput,
    ExecutionLimits,
    ExecutionProgram,
    ExecutionRequest,
    Executor,
)

# Cheap, safe, and broadly applicable: neither transform is legitimate grounds
# for a different answer under ANY operation this agent supports today.
# Transforms whose expected relation depends on the operation (e.g. row
# duplication doubling a sum but not a mean) are a follow-up, not this pass.
_MAX_ROWS_FOR_TRANSFORM = 500_000  # matches domain.MAX_ROWS's order of magnitude


def _read(data: bytes, media_type: str) -> pl.DataFrame | None:
    try:
        buf = io.BytesIO(data)
        if media_type == "application/vnd.apache.parquet":
            return pl.read_parquet(buf)
        return pl.read_csv(buf, infer_schema_length=10_000, try_parse_dates=True)
    except Exception:  # noqa: BLE001 - a transform that can't even parse skips, never crashes
        return None


def _write(df: pl.DataFrame, media_type: str) -> bytes:
    buf = io.BytesIO()
    if media_type == "application/vnd.apache.parquet":
        df.write_parquet(buf)
    else:
        df.write_csv(buf)
    return buf.getvalue()


def shuffle_rows(data: bytes, media_type: str, *, seed: int = 1337) -> bytes | None:
    df = _read(data, media_type)
    if df is None or df.height < 2 or df.height > _MAX_ROWS_FOR_TRANSFORM:
        return None
    return _write(df.sample(fraction=1.0, shuffle=True, seed=seed), media_type)


def reorder_columns(data: bytes, media_type: str) -> bytes | None:
    df = _read(data, media_type)
    if df is None or df.width < 2:
        return None
    return _write(df.select(list(reversed(df.columns))), media_type)


_TRANSFORMS: tuple[tuple[str, str, str], ...] = (
    ("row_shuffle", "shuffle_rows", "the result is unchanged when rows are reordered"),
    ("column_reorder", "reorder_columns", "the result is unchanged when columns are reordered"),
)
_TRANSFORM_FNS = {"shuffle_rows": shuffle_rows, "reorder_columns": reorder_columns}


def _values_agree(a: object, b: object, *, tol: float = 1e-6) -> bool:
    """Value equality with float tolerance: shuffling rows can change floating
    point summation ORDER, which can change a sum/mean in its last few bits
    even though the mathematical relation holds exactly — an exact-equality
    check would flag that as a false violation."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        sa = sorted(a, key=repr)
        sb = sorted(b, key=repr)
        return all(_values_agree(x, y, tol=tol) for x, y in zip(sa, sb, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_values_agree(a[k], b[k], tol=tol) for k in a)
    return a == b


async def run_challenges(
    *,
    executor: Executor,
    run_id: str,
    attempt_id: str,
    program: ExecutionProgram,
    dataset: DatasetInput,
    limits: ExecutionLimits,
    baseline_result: dict[str, object],
) -> list[ChallengeOutcome]:
    """Re-run `program` against each transformed dataset and compare to the
    baseline (already-verified-as-executed) result. Never raises: a transform
    that can't apply (e.g. too few rows) is skipped, not reported as failed —
    absence of evidence isn't evidence of a bug."""
    outcomes: list[ChallengeOutcome] = []
    if dataset.content is None:
        return outcomes  # no local bytes to transform (e.g. a microVM grant)

    for transform_name, fn_name, relation in _TRANSFORMS:
        transformed = _TRANSFORM_FNS[fn_name](dataset.content, dataset.media_type)
        if transformed is None:
            continue  # not applicable to this dataset shape — no evidence either way

        request = ExecutionRequest(
            run_id=run_id,
            attempt_id=f"{attempt_id}-challenge-{transform_name}",
            program=program,
            dataset=DatasetInput(
                filename=dataset.filename,
                media_type=dataset.media_type,
                sha256=hashlib.sha256(transformed).hexdigest(),
                content=transformed,
            ),
            limits=limits,
        )
        result = await executor.execute(request)
        if not result.ok:
            # The baseline ran fine; the SAME program failing only on
            # transformed input is itself suspicious, but distinct from an
            # answer mismatch — recorded as not-held with the execution detail.
            outcomes.append(
                ChallengeOutcome(
                    transform=transform_name,
                    relation=relation,
                    held=False,
                    detail=f"re-execution failed: {result.exit_class.value}",
                )
            )
            continue

        held = _values_agree(result.result.get("value") if result.result else None, baseline_result.get("value"))
        outcomes.append(
            ChallengeOutcome(
                transform=transform_name,
                relation=relation,
                held=held,
                detail="" if held else (
                    f"baseline value={baseline_result.get('value')!r} vs "
                    f"{transform_name} value={(result.result or {}).get('value')!r}"
                ),
            )
        )
    return outcomes
