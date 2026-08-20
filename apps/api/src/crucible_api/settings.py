"""Typed settings. The ONLY place the API reads the environment (plan §6.2).

Profiles: local | test | staging | production. Staging/production startup
fails fast when mandatory configuration is missing or unsafe — a misconfigured
deploy must die loudly at boot, not at first request.
"""

from __future__ import annotations

import subprocess
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from crucible.domain import BuildInfo

Profile = Literal["local", "test", "staging", "production"]

# Compose service names and loopback. Matched against the parsed *hostname*,
# never a substring of the URL — `redis://cache.internal/0` must not trip the
# "redis" entry just because the scheme shares its name.
_LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "host.docker.internal", "minio", "postgres", "redis"}
)


def _is_local(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).hostname
    return host is not None and host.lower() in _LOCAL_HOSTS


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRUCIBLE_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,  # aliased fields stay settable by field name (tests, wiring)
    )

    profile: Profile = "local"
    database_url: str = Field(
        default="postgresql+psycopg://crucible:crucible@localhost:55432/crucible",
        validation_alias=AliasChoices("CRUCIBLE_DATABASE_URL", "DATABASE_URL"),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("CRUCIBLE_REDIS_URL", "REDIS_URL"),
    )
    allowed_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:3100"])
    git_sha: str = Field(
        default="unknown", validation_alias=AliasChoices("CRUCIBLE_GIT_SHA", "GIT_SHA")
    )
    built_at: str = Field(
        default="unknown", validation_alias=AliasChoices("CRUCIBLE_BUILT_AT", "BUILT_AT")
    )
    app_version: str = "0.1.0"

    # ------------------------------------------------------------- object store
    s3_bucket: str = Field(default="crucible-local", validation_alias=AliasChoices("S3_BUCKET"))
    s3_endpoint_url: str | None = Field(
        default="http://localhost:9000", validation_alias=AliasChoices("S3_ENDPOINT_URL")
    )
    # The host a *client* can reach. In compose the API talks to `minio:9000`
    # while the browser needs `localhost:9000`, and a presigned URL is signed
    # for one specific host. Defaults to s3_endpoint_url when unset (cloud).
    s3_public_endpoint_url: str | None = Field(
        default=None, validation_alias=AliasChoices("S3_PUBLIC_ENDPOINT_URL")
    )
    s3_region: str = Field(default="us-east-1", validation_alias=AliasChoices("S3_REGION"))
    s3_access_key: str | None = Field(
        default="crucible", validation_alias=AliasChoices("S3_ACCESS_KEY")
    )
    s3_secret_key: str | None = Field(
        default="crucible-local-only", validation_alias=AliasChoices("S3_SECRET_KEY")
    )
    upload_url_ttl_seconds: int = 900

    # -------------------------------------------------------------------- OIDC
    # Unset in local/test: API keys are the credential there. Required whenever a
    # deployed profile wants interactive users.
    oidc_issuer: str | None = Field(default=None, validation_alias=AliasChoices("OIDC_ISSUER"))
    oidc_audience: str | None = Field(default=None, validation_alias=AliasChoices("OIDC_AUDIENCE"))
    oidc_jwks_uri: str | None = Field(default=None, validation_alias=AliasChoices("OIDC_JWKS_URI"))

    # ------------------------------------------------------------- rate limits
    # Expensive routes (upload creation, run creation) fail closed when the
    # limiter is unavailable (plan §5.5).
    rate_limit_writes_per_minute: int = 60
    rate_limit_runs_per_minute: int = 20

    @property
    def deployed(self) -> bool:
        return self.profile in ("staging", "production")

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience and self.oidc_jwks_uri)

    @model_validator(mode="after")
    def _fail_fast_when_deployed(self) -> Self:
        if not self.deployed:
            return self
        problems: list[str] = []
        if not self.allowed_origins or "*" in self.allowed_origins:
            problems.append("allowed_origins must be an explicit non-wildcard list")
        for name, url in (
            ("database_url", self.database_url),
            ("redis_url", self.redis_url),
            ("s3_endpoint_url", self.s3_endpoint_url),
        ):
            if _is_local(url):
                problems.append(f"{name} points at a local host")
        if self.git_sha == "unknown":
            problems.append("git_sha must identify the deployed build")
        if self.s3_secret_key and "local-only" in self.s3_secret_key:
            problems.append("s3_secret_key is a local development credential")
        if problems:
            raise ValueError(f"unsafe {self.profile} configuration: " + "; ".join(problems))
        return self


def resolve_build_info(settings: ApiSettings) -> BuildInfo:
    """Build identity for /version. In local dev, falls back to `git rev-parse`
    so the endpoint is truthful without CI-injected metadata."""
    sha = settings.git_sha
    if sha == "unknown" and settings.profile == "local":
        try:
            sha = (
                subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                ).stdout.strip()
                or "unknown"
            )
        except Exception:
            sha = "unknown"
    return BuildInfo(
        git_sha=sha,
        version=settings.app_version,
        profile=settings.profile,
        built_at=settings.built_at,
    )
