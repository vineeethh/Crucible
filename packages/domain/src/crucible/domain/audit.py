"""Audit actions. The audit log is append-only security evidence (plan §6.3)."""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    DATASET_CREATED = "dataset.created"
    DATASET_UPLOAD_STARTED = "dataset.upload_started"
    DATASET_VERSION_COMPLETED = "dataset.version_completed"
    DATASET_DOWNLOADED = "dataset.downloaded"
    RUN_CREATED = "run.created"
    RUN_CANCELLED = "run.cancelled"
    RUN_REVIEW_SUBMITTED = "run.review_submitted"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"
    BUDGET_SET = "org.budget_set"
    ROLE_CHANGED = "membership.role_changed"
    ACCESS_DENIED = "access.denied"


class AuditResult(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
