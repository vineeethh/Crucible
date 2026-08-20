"""OIDC JWT verification.

The backend verifies signature, issuer, audience, and expiry against the
provider's JWKS (plan §6.3). The frontend never asserts identity.

`JwtVerifier` takes a key-source callable so tests can inject a locally
generated key set without network access, while production uses PyJWKClient
against the provider's `jwks_uri`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]


class TokenInvalid(Exception):
    """Raised for any verification failure. Detail stays internal."""


@dataclass(frozen=True, slots=True)
class OidcClaims:
    subject: str
    issuer: str
    email: str | None = None
    name: str | None = None


class JwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_resolver: Callable[[str], Any],
        algorithms: tuple[str, ...] = ("RS256",),
        leeway_seconds: int = 30,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._key_resolver = key_resolver
        self._algorithms = list(algorithms)
        self._leeway = leeway_seconds

    @classmethod
    def from_jwks_uri(cls, *, issuer: str, audience: str, jwks_uri: str) -> JwtVerifier:
        client = PyJWKClient(jwks_uri, cache_keys=True)

        def resolve(token: str) -> Any:
            return client.get_signing_key_from_jwt(token).key

        return cls(issuer=issuer, audience=audience, key_resolver=resolve)

    def verify(self, token: str) -> OidcClaims:
        try:
            key = self._key_resolver(token)
            payload: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS, "verify_signature": True},
            )
        except Exception as exc:
            raise TokenInvalid(type(exc).__name__) from exc

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise TokenInvalid("missing subject")
        email = payload.get("email")
        name = payload.get("name")
        return OidcClaims(
            subject=subject,
            issuer=str(payload["iss"]),
            email=email if isinstance(email, str) else None,
            name=name if isinstance(name, str) else None,
        )
