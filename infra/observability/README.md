# Observability as code

OTel Collector config for local development lives in `infra/compose`
(`otel-collector.yaml`). This directory holds the deployment-facing,
version-controlled observability definitions.

## `alerts.yaml` — alert policies as code (Phase 9)

The alert policies mirror the SLO rules in `crucible.observability.slo` — the
**same thresholds** (trace completeness 0.99, technical completion 0.80,
abstention 0.50, containment 0), so what a provider pages on cannot drift from
what the app computes and the tests exercise
(`tests/unit/test_observability_metrics_trace.py`). Each policy names a
severity, a `for` window, and a runbook.

A provisioner renders `alerts.yaml` into the concrete backend (Cloud Monitoring
alert policies for the GCP reference deployment; Grafana/OTel elsewhere). The
definitions are reviewed like code and are the single source of truth for
alerting — no click-ops alert rules.

Signals are read from the observability plane
(`GET /v1/metrics/{reliability,cost,alerts,cache}`, `/readyz`, and audit rates),
which is derived from run telemetry and carries no raw prompts or dataset
contents (threat T8, redaction boundary).

## Dashboards

The product dashboard (`apps/web /dashboard`) is the live operator view
(reliability, cost/budget, cache safety, firing alerts). Provider dashboards
(Cloud Monitoring / Grafana) are provisioned from the same signals; keep any
committed dashboard JSON alongside `alerts.yaml` so both stay in review.
