"""API-key lifecycle primitives.

Token format:  ck_<prefix>_<secret>
  - `prefix` is stored in cleartext and indexed: it identifies which row to
    check, so verification is one indexed lookup plus one Argon2id comparison.
  - `secret` is never stored. Only its Argon2id hash is. The full token is
    shown to the user exactly once (plan §6.3).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

TOKEN_NAMESPACE = "ck"
API_KEY_PREFIX_LEN = 12
_SECRET_BYTES = 32

# Argon2id defaults from argon2-cffi; explicit here so a change is reviewable.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    token: str  # shown once, never persisted
    prefix: str  # persisted, indexed
    secret_hash: str  # persisted


def generate_api_key() -> GeneratedApiKey:
    prefix = secrets.token_hex(API_KEY_PREFIX_LEN // 2)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return GeneratedApiKey(
        token=f"{TOKEN_NAMESPACE}_{prefix}_{secret}",
        prefix=prefix,
        secret_hash=hash_secret(secret),
    )


def split_token(token: str) -> tuple[str, str] | None:
    """Return (prefix, secret) for a well-formed token, else None."""
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_NAMESPACE:
        return None
    prefix, secret = parts[1], parts[2]
    if len(prefix) != API_KEY_PREFIX_LEN or not secret:
        return None
    return prefix, secret


def hash_secret(secret: str) -> str:
    return _hasher.hash(secret)


def verify_secret(secret_hash: str, secret: str) -> bool:
    try:
        return _hasher.verify(secret_hash, secret)
    except (VerifyMismatchError, VerificationError, Exception):
        return False
