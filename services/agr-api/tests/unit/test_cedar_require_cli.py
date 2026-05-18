"""W1.1 — Cedar require-CLI startup behavior."""

import pytest
from app.config import Settings


def test_validate_prod_requires_cedar_cli_by_default() -> None:
    """In production, cedar_require_cli must be true unless explicitly opted out."""
    settings = Settings(
        env="production",
        secret_key="x" * 64,
        cors_origins=["https://app.example.com"],
        redis_url="redis://r:6379",
        database_url="postgresql+asyncpg://u:p@db:5432/agr",
        cedar_require_cli=False,
        webhook_timeout=10.0,
        temporal_host="t:7233",
        rate_limit_fail_mode="closed",
    )
    with pytest.raises(RuntimeError, match="CEDAR_REQUIRE_CLI"):
        settings.validate_production_settings()


def test_explicit_cedar_fallback_opt_in_clears_check() -> None:
    settings = Settings(
        env="production",
        secret_key="x" * 64,
        cors_origins=["https://app.example.com"],
        redis_url="redis://r:6379",
        database_url="postgresql+asyncpg://u:p@db:5432/agr",
        cedar_require_cli=False,
        allow_cedar_fallback_in_prod=True,
        webhook_timeout=10.0,
        temporal_host="t:7233",
        rate_limit_fail_mode="closed",
    )
    settings.validate_production_settings()  # must not raise
