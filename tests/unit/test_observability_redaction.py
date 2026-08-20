"""Redaction boundary: secrets and PII never cross into exported telemetry."""

from crucible.observability import export_safe_excerpt, redact_payload, redact_text, sha256_text


def test_crucible_api_key_is_redacted() -> None:
    out, kinds = redact_text("here is ck_0123456789ab_supersecretsecretvalue123 do not leak")
    assert "ck_0123456789ab" not in out
    assert "[REDACTED:secret]" in out
    assert "secret" in kinds


def test_common_provider_secrets_are_redacted() -> None:
    for secret in (
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "postgresql://user:hunter2@db.internal:5432/app",
    ):
        out, kinds = redact_text(f"value {secret} end")
        assert secret not in out, secret
        assert "secret" in kinds


def test_pii_is_redacted() -> None:
    out, kinds = redact_text("contact alice@example.com or 555-12-3456")
    assert "alice@example.com" not in out
    assert "[REDACTED:pii]" in out
    assert "pii" in kinds


def test_export_safe_excerpt_bounds_and_hashes() -> None:
    text = "sensitive question " * 50
    ex = export_safe_excerpt(text, max_chars=40)
    assert ex.truncated
    assert len(ex.excerpt) <= 41  # 40 + ellipsis
    assert ex.length == len(text)
    assert ex.sha256 == sha256_text(text)
    # The full text is not present in the excerpt.
    assert text not in ex.excerpt


def test_excerpt_redacts_before_truncating() -> None:
    ex = export_safe_excerpt("my key is ck_0123456789ab_supersecretsecretvalue and more")
    assert "ck_0123456789ab" not in ex.excerpt


def test_payload_redacts_sensitive_keys_and_nested_strings() -> None:
    payload = {
        "run_id": "abc",
        "secret_hash": "$argon2id$v=19$m=65536",
        "code_source": "import os; os.system('x')",
        "nested": {"note": "email me at bob@example.com", "count": 3},
        "list": ["sk-abcdefghijklmnopqrstuvwxyz012345", "safe"],
    }
    out = redact_payload(payload)
    assert out["run_id"] == "abc"
    assert out["secret_hash"] == "[REDACTED:secret]"
    assert out["code_source"] == "[REDACTED:secret]"
    assert "bob@example.com" not in out["nested"]["note"]
    assert out["nested"]["count"] == 3
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in out["list"][0]


def test_clean_text_is_unchanged() -> None:
    out, kinds = redact_text("What is the total amount by region?")
    assert out == "What is the total amount by region?"
    assert kinds == set()
