"""OIDC JWT verification: signature, issuer, audience, and expiry are enforced.

Keys are generated locally, so this runs with no network and no provider.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from crucible.security import JwtVerifier, TokenInvalid

ISSUER = "https://issuer.example.com/"
AUDIENCE = "crucible-api"

_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public = _private.public_key()
_other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _verifier() -> JwtVerifier:
    return JwtVerifier(issuer=ISSUER, audience=AUDIENCE, key_resolver=lambda _token: _public)


def _token(
    *,
    key: rsa.RSAPrivateKey = _private,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: timedelta = timedelta(minutes=5),
    subject: str = "user-123",
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_in,
            "email": "dev@example.com",
            "name": "Dev User",
        },
        key,
        algorithm="RS256",
    )


def test_valid_token_yields_claims() -> None:
    claims = _verifier().verify(_token())
    assert claims.subject == "user-123"
    assert claims.email == "dev@example.com"


def test_token_signed_by_another_key_is_rejected() -> None:
    with pytest.raises(TokenInvalid):
        _verifier().verify(_token(key=_other_private))


def test_wrong_audience_is_rejected() -> None:
    with pytest.raises(TokenInvalid):
        _verifier().verify(_token(audience="some-other-api"))


def test_wrong_issuer_is_rejected() -> None:
    with pytest.raises(TokenInvalid):
        _verifier().verify(_token(issuer="https://evil.example.com/"))


def test_expired_token_is_rejected() -> None:
    with pytest.raises(TokenInvalid):
        _verifier().verify(_token(expires_in=timedelta(minutes=-10)))


def test_unsigned_token_is_rejected() -> None:
    """`alg: none` must never be honored."""
    unsigned = jwt.encode({"sub": "x", "iss": ISSUER, "aud": AUDIENCE}, key="", algorithm="none")
    with pytest.raises(TokenInvalid):
        _verifier().verify(unsigned)


def test_garbage_is_rejected() -> None:
    with pytest.raises(TokenInvalid):
        _verifier().verify("not.a.jwt")
