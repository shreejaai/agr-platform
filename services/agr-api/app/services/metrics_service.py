"""Prometheus metrics for AGR API.

Counters and histograms are registered once at module import time.
The /metrics endpoint exposes them in Prometheus text format.

Counter naming follows Prometheus conventions:
  agr_evaluations_total{decision="ALLOW|DENY|APPROVAL_REQUIRED"}
  agr_risk_score_bucket{le="..."}
  agr_approval_decisions_total{decision="approved|rejected"}
  agr_policy_changes_total{operation="create|update|delete"}
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# Use a custom registry so we don't accidentally expose default process metrics
# in multi-process / gunicorn setups.
_registry = CollectorRegistry()

evaluations_total = Counter(
    "agr_evaluations_total",
    "Total evaluation requests by decision",
    ["decision"],
    registry=_registry,
)

risk_score_histogram = Histogram(
    "agr_risk_score",
    "Distribution of risk scores (0-100)",
    buckets=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    registry=_registry,
)

approval_decisions_total = Counter(
    "agr_approval_decisions_total",
    "Total approval decisions",
    ["decision"],
    registry=_registry,
)

policy_changes_total = Counter(
    "agr_policy_changes_total",
    "Total policy create/update/delete operations",
    ["operation"],
    registry=_registry,
)

webhook_deliveries_total = Counter(
    "agr_webhook_deliveries_total",
    "Total webhook delivery attempts",
    ["status"],
    registry=_registry,
)


def record_evaluation(decision: str, risk_score: int | None = None) -> None:
    """Increment the evaluation counter and update risk score histogram."""
    evaluations_total.labels(decision=decision).inc()
    if risk_score is not None:
        risk_score_histogram.observe(risk_score)


def record_approval_decision(decision: str) -> None:
    """Increment the approval decision counter."""
    approval_decisions_total.labels(decision=decision).inc()


def record_policy_change(operation: str) -> None:
    """Increment the policy change counter."""
    policy_changes_total.labels(operation=operation).inc()


def record_webhook_delivery(status: str) -> None:
    """Increment the webhook delivery counter."""
    webhook_deliveries_total.labels(status=status).inc()


def get_metrics_output() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(_registry), CONTENT_TYPE_LATEST
