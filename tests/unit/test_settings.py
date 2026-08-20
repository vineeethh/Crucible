"""Settings tests: profiles, env aliases, and production fail-fast rules."""

import pytest
from pydantic import ValidationError

from crucible_api.settings import ApiSettings, resolve_build_info

# Note: _env_file=None disables .env pickup so tests are hermetic.


def _settings(**kwargs: object) -> ApiSettings:
    return ApiSettings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_local_defaults_are_valid() -> None:
    s = _settings()
    assert s.profile == "local"
    assert not s.deployed


def test_env_alias_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db.internal:5432/x")
    s = _settings()
    assert "db.internal" in s.database_url


def test_production_rejects_wildcard_origins() -> None:
    with pytest.raises(ValidationError, match="allowed_origins"):
        _settings(
            profile="production",
            allowed_origins=["*"],
            database_url="postgresql+psycopg://u:p@db.internal/x",
            redis_url="redis://cache.internal/0",
            git_sha="abc1234",
        )


def test_production_rejects_localhost_database() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        _settings(
            profile="production",
            allowed_origins=["https://app.example.com"],
            git_sha="abc1234",
        )


def test_production_requires_git_sha() -> None:
    with pytest.raises(ValidationError, match="git_sha"):
        _settings(
            profile="production",
            allowed_origins=["https://app.example.com"],
            database_url="postgresql+psycopg://u:p@db.internal/x",
            redis_url="redis://cache.internal/0",
        )


def test_production_rejects_local_object_storage_credentials() -> None:
    """The MinIO development credential must never reach a deployed profile."""
    with pytest.raises(ValidationError, match="s3_"):
        _settings(
            profile="production",
            allowed_origins=["https://app.example.com"],
            database_url="postgresql+psycopg://u:p@db.internal/x",
            redis_url="redis://cache.internal/0",
            git_sha="abc1234",
        )


def test_valid_production_configuration_passes() -> None:
    s = _settings(
        profile="production",
        allowed_origins=["https://app.example.com"],
        database_url="postgresql+psycopg://u:p@db.internal/x",
        redis_url="redis://cache.internal/0",
        s3_endpoint_url=None,
        s3_bucket="crucible-prod",
        s3_access_key="AKIAEXAMPLE",
        s3_secret_key="managed-by-secret-manager",
        git_sha="abc1234",
    )
    assert s.deployed
    assert not s.oidc_enabled  # OIDC is opt-in; API keys still work


def test_build_info_uses_explicit_sha_without_subprocess() -> None:
    s = _settings(profile="test", git_sha="deadbee")
    info = resolve_build_info(s)
    assert info.git_sha == "deadbee"
    assert info.profile == "test"
