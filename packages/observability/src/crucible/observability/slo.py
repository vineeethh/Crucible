"""SLIs and alert rules (master plan §11.3).

Alerts fire on user-impacting symptoms and security events, not on every
transient model failure. Each alert names a severity and a runbook. The rules
are pure functions over the metrics so they can be exercised in tests and in a
staging drill.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from crucible.observability.metrics import ReliabilityMetrics


class Severity(StrEnum):
    SEV1 = "sev1"  # security / containment — page immediately
    SEV2 = "sev2"  # user-impacting reliability
    SEV3 = "sev3"  # degraded, informational


@dataclass(frozen=True, slots=True)
class Alert:
    rule_id: str
    severity: Severity
    firing: bool
    detail: str
    runbook: str


@dataclass(frozen=True, slots=True)
class SloThresholds:
    min_trace_completeness: float = 0.99
    min_technical_completion: float = 0.80
    max_abstention_rate: float = 0.50


def evaluate_slo_alerts(
    reliability: ReliabilityMetrics,
    *,
    thresholds: SloThresholds | None = None,
    containment_breaches: int = 0,
) -> list[Alert]:
    t = thresholds or SloThresholds()
    alerts: list[Alert] = []

    # Security first: any confirmed sandbox containment breach is SEV1.
    alerts.append(
        Alert(
            rule_id="sandbox_containment",
            severity=Severity.SEV1,
            firing=containment_breaches > 0,
            detail=f"{containment_breaches} confirmed containment breach(es)",
            runbook="docs/operations/sandbox-incident-runbook.md",
        )
    )

    if reliability.terminal:
        if reliability.trace_completeness < t.min_trace_completeness:
            alerts.append(
                Alert(
                    rule_id="trace_completeness",
                    severity=Severity.SEV2,
                    firing=True,
                    detail=(
                        f"trace completeness {reliability.trace_completeness} < "
                        f"{t.min_trace_completeness}"
                    ),
                    runbook="docs/operations/alert-runbook.md#trace-completeness",
                )
            )
        if reliability.technical_completion_rate < t.min_technical_completion:
            alerts.append(
                Alert(
                    rule_id="technical_completion",
                    severity=Severity.SEV2,
                    firing=True,
                    detail=(
                        f"technical completion {reliability.technical_completion_rate} < "
                        f"{t.min_technical_completion}"
                    ),
                    runbook="docs/operations/alert-runbook.md#technical-completion",
                )
            )
        abstention_rate = (
            reliability.abstained / reliability.terminal if reliability.terminal else 0.0
        )
        if abstention_rate > t.max_abstention_rate:
            alerts.append(
                Alert(
                    rule_id="abstention_spike",
                    severity=Severity.SEV3,
                    firing=True,
                    detail=f"abstention rate {round(abstention_rate, 3)} > {t.max_abstention_rate}",
                    runbook="docs/operations/alert-runbook.md#abstention-spike",
                )
            )
    return alerts


def firing(alerts: list[Alert]) -> list[Alert]:
    return [a for a in alerts if a.firing]
