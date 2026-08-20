"""Exact-cache key computation (master plan Phase 8, §12.3).

The key binds every identity input: tenant, dataset *content* (not id — content
is identity), the full model/router config signature, and the normalized
question. Change any one and the key changes, so a cached answer can never leak
across tenants, datasets, or behavior configurations. The org also scopes the
adapter's SQL lookup — the key is defense in depth, not the only control.

Normalization is deliberately conservative: collapse whitespace only. Case or
wording changes may change meaning ("Region" may be a column), so they miss
rather than false-hit. A miss costs a model call; a false hit costs trust.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def normalize_question(question: str) -> str:
    return " ".join(question.split())


def question_sha256(question: str) -> str:
    return hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()


def config_signature(manifest: dict[str, dict[str, Any]]) -> str:
    """A stable digest of the model gateway manifest (models, prompt/policy
    versions, router policy). Any behavior-changing config yields a new
    signature and therefore a disjoint cache."""
    canonical = json.dumps(manifest, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_cache_key(
    *,
    organization_id: str,
    dataset_sha256: str,
    config_sig: str,
    question: str,
) -> str:
    payload = "\x1f".join(
        ["exact-cache@1", organization_id, dataset_sha256, config_sig, normalize_question(question)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
