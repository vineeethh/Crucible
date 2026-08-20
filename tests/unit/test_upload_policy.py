"""Upload admission policy — checked before any bytes are accepted."""

import pytest

from crucible.domain import MAX_UPLOAD_BYTES, UploadPolicyError, check_upload_policy


def test_valid_csv_is_admitted() -> None:
    assert (
        check_upload_policy(filename="sales.csv", content_type="text/csv", declared_size=1024)
        is None
    )


def test_valid_parquet_is_admitted() -> None:
    assert (
        check_upload_policy(
            filename="sales.parquet",
            content_type="application/vnd.apache.parquet",
            declared_size=1024,
        )
        is None
    )


def test_oversize_is_refused_before_upload() -> None:
    assert (
        check_upload_policy(
            filename="huge.csv", content_type="text/csv", declared_size=MAX_UPLOAD_BYTES + 1
        )
        is UploadPolicyError.TOO_LARGE
    )


def test_empty_is_refused() -> None:
    assert (
        check_upload_policy(filename="x.csv", content_type="text/csv", declared_size=0)
        is UploadPolicyError.EMPTY
    )


@pytest.mark.parametrize(
    "content_type",
    ["application/zip", "application/x-executable", "text/html", "application/json"],
)
def test_disallowed_content_types_are_refused(content_type: str) -> None:
    assert (
        check_upload_policy(filename="x.csv", content_type=content_type, declared_size=10)
        is UploadPolicyError.CONTENT_TYPE_NOT_ALLOWED
    )


@pytest.mark.parametrize("filename", ["payload.zip", "script.sh", "archive.tar.gz", "noext"])
def test_disallowed_extensions_are_refused(filename: str) -> None:
    """Content type alone is not trusted: a .zip declared as text/csv is still
    refused, and the parser is the final authority regardless."""
    assert (
        check_upload_policy(filename=filename, content_type="text/csv", declared_size=10)
        is UploadPolicyError.EXTENSION_NOT_ALLOWED
    )
