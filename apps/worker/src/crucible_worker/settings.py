"""Typed worker settings — the only place the worker reads the environment."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRUCIBLE_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    profile: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = Field(
        default="postgresql+psycopg://crucible:crucible@localhost:55432/crucible",
        validation_alias=AliasChoices("CRUCIBLE_DATABASE_URL", "DATABASE_URL"),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("CRUCIBLE_REDIS_URL", "REDIS_URL"),
    )
    git_sha: str = Field(
        default="unknown", validation_alias=AliasChoices("CRUCIBLE_GIT_SHA", "GIT_SHA")
    )
    job_concurrency: int = 4

    s3_bucket: str = Field(default="crucible-local", validation_alias=AliasChoices("S3_BUCKET"))
    s3_endpoint_url: str | None = Field(
        default="http://localhost:9000", validation_alias=AliasChoices("S3_ENDPOINT_URL")
    )
    s3_region: str = Field(default="us-east-1", validation_alias=AliasChoices("S3_REGION"))
    # The worker only reads objects server-side; it never issues presigned URLs.
    s3_access_key: str | None = Field(
        default="crucible", validation_alias=AliasChoices("S3_ACCESS_KEY")
    )
    s3_secret_key: str | None = Field(
        default="crucible-local-only", validation_alias=AliasChoices("S3_SECRET_KEY")
    )

    # Sandbox backend for untrusted code (ADR-003).
    #   fake    - deterministic, no execution (default: the compose worker has
    #             no Docker socket, by policy, so it cannot use docker)
    #   docker  - local hardened Docker runner (host-run worker / tests only)
    #   microvm - managed provider (staging/production)
    executor_backend: Literal["fake", "docker", "microvm"] = Field(
        default="fake", validation_alias=AliasChoices("EXECUTOR_BACKEND")
    )
    sandbox_image: str = Field(
        default="crucible-sandbox-runner:local", validation_alias=AliasChoices("SANDBOX_IMAGE")
    )
    sandbox_work_root: str | None = Field(
        default=None, validation_alias=AliasChoices("SANDBOX_WORK_ROOT")
    )
    microvm_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("MICROVM_API_KEY")
    )
    microvm_template_id: str | None = Field(
        default=None, validation_alias=AliasChoices("MICROVM_TEMPLATE_ID")
    )

    # Model gateway for the agent (plan/code/repair). `fake` is deterministic and
    # offline (default); `openai_compat` targets any OpenAI-compatible endpoint.
    model_backend: Literal["fake", "openai_compat"] = Field(
        default="fake", validation_alias=AliasChoices("MODEL_BACKEND")
    )
    openai_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_BASE_URL")
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY")
    )
    openai_model: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_MODEL"))
    # The tier-1 model for the two-tier router when the backend is openai_compat.
    # Same PROVIDER as `openai_model` (just a cheaper model) — this does not
    # protect against that provider itself being rate-limited or down. For
    # that, see `fallback_openai_*` below.
    openai_model_lite: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_MODEL_LITE")
    )

    # An independent OpenAI-compatible provider (a different base URL, key,
    # and quota — e.g. Groq or Google AI Studio's free tier alongside
    # OpenRouter's) that `build_model()` wires as the router's secondary when
    # `openai_model`'s own provider is unavailable or rate-limited (a 429/5xx
    # exhausting `OpenAICompatModel`'s retries raises `ModelUnavailable`,
    # which `RouterPolicy.fallback_on_error` catches). Optional: if any of
    # these three is unset, no cross-provider fallback is wired and a primary
    # outage abstains as before.
    fallback_openai_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("FALLBACK_OPENAI_BASE_URL")
    )
    fallback_openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("FALLBACK_OPENAI_API_KEY")
    )
    fallback_openai_model: str | None = Field(
        default=None, validation_alias=AliasChoices("FALLBACK_OPENAI_MODEL")
    )

    # Phase 8 efficiency controls. Both default OFF; flipping either back is the
    # documented rollback (no deploy, no data migration — see
    # docs/operations/efficiency.md).
    #   router_policy: "default" = single gateway; "two-tier" = cheap primary
    #   with declared escalation/fallback (crucible.agent.router).
    router_policy: Literal["default", "two-tier"] = Field(
        default="default", validation_alias=AliasChoices("ROUTER_POLICY")
    )
    #   exact_cache_enabled: replay exactly verified answers keyed by
    #   tenant+dataset-content+config+question. Semantic caching has no flag on
    #   purpose: it stays disabled unless an approved evaluation supports it.
    exact_cache_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("EXACT_CACHE_ENABLED")
    )

    execution_wall_seconds: float = 20.0

    # Platform data-retention window (Phase 10): terminal runs and their
    # evidence older than this are deleted by the daily retention job. A tenant
    # may override it via organizations.retention_days. Audit events and
    # datasets are out of scope.
    retention_days: int = 90
