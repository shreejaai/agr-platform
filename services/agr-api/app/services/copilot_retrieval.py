"""Copilot retrieval (W5.4) — org-scoped context for grounded answers.

Pulls a small number of the most query-relevant records out of the caller's
org (policies, recent audit events, policy test suites) and formats them as
an ``<org_context>`` block that can be spliced into the LLM prompt. This lets
the copilot answer questions like *"why did agent X get denied yesterday on
deploy_prod?"* with actual org data instead of hallucinated examples.

Design notes
------------
The hardening plan calls for pgvector + embeddings. We deliberately ship
**phase 1: lexical retrieval** because:

* it is DB-agnostic (works against SQLite test fixtures and Postgres prod
  with identical code, no migration, no extension dependency);
* the dataset per org is small (tens-to-hundreds of policies, recent audit
  is bounded to the last 100 rows here), so a token-overlap score is
  perfectly serviceable;
* it lets us prove the prompt-splice integration end to end before paying
  the operational cost of pgvector + an embeddings provider.

Phase 2 (deferred, tracked in the W5 plan) can swap the scorer for a
pgvector cosine query without changing the call site or the prompt shape.

Tenant isolation
----------------
Every query is filtered by ``org_id`` AND runs inside the request-scoped
async session that has already set ``app.current_org`` for Postgres RLS.
The retrieval helper never returns cross-tenant data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models import AuditEvent, Policy, PolicyTestSuite

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Hard caps so a noisy org never blows up the prompt.
_MAX_POLICIES = 200
_MAX_AUDIT = 100
_MAX_TEST_SUITES = 50
_TOP_K_DEFAULT = 5
_SNIPPET_CHARS = 400

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
# Stop-words we drop before scoring — generic English plus a handful of words
# that appear in every prompt and would otherwise dominate token overlap.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "is",
        "in",
        "on",
        "for",
        "by",
        "with",
        "why",
        "did",
        "do",
        "does",
        "was",
        "were",
        "be",
        "been",
        "i",
        "we",
        "you",
        "my",
        "our",
        "your",
        "this",
        "that",
        "those",
        "these",
        "it",
        "agent",
        "policy",
        "policies",
        "show",
        "list",
        "tell",
        "me",
        "about",
        "what",
        "how",
        "can",
        "should",
    }
)


@dataclass(frozen=True)
class Snippet:
    """A single retrieved chunk."""

    source: str  # "policy" | "audit" | "test_suite"
    title: str
    body: str
    score: float


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t and t not in _STOP_WORDS}


def _score(query_tokens: set[str], doc: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(doc)
    if not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    if overlap == 0:
        return 0.0
    # Normalise by query length so the score lives in (0, 1].
    return overlap / float(len(query_tokens))


def _truncate(text: str, limit: int = _SNIPPET_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def _load_policies(session: AsyncSession, org_id: uuid.UUID) -> list[Policy]:
    stmt = (
        select(Policy)
        .where(Policy.org_id == org_id)
        .order_by(Policy.updated_at.desc())
        .limit(_MAX_POLICIES)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _load_audit(session: AsyncSession, org_id: uuid.UUID) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.recorded_at.desc())
        .limit(_MAX_AUDIT)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _load_test_suites(session: AsyncSession, org_id: uuid.UUID) -> list[PolicyTestSuite]:
    stmt = (
        select(PolicyTestSuite)
        .where(PolicyTestSuite.org_id == org_id)
        .order_by(PolicyTestSuite.updated_at.desc())
        .limit(_MAX_TEST_SUITES)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _summarise_policy(policy: Policy) -> tuple[str, str]:
    title = f"policy: {policy.name} ({policy.state}, level={policy.level})"
    body = policy.cedar_rule
    return title, body


def _summarise_audit(event: AuditEvent) -> tuple[str, str]:
    title = (
        f"audit: agent={event.agent_id} action={event.action} "
        f"resource={event.resource} decision={event.decision}"
    )
    payload = event.payload or {}
    reason = ""
    if isinstance(payload, dict):
        raw_reason = payload.get("reason") or payload.get("explanation")
        if isinstance(raw_reason, str):
            reason = raw_reason
    body_parts = [
        f"recorded_at={event.recorded_at.isoformat() if event.recorded_at else 'n/a'}",
    ]
    if reason:
        body_parts.append(f"reason={reason}")
    body = " | ".join(body_parts)
    return title, body


def _summarise_test_suite(suite: PolicyTestSuite) -> tuple[str, str]:
    title = f"test_suite: {suite.name}"
    description = suite.description or ""
    # Test cases are a list of dicts; flatten the case names + expected
    # decisions so the LLM can spot regressions referenced by name.
    case_summaries: list[str] = []
    cases = suite.test_cases if isinstance(suite.test_cases, list) else []
    for raw in cases[:20]:
        if not isinstance(raw, dict):
            continue
        case_name = str(raw.get("name", "case"))
        expected = str(raw.get("expected_decision", raw.get("expected", "")))
        case_summaries.append(f"- {case_name}: expects {expected}")
    body = description
    if case_summaries:
        joined = "\n".join(case_summaries)
        body = f"{description}\n{joined}" if description else joined
    return title, body


async def retrieve_org_context(
    session: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    top_k: int = _TOP_K_DEFAULT,
) -> str:
    """Return a formatted ``<org_context>`` block, or ``""`` when nothing matches.

    The block is safe to splice verbatim into the user message; it never
    contains data from another org because every underlying load is filtered
    by ``org_id`` (and Postgres RLS provides defence in depth).
    """

    if not query or not query.strip():
        return ""

    query_tokens = _tokens(query)
    if not query_tokens:
        return ""

    try:
        policies = await _load_policies(session, org_id)
        audit = await _load_audit(session, org_id)
        suites = await _load_test_suites(session, org_id)
    except Exception:  # pragma: no cover — advisory, must not break copilot
        logger.exception("copilot retrieval failed; returning empty context")
        return ""

    scored: list[Snippet] = []

    for p in policies:
        title, body = _summarise_policy(p)
        scored.append(
            Snippet(
                source="policy",
                title=title,
                body=body,
                score=_score(query_tokens, f"{title}\n{body}"),
            )
        )

    for e in audit:
        title, body = _summarise_audit(e)
        scored.append(
            Snippet(
                source="audit",
                title=title,
                body=body,
                score=_score(query_tokens, f"{title}\n{body}"),
            )
        )

    for s in suites:
        title, body = _summarise_test_suite(s)
        scored.append(
            Snippet(
                source="test_suite",
                title=title,
                body=body,
                score=_score(query_tokens, f"{title}\n{body}"),
            )
        )

    relevant = [s for s in scored if s.score > 0]
    if not relevant:
        return ""

    relevant.sort(key=lambda s: s.score, reverse=True)
    top = relevant[:top_k]

    return _format_context_block(top)


def _format_context_block(snippets: Sequence[Snippet]) -> str:
    lines = [
        "<org_context>",
        (
            "The following records belong to the caller's organization and were "
            "selected because they appear relevant to the question. Use them as "
            "ground truth; do not invent details."
        ),
    ]
    for snip in snippets:
        lines.append("")
        lines.append(f"[{snip.source}] {snip.title}")
        lines.append(_truncate(snip.body))
    lines.append("</org_context>")
    return "\n".join(lines)


def augment_user_message(user_message: str, org_context: str) -> str:
    """Prepend the retrieved context block to the user message."""
    if not org_context:
        return user_message
    return f"{org_context}\n\nUser question:\n{user_message}"


__all__ = [
    "Snippet",
    "augment_user_message",
    "retrieve_org_context",
]
