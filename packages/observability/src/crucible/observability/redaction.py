"""Redaction boundary (threat model T8).

Nothing raw crosses into a third-party trace/observability provider by default:
no secrets, no PII, no unrestricted dataset contents or prompts. This module
turns a payload into an export-safe form — secrets and PII replaced with typed
markers, free text reduced to a bounded excerpt plus a content hash — so a leak
in the telemetry pipeline cannot disclose sensitive material.

It is deny-by-default about strings: `redact_text` scans for secret and PII
shapes, and `export_safe_excerpt` never emits more than a capped prefix of any
free text (the full value is represented only by its SHA-256).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from crucible.domain import RedactionState

DEFAULT_EXCERPT_CHARS = 120

_SECRET = "[REDACTED:secret]"
_PII = "[REDACTED:pii]"

# Secret shapes: our API keys, common cloud/provider keys, bearer/JWT tokens, and
# credentialed connection URLs. Ordered so the most specific match first.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ck_[0-9a-f]{12}_[A-Za-z0-9_\-]{16,}"),  # Crucible API key
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),  # OpenAI-style key
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),  # GitHub token
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\b"),  # JWT
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s]+"),  # url with user:pass@
    re.compile(r"(?i)\b(?:bearer|token|api[_-]?key|secret|password)\s*[=:]\s*\S+"),
)

_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b(?:\d[ \-]?){13,16}\b"),  # card-like digit runs
    re.compile(r"(?<!\d)(?:\+?\d[ \-]?){10,15}(?!\d)"),  # phone-like
)

# Object keys that must never be exported raw regardless of value.
_SENSITIVE_KEYS = frozenset(
    {
        "secret",
        "secret_hash",
        "password",
        "token",
        "api_key",
        "authorization",
        "source",
        "code_source",
    }
)


@dataclass(frozen=True, slots=True)
class Excerpt:
    excerpt: str
    sha256: str
    length: int
    truncated: bool
    redaction_state: str = RedactionState.REDACTED.value

    def to_dict(self) -> dict[str, object]:
        return {
            "excerpt": self.excerpt,
            "sha256": self.sha256,
            "length": self.length,
            "truncated": self.truncated,
            "redaction_state": self.redaction_state,
        }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact_text(text: str) -> tuple[str, set[str]]:
    """Replace secret/PII shapes with typed markers. Returns (redacted, kinds)."""
    found: set[str] = set()
    out = text
    for pattern in _SECRET_PATTERNS:
        if pattern.search(out):
            found.add("secret")
            out = pattern.sub(_SECRET, out)
    for pattern in _PII_PATTERNS:
        if pattern.search(out):
            found.add("pii")
            out = pattern.sub(_PII, out)
    return out, found


def export_safe_excerpt(text: str, *, max_chars: int = DEFAULT_EXCERPT_CHARS) -> Excerpt:
    """A bounded, redacted excerpt plus the hash of the *original* text. The full
    value is never exported — only enough to recognize it, and its hash to match
    it — so free text (a question, an explanation) cannot leak in bulk."""
    digest = sha256_text(text)
    redacted, _ = redact_text(text)
    truncated = len(redacted) > max_chars
    excerpt = redacted[:max_chars] + ("…" if truncated else "")
    return Excerpt(excerpt=excerpt, sha256=digest, length=len(text), truncated=truncated)


def redact_payload(obj: object) -> object:
    """Recursively redact a JSON-like structure: sensitive keys are dropped to a
    marker, and every string is scanned for secret/PII shapes."""
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for key, value in obj.items():
            if key.lower() in _SENSITIVE_KEYS:
                out[key] = _SECRET if _looks_secretish(key) else _PII
            else:
                out[key] = redact_payload(value)
        return out
    if isinstance(obj, list):
        return [redact_payload(v) for v in obj]
    if isinstance(obj, str):
        redacted, _ = redact_text(obj)
        return redacted
    return obj


def _looks_secretish(key: str) -> bool:
    return any(
        t in key.lower()
        for t in ("secret", "password", "token", "api_key", "authorization", "code", "source")
    )
