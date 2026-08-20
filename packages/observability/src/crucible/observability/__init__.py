"""Crucible observability: redaction, trace conventions, metrics, and SLIs.

Boundary rule (import-linter): imports the domain layer and the standard library
only. It operates on plain records the API/db build for it, so it has no
infrastructure dependency and is fully testable.
"""

from crucible.observability.metrics import (
    CostLatencyMetrics,
    ReliabilityMetrics,
    RunTelemetry,
    cost_latency,
    reliability,
)
from crucible.observability.redaction import (
    Excerpt,
    export_safe_excerpt,
    redact_payload,
    redact_text,
    sha256_text,
)
from crucible.observability.slo import (
    Alert,
    Severity,
    SloThresholds,
    evaluate_slo_alerts,
    firing,
)
from crucible.observability.trace import (
    RunTrace,
    RunTraceInput,
    Span,
    TraceCompleteness,
    build_run_trace,
    export_trace,
    pseudonymize,
)

__all__ = [
    "Alert",
    "CostLatencyMetrics",
    "Excerpt",
    "ReliabilityMetrics",
    "RunTelemetry",
    "RunTrace",
    "RunTraceInput",
    "Severity",
    "SloThresholds",
    "Span",
    "TraceCompleteness",
    "build_run_trace",
    "cost_latency",
    "evaluate_slo_alerts",
    "export_safe_excerpt",
    "export_trace",
    "firing",
    "pseudonymize",
    "redact_payload",
    "redact_text",
    "reliability",
    "sha256_text",
]
