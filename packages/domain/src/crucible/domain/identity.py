"""Tenancy, roles, permissions, and the authenticated principal.

Authorization is default-deny: a permission is granted only if the principal's
role maps to it AND (for API keys) the key's scopes include it. UI route hiding
is never the control — every use case checks these predicates (plan §6.3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class OrganizationStatus(StrEnum):
    """Tenant lifecycle (Phase 10). During the private beta, access is an
    allowlist: only `ACTIVE` organizations authenticate. `SUSPENDED` is a
    reversible block (billing, abuse, or off-boarding) — the data is retained,
    but every request is refused at the authentication boundary."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Permission(StrEnum):
    DATASET_READ = "dataset:read"
    DATASET_WRITE = "dataset:write"
    DATASET_DOWNLOAD = "dataset:download"
    RUN_READ = "run:read"
    RUN_CREATE = "run:create"
    RUN_CANCEL = "run:cancel"
    REVIEW_SUBMIT = "review:submit"
    EVAL_READ = "eval:read"
    EVAL_WRITE = "eval:write"
    APIKEY_MANAGE = "apikey:manage"
    MEMBER_MANAGE = "member:manage"
    # Owner-only: transfer/delete the organization, change billing and
    # retention policy. Without this, `admin` and `owner` would hold identical
    # permissions, and the privilege-escalation guard on API-key creation
    # (a key may not exceed its creator) would have nothing to bite on.
    ORG_MANAGE = "org:manage"


_VIEWER: frozenset[Permission] = frozenset(
    {Permission.DATASET_READ, Permission.RUN_READ, Permission.EVAL_READ}
)
_REVIEWER: frozenset[Permission] = _VIEWER | {Permission.REVIEW_SUBMIT}
_ENGINEER: frozenset[Permission] = _REVIEWER | {
    Permission.DATASET_WRITE,
    Permission.DATASET_DOWNLOAD,
    Permission.RUN_CREATE,
    Permission.RUN_CANCEL,
    Permission.EVAL_WRITE,
}
_ADMIN: frozenset[Permission] = _ENGINEER | {Permission.APIKEY_MANAGE, Permission.MEMBER_MANAGE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.REVIEWER: _REVIEWER,
    Role.ENGINEER: _ENGINEER,
    Role.ADMIN: _ADMIN,
    Role.OWNER: frozenset(Permission),  # every permission, including ORG_MANAGE
}


class ActorType(StrEnum):
    USER = "user"
    API_KEY = "api_key"


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, always bound to exactly one organization."""

    organization_id: uuid.UUID
    actor_type: ActorType
    actor_id: uuid.UUID
    role: Role
    # API keys may hold a subset of their role's permissions; None = full role.
    scopes: frozenset[Permission] | None = field(default=None)

    @property
    def permissions(self) -> frozenset[Permission]:
        granted = ROLE_PERMISSIONS[self.role]
        if self.scopes is None:
            return granted
        return granted & self.scopes  # a scope can narrow, never widen

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def user_id(self) -> uuid.UUID | None:
        """The acting *user*, or None when the caller is an API key.

        `actor_id` is the key's ID for a machine caller, so it must never be
        written to a users foreign key. Anything attributing a row to a person
        uses this; full attribution for both kinds of actor lives in the audit
        log (actor_type + actor_id).
        """
        return self.actor_id if self.actor_type is ActorType.USER else None
