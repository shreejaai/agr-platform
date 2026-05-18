import pytest

from app.config import Settings


def _prod_settings(**overrides: object) -> Settings:
    """Build a Settings instance that passes all production checks by default.

    Tests then mutate one field at a time to assert each guard fires.
    """
    base: dict[str, object] = {
        "env": "production",
        "secret_key": "x" * 64,
        "cors_origins": ["https://dashboard.example.com"],
        "redis_url": "redis://redis:6379",
        "database_url": "postgresql+asyncpg://u:p@db:5432/agr",
        "cedar_require_cli": True,
        "webhook_timeout": 10.0,
        "temporal_host": "temporal:7233",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_validate_production_settings_passes_when_all_checks_satisfied() -> None:
    settings = _prod_settings()
    settings.validate_production_settings()  # must not raise


def test_validate_production_settings_is_noop_outside_production() -> None:
    settings = Settings(env="development")
    settings.validate_production_settings()  # never raises in dev


def test_dev_secret_rejected_in_production() -> None:
    settings = _prod_settings()
    settings.secret_key = "dev-secret-key-not-for-production"
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.validate_production_settings()


def test_wildcard_cors_rejected_in_production() -> None:
    settings = _prod_settings(cors_origins=["*"])
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        settings.validate_production_settings()


def test_empty_redis_rejected_in_production() -> None:
    settings = _prod_settings(redis_url="")
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        settings.validate_production_settings()


def test_sqlite_url_rejected_in_production() -> None:
    settings = _prod_settings(
        database_url="sqlite+aiosqlite:///./test.db",
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.validate_production_settings()


def test_cedar_fallback_rejected_in_production_without_opt_in() -> None:
    settings = _prod_settings(cedar_require_cli=False)
    with pytest.raises(RuntimeError, match="CEDAR_REQUIRE_CLI"):
        settings.validate_production_settings()


def test_cedar_fallback_allowed_with_explicit_opt_in() -> None:
    settings = _prod_settings(
        cedar_require_cli=False,
        allow_cedar_fallback_in_prod=True,
    )
    settings.validate_production_settings()  # must not raise


def test_webhook_timeout_over_30s_rejected() -> None:
    settings = _prod_settings(webhook_timeout=60.0)
    with pytest.raises(RuntimeError, match="WEBHOOK_TIMEOUT"):
        settings.validate_production_settings()


def test_empty_temporal_rejected_in_production_without_opt_in() -> None:
    settings = _prod_settings(temporal_host="")
    with pytest.raises(RuntimeError, match="TEMPORAL_HOST"):
        settings.validate_production_settings()


def test_db_only_approvals_allowed_with_explicit_opt_in() -> None:
    settings = _prod_settings(
        temporal_host="",
        allow_db_only_approvals_in_prod=True,
    )
    settings.validate_production_settings()  # must not raise


def test_multiple_problems_reported_in_single_error() -> None:
    settings = _prod_settings(
        cors_origins=["*"],
        redis_url="",
        cedar_require_cli=False,
    )
    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_production_settings()
    # All three guards must surface in the one message
    msg = str(exc_info.value)
    assert "CORS_ORIGINS" in msg
    assert "REDIS_URL" in msg
    assert "CEDAR_REQUIRE_CLI" in msg
    assert "3 problem(s)" in msg


def test_wildcard_cors_disables_credentials() -> None:
    settings = Settings(cors_origins=["*"])

    assert settings.cors_uses_wildcard is True
    assert settings.cors_allow_credentials is False


def test_specific_cors_origins_keep_credentials_enabled() -> None:
    settings = Settings(cors_origins=["https://dashboard.example.com"])

    assert settings.cors_uses_wildcard is False
    assert settings.cors_allow_credentials is True


def test_max_request_body_bytes_range_enforced() -> None:
    settings = _prod_settings(max_request_body_bytes=0)
    with pytest.raises(RuntimeError, match="MAX_REQUEST_BODY_BYTES"):
        settings.validate_production_settings()

    settings = _prod_settings(max_request_body_bytes=50 * 1024 * 1024)
    with pytest.raises(RuntimeError, match="MAX_REQUEST_BODY_BYTES"):
        settings.validate_production_settings()

