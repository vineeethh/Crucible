"""Versioned evaluation case, suite, and fixture schemas.

A case is immutable once released (master plan §10.2): edits create a new
version. The loader pins the fixture by content hash and the suite carries a
content hash, so an accidental edit to released evidence is caught rather than
silently changing what "correct" means.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, Field

from crucible.agent import ColumnView


class OracleType(StrEnum):
    EXACT_VALUE = "exact_value"
    NUMERIC_EXACT_WITH_TOLERANCE = "numeric_exact_with_tolerance"
    RESULT_SET_MATCH = "result_set_match"
    BEHAVIORAL = "behavioral"  # the agent must abstain / route to review


class Oracle(BaseModel):
    type: OracleType
    expected: object = None
    abs_tol: float = 0.0
    rel_tol: float = 0.0
    expected_terminals: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str
    question: str
    answer_contract: dict[str, object] = Field(default_factory=dict)
    oracle: Oracle
    policy_checks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @property
    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        return _hash(payload)


class EvalColumn(BaseModel):
    name: str
    dtype: str


class EvalFixture(BaseModel):
    id: str
    version: str
    file: str
    sha256: str
    rows: int
    columns: list[EvalColumn]

    def column_views(self) -> list[ColumnView]:
        return [ColumnView(name=c.name, dtype=c.dtype) for c in self.columns]


class EvalSuite(BaseModel):
    id: str
    version: str
    purpose: str
    status: str
    fixture: str
    description: str = ""
    verified_by: str = ""
    smoke: list[str] = Field(default_factory=list)
    cases: list[EvalCase]

    def case(self, case_id: str) -> EvalCase:
        for c in self.cases:
            if c.id == case_id:
                return c
        raise KeyError(case_id)

    def smoke_suite(self) -> EvalSuite:
        """A derived suite containing only the smoke-marked cases."""
        smoke_cases = [c for c in self.cases if c.id in set(self.smoke)]
        return self.model_copy(
            update={"id": f"{self.id}-smoke", "purpose": "smoke", "cases": smoke_cases}
        )

    @property
    def content_hash(self) -> str:
        # A stable hash over the case set (id, question, oracle, checks): a
        # released case changing produces a new hash, which re-baselining detects.
        payload = [c.model_dump(mode="json") for c in self.cases]
        return _hash({"id": self.id, "version": self.version, "cases": payload})


def _hash(payload: object) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
