"""Trace conventions and completeness (master plan §11.1).

A run's trace is assembled from its append-only events (node progression) and
its attempts (plan/code/execute/verify, each carrying model attribution and, for
sandbox spans, the execution attributes). The root span carries the version
metadata that makes a run reproducible: release, model ids, dataset hash, and a
tenant *pseudonym* — never the raw organization id — for anything exported.

"Trace completeness" is the DoD metric: a terminal run must have its config
manifest, its version metadata, node-level events, and a terminal event.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from crucible.domain import TERMINAL_RUN_STATES, RedactionState, RunStatus
from crucible.observability.redaction import export_safe_excerpt

_PSEUDONYM_SALT = "crucible-tenant-pseudonym-v1"


def pseudonymize(organization_id: str) -> str:
    """A stable, non-reversible tenant label for exported traces."""
    return hashlib.sha256((_PSEUDONYM_SALT + organization_id).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Span:
    name: str
    sequence_no: int
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunTraceInput:
    run_id: str
    organization_id: str
    status: str
    config_manifest: dict[str, Any]
    events: list[dict[str, Any]]  # {event_type, payload, sequence_no}
    attempts: list[dict[str, Any]]  # {kind, model_id, exit_class, duration_ms, cost_usd, payload}


@dataclass(frozen=True, slots=True)
class TraceCompleteness:
    complete: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunTrace:
    run_id: str
    tenant_pseudonym: str
    release: str
    model_ids: tuple[str, ...]
    dataset_sha256: str | None
    spans: tuple[Span, ...]
    completeness: TraceCompleteness
    redaction_state: str = RedactionState.REDACTED.value


def build_run_trace(inp: RunTraceInput) -> RunTrace:
    spans: list[Span] = []
    for event in inp.events:
        payload = event.get("payload") or {}
        node = payload.get("node") if isinstance(payload, dict) else None
        name = f"agent.{node}" if node else f"run.{event.get('event_type')}"
        spans.append(
            Span(
                name=name,
                sequence_no=int(event.get("sequence_no", 0)),
                attributes={"event_type": event.get("event_type")},
            )
        )
    for attempt in inp.attempts:
        span_attrs = attempt.get("payload", {})
        attrs = span_attrs.get("span", {}) if isinstance(span_attrs, dict) else {}
        spans.append(
            Span(
                name=f"attempt.{attempt.get('kind')}",
                sequence_no=1000 + len(spans),
                attributes={
                    "model_id": attempt.get("model_id"),
                    "exit_class": attempt.get("exit_class"),
                    "duration_ms": attempt.get("duration_ms"),
                    **(attrs if isinstance(attrs, dict) else {}),
                },
            )
        )

    model_ids = tuple(sorted({str(a.get("model_id")) for a in inp.attempts if a.get("model_id")}))
    manifest = inp.config_manifest or {}
    dataset_sha = manifest.get("dataset_content_sha256")
    completeness = _completeness(inp, model_ids)
    return RunTrace(
        run_id=inp.run_id,
        tenant_pseudonym=pseudonymize(inp.organization_id),
        release=str(manifest.get("release_id", "unknown")),
        model_ids=model_ids,
        dataset_sha256=str(dataset_sha) if dataset_sha else None,
        spans=tuple(spans),
        completeness=completeness,
    )


def _completeness(inp: RunTraceInput, model_ids: tuple[str, ...]) -> TraceCompleteness:
    missing: list[str] = []
    if not inp.config_manifest:
        missing.append("manifest")
    event_types = {e.get("event_type") for e in inp.events}
    has_nodes = any(
        isinstance(e.get("payload"), dict) and e["payload"].get("node") for e in inp.events
    )
    if not has_nodes:
        missing.append("node_trace")
    if RunStatus(inp.status) in TERMINAL_RUN_STATES and "terminal" not in event_types:
        missing.append("terminal_event")
    # Version metadata: a release plus at least one model attribution (unless the
    # run never reached a model — e.g. an early policy denial, which is complete
    # without model spans).
    reached_model = any(a.get("kind") in ("plan", "code") for a in inp.attempts)
    if inp.config_manifest.get("release_id") in (None, "unknown"):
        missing.append("release")
    if reached_model and not model_ids:
        missing.append("model_versions")
    return TraceCompleteness(complete=not missing, missing=tuple(missing))


def export_trace(trace: RunTrace, *, question: str | None = None) -> dict[str, object]:
    """Export-safe trace: tenant pseudonym, hashes, and a bounded question
    excerpt only — no raw org id, no raw prompt, no dataset contents."""
    out: dict[str, object] = {
        "run_id": trace.run_id,
        "tenant": trace.tenant_pseudonym,
        "release": trace.release,
        "model_ids": list(trace.model_ids),
        "dataset_sha256": trace.dataset_sha256,
        "redaction_state": trace.redaction_state,
        "complete": trace.completeness.complete,
        "spans": [
            {"name": s.name, "seq": s.sequence_no, "attributes": s.attributes} for s in trace.spans
        ],
    }
    if question is not None:
        out["question"] = export_safe_excerpt(question).to_dict()
    return out
