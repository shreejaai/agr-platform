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
    Gauge,
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

# ── W3.1 additions ────────────────────────────────────────────────────────────

evaluate_latency_ms = Histogram(
    "agr_evaluate_latency_ms",
    "End-to-end /v1/evaluate latency in milliseconds",
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
    registry=_registry,
)

cedar_engine_mode_total = Counter(
    "agr_cedar_engine_mode_total",
    "Cedar engine mode used per evaluation",
    ["mode"],
    registry=_registry,
)

cedar_pool_inflight = Gauge(
    "agr_cedar_pool_inflight",
    "Number of Cedar CLI evaluations currently in flight",
    registry=_registry,
)

approval_workflow_fallback_total = Counter(
    "agr_approval_workflow_fallback_total",
    "Approval rows created with a Temporal-fallback mode",
    ["mode"],
    registry=_registry,
)

webhook_delivery_latency_ms = Histogram(
    "agr_webhook_delivery_latency_ms",
    "Webhook delivery latency in milliseconds (POST round-trip)",
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000],
    registry=_registry,
)

audit_chain_break_total = Counter(
    "agr_audit_chain_break_total",
    "Audit chain verifications that returned valid=false",
    registry=_registry,
)

rate_limit_drop_total = Counter(
    "agr_rate_limit_drop_total",
    "Requests dropped with HTTP 429 by the rate limiter",
    registry=_registry,
)

# ── W3.2 additions ────────────────────────────────────────────────────────────

temporal_circuit_state = Gauge(
    "agr_temporal_circuit_state",
    "Temporal client circuit-breaker state (1 if state is active, else 0)",
    ["state"],
    registry=_registry,
)

temporal_circuit_trips_total = Counter(
    "agr_temporal_circuit_trips_total",
    "Number of times the Temporal circuit breaker transitioned to open",
    registry=_registry,
)


def set_temporal_circuit_state(state: str) -> None:
    """Set the temporal circuit breaker gauge so only the active state is 1."""
    for s in ("closed", "open", "half_open"):
        temporal_circuit_state.labels(state=s).set(1.0 if s == state else 0.0)


def record_temporal_circuit_trip() -> None:
    temporal_circuit_trips_total.inc()


def record_evaluate_latency(latency_ms: float) -> None:
    """Observe end-to-end /v1/evaluate latency."""
    evaluate_latency_ms.observe(latency_ms)


def record_cedar_engine_mode(mode: str) -> None:
    """Increment the Cedar engine mode counter."""
    cedar_engine_mode_total.labels(mode=mode).inc()


def record_approval_workflow_fallback(mode: str) -> None:
    """Increment the approval workflow fallback counter."""
    approval_workflow_fallback_total.labels(mode=mode).inc()


def record_webhook_delivery_latency(latency_ms: float) -> None:
    """Observe webhook delivery round-trip latency."""
    webhook_delivery_latency_ms.observe(latency_ms)


def record_audit_chain_break() -> None:
    """Increment the audit chain break counter."""
    audit_chain_break_total.inc()


def record_rate_limit_drop() -> None:
    """Increment the rate-limit drop counter."""
    rate_limit_drop_total.inc()


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
