"""API-key token format, hashing, and verification."""

from crucible.security import (
    API_KEY_PREFIX_LEN,
    generate_api_key,
    hash_secret,
    split_token,
    verify_secret,
)


def test_generated_token_round_trips() -> None:
    key = generate_api_key()
    parts = split_token(key.token)
    assert parts is not None
    prefix, secret = parts
    assert prefix == key.prefix
    assert len(prefix) == API_KEY_PREFIX_LEN
    assert verify_secret(key.secret_hash, secret)


def test_secret_is_not_recoverable_from_the_hash() -> None:
    key = generate_api_key()
    assert key.secret_hash.startswith("$argon2id$")
    _, secret = split_token(key.token)  # type: ignore[misc]
    assert secret not in key.secret_hash


def test_wrong_secret_is_rejected() -> None:
    key = generate_api_key()
    assert not verify_secret(key.secret_hash, "not-the-secret")


def test_verification_never_raises_on_garbage() -> None:
    assert not verify_secret("not-a-hash", "whatever")


def test_two_keys_never_collide() -> None:
    keys = {generate_api_key().prefix for _ in range(50)}
    assert len(keys) == 50


def test_malformed_tokens_are_rejected() -> None:
    assert split_token("") is None
    assert split_token("bearer-token") is None
    assert split_token("xx_abcdef012345_secret") is None  # wrong namespace
    assert split_token("ck_short_secret") is None  # wrong prefix length
    assert split_token(f"ck_{'a' * API_KEY_PREFIX_LEN}_") is None  # empty secret


def test_same_secret_hashes_differently_each_time() -> None:
    """Argon2 salts per hash, so identical secrets have different digests."""
    assert hash_secret("s3cret") != hash_secret("s3cret")
