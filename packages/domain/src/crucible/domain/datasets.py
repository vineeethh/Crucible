"""Dataset ingestion domain: upload policy, immutable versions, schema profile.

A dataset version is identified by the SHA-256 of its bytes, never by filename
(Phase 2 risk: "using file names as identity rather than content hashes").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB
MAX_ROWS = 2_000_000
MAX_COLUMNS = 512

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/csv",
        "application/vnd.apache.parquet",
    }
)

# Extension is advisory only; the parser decides the real format.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".parquet"})


class DatasetStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class DatasetVersionStatus(StrEnum):
    AWAITING_UPLOAD = "awaiting_upload"  # presigned URL issued, bytes not yet confirmed
    PENDING_PROFILE = "pending_profile"  # bytes confirmed, profiling job queued
    READY = "ready"  # immutable, profiled, usable by runs
    INVALID = "invalid"  # parse/policy failure; terminal, never retried in place


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    name: str
    dtype: str
    null_count: int
    distinct_count: int | None = None
    min_value: str | None = None
    max_value: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Schema profile of one immutable dataset version."""

    row_count: int
    column_count: int
    columns: tuple[ColumnProfile, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [asdict(c) for c in self.columns],
        }

    @property
    def schema_hash(self) -> str:
        """Canonical hash of (name, dtype) pairs in column order.

        Two uploads with identical schemas share a schema hash even when their
        rows differ — this is what eval cases pin, alongside the content hash.
        """
        canonical = json.dumps(
            [[c.name, c.dtype] for c in self.columns], separators=(",", ":"), sort_keys=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class UploadPolicyError(StrEnum):
    """Reasons an upload is refused before any bytes are accepted."""

    CONTENT_TYPE_NOT_ALLOWED = "content_type_not_allowed"
    TOO_LARGE = "too_large"
    EMPTY = "empty"
    EXTENSION_NOT_ALLOWED = "extension_not_allowed"


def check_upload_policy(
    *, filename: str, content_type: str, declared_size: int
) -> UploadPolicyError | None:
    """Pure admission check applied before a presigned URL is issued."""
    if declared_size <= 0:
        return UploadPolicyError.EMPTY
    if declared_size > MAX_UPLOAD_BYTES:
        return UploadPolicyError.TOO_LARGE
    if content_type not in ALLOWED_CONTENT_TYPES:
        return UploadPolicyError.CONTENT_TYPE_NOT_ALLOWED
    suffix = filename[filename.rfind(".") :].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        return UploadPolicyError.EXTENSION_NOT_ALLOWED
    return None
