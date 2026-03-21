"""Approval email notifications via Resend REST API."""

import hashlib
import hmac
import html
import logging
import time

import httpx

from app.config import settings
from app.models import ApprovalRequest

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY = 48 * 3600  # matches approval expires_at


# ---------------------------------------------------------------------------
# Token signing — two formats supported:
#   v1 (legacy): {id}:{decision}:{expires}:{sig}
#   v2 (current): {id}:{decision}:{expires}:{version}:{sig}
# The version field lets us invalidate tokens when an approval is escalated
# to a different approver, preventing the old approver from acting on a
# stale email link.
# ---------------------------------------------------------------------------


def _sign_v1(approval_id: str, decision: str, expires: int) -> str:
    """Legacy HMAC — no token_version (backward-compat for in-flight emails)."""
    msg = f"{approval_id}:{decision}:{expires}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def _sign_v2(approval_id: str, decision: str, expires: int, token_version: int) -> str:
    """Versioned HMAC — includes token_version so escalation invalidates old tokens."""
    msg = f"{approval_id}:{decision}:{expires}:{token_version}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def make_decision_token(approval_id: str, decision: str, token_version: int = 0) -> str:
    """Return a URL-safe HMAC-signed token for one-click email links (v2 format)."""
    expires = int(time.time()) + _TOKEN_EXPIRY
    sig = _sign_v2(approval_id, decision, expires, token_version)
    return f"{approval_id}:{decision}:{expires}:{token_version}:{sig}"


def verify_decision_token(token: str) -> tuple[str, str, int | None] | None:
    """Verify token. Returns (approval_id, decision, token_version) or None.

    token_version is None for legacy v1 tokens — callers should skip the
    version check in that case to avoid breaking in-flight email links.
    """
    parts = token.split(":")
    if len(parts) == 4:
        # v1 legacy format — accept but don't enforce version
        approval_id, decision, expires_str, sig = parts
        if decision not in ("approved", "rejected"):
            return None
        try:
            expires = int(expires_str)
        except ValueError:
            return None
        if int(time.time()) > expires:
            return None
        if not hmac.compare_digest(sig, _sign_v1(approval_id, decision, expires)):
            return None
        return approval_id, decision, None

    if len(parts) == 5:
        # v2 format — validate version
        approval_id, decision, expires_str, version_str, sig = parts
        if decision not in ("approved", "rejected"):
            return None
        try:
            expires = int(expires_str)
            token_version = int(version_str)
        except ValueError:
            return None
        if int(time.time()) > expires:
            return None
        if not hmac.compare_digest(sig, _sign_v2(approval_id, decision, expires, token_version)):
            return None
        return approval_id, decision, token_version

    return None


async def send_approval_email(approval: ApprovalRequest) -> None:
    """Send one-click approve/reject email. No-ops if Resend is not configured."""
    if not settings.resend_api_key or not approval.approver_email:
        logger.debug(
            "Skipping approval email: resend configured=%s, approver_email=%s",
            bool(settings.resend_api_key),
            bool(approval.approver_email),
        )
        return

    token_ver = getattr(approval, "token_version", 0) or 0
    approve_url = (
        f"{settings.api_base_url}/v1/approvals/decide"
        f"?token={make_decision_token(str(approval.id), 'approved', token_ver)}"
    )
    reject_url = (
        f"{settings.api_base_url}/v1/approvals/decide"
        f"?token={make_decision_token(str(approval.id), 'rejected', token_ver)}"
    )

    # Strip control characters from user-controlled fields to prevent
    # email header injection (M3: newlines in action/resource could inject headers)
    safe_action = approval.action.replace("\r", " ").replace("\n", " ")
    safe_resource = approval.resource.replace("\r", " ").replace("\n", " ")

    payload = {
        "from": "AGR <no-reply@agr.dev>",
        "to": [approval.approver_email],
        "subject": f"[AGR] Approval required: {safe_action} on {safe_resource}",
        "html": _build_html(approval, approve_url, reject_url),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
            resp.raise_for_status()
        logger.info("Approval email sent for %s to %s", approval.id, approval.approver_email)
    except Exception:
        logger.exception("Failed to send approval email for %s", approval.id)


def _build_html(approval: ApprovalRequest, approve_url: str, reject_url: str) -> str:
    # C2: Escape all user-controlled fields before embedding in HTML to prevent XSS
    agent_id = html.escape(str(approval.agent_id))
    action = html.escape(str(approval.action))
    resource = html.escape(str(approval.resource))

    ctx_rows = ""
    if approval.context:
        ctx_rows = "".join(
            f"<tr><td style='padding:4px 8px;color:#6b7280'>{html.escape(str(k))}</td>"
            f"<td style='padding:4px 8px'>{html.escape(str(v))}</td></tr>"
            for k, v in approval.context.items()
        )

    return f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="margin:0 0 16px;color:#111">Action requires your approval</h2>
  <table style="width:100%;border-collapse:collapse;background:#f9fafb;border-radius:6px;
               margin-bottom:24px">
    <tr><td style="padding:8px 12px;color:#6b7280;width:100px">Agent</td>
        <td style="padding:8px 12px">{agent_id}</td></tr>
    <tr><td style="padding:8px 12px;color:#6b7280">Action</td>
        <td style="padding:8px 12px"><strong>{action}</strong></td></tr>
    <tr><td style="padding:8px 12px;color:#6b7280">Resource</td>
        <td style="padding:8px 12px">{resource}</td></tr>
    {ctx_rows}
  </table>
  <div style="margin-bottom:24px">
    <a href="{approve_url}"
       style="background:#16a34a;color:#fff;padding:12px 28px;text-decoration:none;
              border-radius:6px;font-weight:600;margin-right:12px;display:inline-block">
      Approve
    </a>
    <a href="{reject_url}"
       style="background:#dc2626;color:#fff;padding:12px 28px;text-decoration:none;
              border-radius:6px;font-weight:600;display:inline-block">
      Reject
    </a>
  </div>
  <p style="color:#9ca3af;font-size:12px;margin:0">
    Links expire in 48 hours &nbsp;·&nbsp; Approval ID: {html.escape(str(approval.id))}
  </p>
</div>
"""
