"""Crucible domain layer: pure types only.

Boundary rule (ADR-001, enforced by import-linter): this package imports
nothing but the standard library. No FastAPI, SQLAlchemy, Pydantic, Redis,
or sibling layers.
"""

from crucible.domain.audit import AuditAction, AuditResult
from crucible.domain.datasets import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_UPLOAD_BYTES,
    ColumnProfile,
    DatasetProfile,
    DatasetStatus,
    DatasetVersionStatus,
    UploadPolicyError,
    check_upload_policy,
)
from crucible.domain.errors import (
    Conflict,
    DependencyUnavailable,
    DomainError,
    NotAuthenticated,
    NotFound,
    PayloadTooLarge,
    PermissionDenied,
    ProblemDetail,
    RateLimited,
    UnsupportedMedia,
    ValidationFailed,
)
from crucible.domain.health import BuildInfo, ComponentHealth, HealthState, SystemStatus
from crucible.domain.identity import (
    ROLE_PERMISSIONS,
    ActorType,
    OrganizationStatus,
    Permission,
    Principal,
    Role,
)
from crucible.domain.ids import new_id, uuid7
from crucible.domain.runs import (
    ACTIVE_RUN_STATES,
    MAX_QUESTION_CHARS,
    TERMINAL_RUN_STATES,
    FailureCategory,
    RunEventType,
    RunStatus,
    can_transition,
)
from crucible.domain.scores import (
    RedactionState,
    ReviewDecision,
    ReviewStatus,
    ScoreSource,
    ScoreTargetType,
    ScoreType,
)

__all__ = [
    "ACTIVE_RUN_STATES",
    "ALLOWED_CONTENT_TYPES",
    "ALLOWED_EXTENSIONS",
    "MAX_COLUMNS",
    "MAX_QUESTION_CHARS",
    "MAX_ROWS",
    "MAX_UPLOAD_BYTES",
    "ROLE_PERMISSIONS",
    "TERMINAL_RUN_STATES",
    "ActorType",
    "AuditAction",
    "AuditResult",
    "BuildInfo",
    "ColumnProfile",
    "ComponentHealth",
    "Conflict",
    "DatasetProfile",
    "DatasetStatus",
    "DatasetVersionStatus",
    "DependencyUnavailable",
    "DomainError",
    "FailureCategory",
    "HealthState",
    "NotAuthenticated",
    "NotFound",
    "OrganizationStatus",
    "PayloadTooLarge",
    "Permission",
    "PermissionDenied",
    "Principal",
    "ProblemDetail",
    "RateLimited",
    "RedactionState",
    "ReviewDecision",
    "ReviewStatus",
    "Role",
    "RunEventType",
    "RunStatus",
    "ScoreSource",
    "ScoreTargetType",
    "ScoreType",
    "SystemStatus",
    "UnsupportedMedia",
    "UploadPolicyError",
    "ValidationFailed",
    "can_transition",
    "check_upload_policy",
    "new_id",
    "uuid7",
]
