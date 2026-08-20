"""Error contracts: RFC 9457-style problem details as pure value objects.

`detail` must always be safe to show a user. Internal diagnostics stay in logs
and traces (plan §6.4) — never in the response body.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

_BASE = "https://crucible.dev/problems/"


@dataclass(frozen=True, slots=True)
class ProblemDetail:
    """Transport-agnostic problem description; apps render it as
    application/problem+json."""

    type: str
    title: str
    status: int
    detail: str
    request_id: str = ""
    retryable: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DomainError(Exception):
    """Base for errors that carry a user-safe problem detail."""

    def __init__(self, problem: ProblemDetail) -> None:
        super().__init__(problem.title)
        self.problem = problem


class ValidationFailed(DomainError):
    def __init__(self, detail: str, code: str = "validation") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}{code}",
                title="Request is invalid",
                status=400,
                detail=detail,
            )
        )


class NotAuthenticated(DomainError):
    def __init__(self, detail: str = "Valid credentials are required.") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}not-authenticated",
                title="Not authenticated",
                status=401,
                detail=detail,
            )
        )


class PermissionDenied(DomainError):
    """Used for both missing permissions and cross-tenant access.

    Cross-tenant reads deliberately surface as 404 (see NotFound) so that IDs
    cannot be probed for existence; this 403 is for in-tenant permission gaps.
    """

    def __init__(self, detail: str = "You do not have permission to perform this action.") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}permission-denied",
                title="Permission denied",
                status=403,
                detail=detail,
            )
        )


class NotFound(DomainError):
    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}not-found",
                title=f"{resource} not found",
                status=404,
                detail=f"{resource} does not exist or is not visible to your organization.",
            )
        )


class Conflict(DomainError):
    def __init__(self, detail: str, code: str = "conflict") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}{code}",
                title="Conflicting request",
                status=409,
                detail=detail,
            )
        )


class PayloadTooLarge(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}payload-too-large",
                title="Payload too large",
                status=413,
                detail=detail,
            )
        )


class UnsupportedMedia(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}unsupported-media-type",
                title="Unsupported media type",
                status=415,
                detail=detail,
            )
        )


class RateLimited(DomainError):
    def __init__(self, detail: str = "Too many requests. Retry later.") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}rate-limited",
                title="Rate limit exceeded",
                status=429,
                detail=detail,
                retryable=True,
            )
        )


class DependencyUnavailable(DomainError):
    """Expensive routes fail closed when a limiter/queue dependency is down."""

    def __init__(self, detail: str = "A required dependency is unavailable.") -> None:
        super().__init__(
            ProblemDetail(
                type=f"{_BASE}dependency-unavailable",
                title="Service unavailable",
                status=503,
                detail=detail,
                retryable=True,
            )
        )
