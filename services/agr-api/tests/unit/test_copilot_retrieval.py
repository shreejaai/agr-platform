"""Unit tests for the copilot retrieval helper (W5.4).

These exercise the pure-Python scoring + formatting code paths without
touching the database — DB integration is covered separately by the
copilot integration tests.
"""

from __future__ import annotations

from app.services.copilot_retrieval import (
    Snippet,
    _format_context_block,
    _score,
    _tokens,
    augment_user_message,
)


def test_tokens_strips_stop_words_and_lowercases() -> None:
    out = _tokens("Why did Agent deploy_prod_v2 get DENIED?")
    assert "deploy_prod_v2" in out
    assert "denied" in out
    # stop words removed
    assert "why" not in out
    assert "did" not in out
    assert "agent" not in out


def test_score_returns_zero_when_no_overlap() -> None:
    assert _score({"foo"}, "bar baz") == 0.0


def test_score_normalises_by_query_length() -> None:
    query = {"alpha", "beta"}
    # one of two query tokens hits
    assert _score(query, "alpha gamma") == 0.5
    # both hit
    assert _score(query, "alpha beta gamma") == 1.0


def test_format_context_block_includes_all_sources() -> None:
    snippets = [
        Snippet(source="policy", title="policy: foo", body="forbid(...)", score=1.0),
        Snippet(source="audit", title="audit: bar", body="deny reason", score=0.5),
    ]
    block = _format_context_block(snippets)
    assert block.startswith("<org_context>")
    assert block.endswith("</org_context>")
    assert "[policy] policy: foo" in block
    assert "[audit] audit: bar" in block
    assert "forbid(...)" in block


def test_augment_user_message_no_context_returns_original() -> None:
    assert augment_user_message("hello", "") == "hello"


def test_augment_user_message_prepends_context() -> None:
    ctx = "<org_context>stuff</org_context>"
    out = augment_user_message("why?", ctx)
    assert out.startswith(ctx)
    assert "User question:\nwhy?" in out
