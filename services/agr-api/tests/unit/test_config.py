from app.config import Settings


def test_validate_production_settings_allows_wildcard_cors_with_real_secret() -> None:
    settings = Settings(
        env="production",
        cors_origins=["*"],
    )
    safe_secret = "replace-me"
    settings.secret_key = safe_secret

    settings.validate_production_settings()


def test_wildcard_cors_disables_credentials() -> None:
    settings = Settings(cors_origins=["*"])

    assert settings.cors_uses_wildcard is True
    assert settings.cors_allow_credentials is False


def test_specific_cors_origins_keep_credentials_enabled() -> None:
    settings = Settings(cors_origins=["https://dashboard.example.com"])

    assert settings.cors_uses_wildcard is False
    assert settings.cors_allow_credentials is True
