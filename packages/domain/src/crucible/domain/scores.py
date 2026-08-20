"""Typed score observations and human-review states.

Scores are stored separately by type and source (metric contract): a boolean
oracle result, a numeric metric, a categorical rubric grade, or free text. The
source records who produced it — a deterministic check, a human reviewer, or the
LLM judge — so a judge score can never be mistaken for ground truth.
"""

from __future__ import annotations

from enum import StrEnum


class ScoreType(StrEnum):
    BOOLEAN = "boolean"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    TEXT = "text"


class ScoreSource(StrEnum):
    DETERMINISTIC = "deterministic"  # an oracle / policy check
    HUMAN = "human"  # a reviewer applying a rubric
    JUDGE = "judge"  # the LLM judge (secondary trend only, never a gate)


class ScoreTargetType(StrEnum):
    RUN = "run"
    ATTEMPT = "attempt"
    EVAL_ITEM = "eval_item"


class ReviewStatus(StrEnum):
    PENDING = "pending"  # waiting for a reviewer to claim
    CLAIMED = "claimed"  # a reviewer holds it
    SUBMITTED = "submitted"  # a decision + rubric scores recorded
    EXPIRED = "expired"  # a claim's SLA lapsed; returned to the queue


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RedactionState(StrEnum):
    """Whether a payload has passed the redaction boundary before leaving the
    trust zone (threat model T8)."""

    RAW = "raw"  # never export
    REDACTED = "redacted"  # secrets/PII removed, content hashed/excerpted
    NONE_NEEDED = "none_needed"  # already only hashes/IDs
