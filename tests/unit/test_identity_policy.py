"""RBAC is default-deny, scopes narrow but never widen, keys cannot escalate."""

import itertools
import uuid

import pytest

from crucible.domain import (
    ROLE_PERMISSIONS,
    ActorType,
    Permission,
    Principal,
    Role,
)


def _principal(role: Role, scopes: frozenset[Permission] | None = None) -> Principal:
    return Principal(
        organization_id=uuid.uuid4(),
        actor_type=ActorType.API_KEY,
        actor_id=uuid.uuid4(),
        role=role,
        scopes=scopes,
    )


def test_viewer_cannot_write_or_run() -> None:
    viewer = _principal(Role.VIEWER)
    assert viewer.can(Permission.DATASET_READ)
    assert not viewer.can(Permission.DATASET_WRITE)
    assert not viewer.can(Permission.RUN_CREATE)
    assert not viewer.can(Permission.APIKEY_MANAGE)


def test_reviewer_can_review_but_not_upload() -> None:
    reviewer = _principal(Role.REVIEWER)
    assert reviewer.can(Permission.REVIEW_SUBMIT)
    assert not reviewer.can(Permission.DATASET_WRITE)


def test_engineer_can_run_but_not_manage_keys_or_members() -> None:
    engineer = _principal(Role.ENGINEER)
    assert engineer.can(Permission.RUN_CREATE)
    assert engineer.can(Permission.DATASET_WRITE)
    assert not engineer.can(Permission.APIKEY_MANAGE)
    assert not engineer.can(Permission.MEMBER_MANAGE)


def test_owner_holds_every_permission() -> None:
    owner = _principal(Role.OWNER)
    assert all(owner.can(p) for p in Permission)


def test_admin_is_strictly_below_owner() -> None:
    """If admin and owner held identical permissions, the escalation guard on
    API-key creation ("a key may not exceed its creator") would be vacuous."""
    admin, owner = _principal(Role.ADMIN), _principal(Role.OWNER)
    assert admin.permissions < owner.permissions
    assert not admin.can(Permission.ORG_MANAGE)
    assert owner.can(Permission.ORG_MANAGE)


def test_role_hierarchy_is_monotonic() -> None:
    """Each step up the ladder is a superset — no role loses a capability."""
    ladder = [Role.VIEWER, Role.REVIEWER, Role.ENGINEER, Role.ADMIN, Role.OWNER]
    for lower, higher in itertools.pairwise(ladder):
        assert ROLE_PERMISSIONS[lower] <= ROLE_PERMISSIONS[higher]


def test_scopes_narrow_a_key() -> None:
    key = _principal(Role.ENGINEER, scopes=frozenset({Permission.RUN_READ}))
    assert key.can(Permission.RUN_READ)
    assert not key.can(Permission.RUN_CREATE)  # role allows it; the scope does not


def test_scopes_cannot_widen_a_key() -> None:
    """A scope list is an intersection, so a viewer key claiming admin scopes
    still cannot manage keys."""
    key = _principal(
        Role.VIEWER, scopes=frozenset({Permission.APIKEY_MANAGE, Permission.DATASET_WRITE})
    )
    assert not key.can(Permission.APIKEY_MANAGE)
    assert not key.can(Permission.DATASET_WRITE)
    assert key.permissions == frozenset()


@pytest.mark.parametrize("role", list(Role))
def test_every_role_is_mapped(role: Role) -> None:
    assert role in ROLE_PERMISSIONS


def test_api_key_principal_has_no_user_id() -> None:
    """`actor_id` is the key's ID for a machine caller. Writing it to a users
    foreign key would be a constraint violation, so `user_id` must be None."""
    key = _principal(Role.OWNER)
    assert key.actor_type is ActorType.API_KEY
    assert key.user_id is None


def test_user_principal_exposes_its_user_id() -> None:
    user_id = uuid.uuid4()
    person = Principal(
        organization_id=uuid.uuid4(),
        actor_type=ActorType.USER,
        actor_id=user_id,
        role=Role.ENGINEER,
    )
    assert person.user_id == user_id
