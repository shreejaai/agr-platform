"""W3.6 — webhook deliveries carry a unique X-AGR-Webhook-Id replay nonce."""

from __future__ import annotations

import uuid

from app.models import Webhook
from app.services.webhook_service import build_signature_headers


def _make_webhook() -> Webhook:
    return Webhook(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        url="https://example.test/hook",
        secret="whsec_abcdefghijklmnopqrstuvwxyz",
        events=["approval.requested"],
        active=True,
    )


def test_build_signature_headers_includes_delivery_nonce() -> None:
    wh = _make_webhook()
    delivery_id = uuid.uuid4()
    headers = build_signature_headers(
        wh, timestamp=1_700_000_000, body="{}", event="approval.requested", delivery_id=delivery_id
    )
    assert headers["X-AGR-Webhook-Id"] == str(delivery_id)
    assert headers["X-AGR-Event"] == "approval.requested"
    assert "X-AGR-Signature" in headers


def test_build_signature_headers_nonce_unique_per_delivery() -> None:
    wh = _make_webhook()
    seen: set[str] = set()
    for _ in range(50):
        delivery_id = uuid.uuid4()
        headers = build_signature_headers(
            wh,
            timestamp=1_700_000_000,
            body="{}",
            event="approval.requested",
            delivery_id=delivery_id,
        )
        nonce = headers["X-AGR-Webhook-Id"]
        assert nonce not in seen
        seen.add(nonce)


def test_build_signature_headers_omits_nonce_when_unset() -> None:
    """Backward-compat: legacy callers without delivery_id still work."""
    wh = _make_webhook()
    headers = build_signature_headers(
        wh, timestamp=1_700_000_000, body="{}", event="approval.requested"
    )
    assert "X-AGR-Webhook-Id" not in headers
