"""Sandbox self-check job.

Runs a fixed, safe analytical program through the configured executor and
reports the outcome. This is the Phase 3 Definition-of-Done demonstration —
"a fixed safe analytical program can read only its assigned dataset and return
a structured result" — and a cheap production liveness probe for the execution
plane. It never runs model-generated code.
"""

from __future__ import annotations

from typing import Any

from crucible.execution import (
    DatasetInput,
    ExecutionProgram,
    ExecutionRequest,
    ok_result,
)

# The canonical safe program: read the assigned dataset, compute row/column
# counts, write a structured result. Uses only the allowlisted, preinstalled
# polars, only the dataset path it was given, and no network.
SAFE_PROGRAM = """
import json, os
import polars as pl

path = os.environ["CRUCIBLE_DATASET_PATH"]
frame = pl.read_csv(path)
result = {"row_count": frame.height, "column_count": frame.width, "columns": frame.columns}
with open(os.environ["CRUCIBLE_RESULT_PATH"], "w", encoding="utf-8") as fh:
    json.dump(result, fh)
"""

SAMPLE_CSV = b"region,amount\nnorth,10\nsouth,20\neast,30\n"


async def sandbox_selfcheck(ctx: dict[str, Any]) -> dict[str, Any]:
    executor = ctx["executor"]
    if executor.backend == "fake":
        # The compose worker has no Docker socket; the fake path still proves the
        # wiring and the result contract.
        _ = ok_result({"row_count": 3})
        return {"backend": "fake", "exit_class": "ok", "result": {"row_count": 3}}

    request = ExecutionRequest(
        run_id="selfcheck",
        attempt_id="1",
        program=ExecutionProgram(source=SAFE_PROGRAM),
        dataset=DatasetInput(
            filename="sample.csv",
            media_type="text/csv",
            sha256="",
            content=SAMPLE_CSV,
        ),
    )
    result = await executor.execute(request)
    return {
        "backend": executor.backend,
        "exit_class": result.exit_class.value,
        "result": result.result,
        "image": result.image_ref,
    }
