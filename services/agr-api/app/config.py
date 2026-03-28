from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://agr:password@localhost:5432/agr_dev"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "dev-secret-key-not-for-production"
    env: str = "development"
    api_base_url: str = "http://localhost:8000"
    dashboard_base_url: str = "http://localhost:4200"
    temporal_host: str = ""
    temporal_namespace: str = "default"
    resend_api_key: str = ""
    slack_bot_token: str = ""
    slack_channel_id: str = ""  # e.g. C0123456789 — channel to post approvals
    slack_signing_secret: str = ""
    slack_team_id: str = ""
    clerk_webhook_secret: str = ""
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""

    # CORS — wildcard mode is supported for bearer-token clients in any env.
    # Browsers reject "*" together with credentialed mode, so wildcard mode
    # automatically disables Access-Control-Allow-Credentials in app.main.
    cors_origins: list[str] = ["*"]

    # Deployment mode
    # "saas"    — multi-tenant, Clerk-managed orgs, hosted by Shreeja AI
    # "onprem"  — single-tenant, license-key auth, self-hosted by client
    deployment_mode: str = "saas"

    # On-prem license key (Ed25519-signed, issued by Shreeja AI)
    # Required when deployment_mode == "onprem". App refuses to start if invalid/expired.
    license_key: str = ""

    # On-prem: name shown in the dashboard and audit logs for the auto-bootstrapped org
    onprem_org_name: str = "My Organization"

    # Risk scoring thresholds — scores are 0-100 (higher = riskier)
    # score <= allow_max  → decision stays ALLOW
    # score <= approval_max → ALLOW is upgraded to APPROVAL_REQUIRED
    # score > approval_max → ALLOW is upgraded to DENY
    risk_thresholds_allow_max: int = 30
    risk_thresholds_approval_max: int = 70
    risk_scoring_enabled: bool = True
    auth_session_ttl_hours: int = 12

    # Webhook delivery — configurable timeout per attempt (seconds)
    webhook_timeout: float = 10.0
    webhook_secret_rotation_hours: int = 24

    cedar_pool_size: int = 4
    cedar_require_cli: bool = False
    rate_limit_per_second: int = 50
    rate_limit_burst: int = 100
    rate_limit_enabled: bool = True
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "agr-api"

    # Copilot (LLM-powered policy assistant) — paid plans only
    anthropic_api_key: str = ""
    copilot_model: str = "claude-sonnet-4-20250514"
    copilot_max_tokens: int = 1024
    copilot_enabled: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def cors_uses_wildcard(self) -> bool:
        return "*" in self.cors_origins

    @property
    def cors_allow_credentials(self) -> bool:
        return not self.cors_uses_wildcard

    def validate_production_settings(self) -> None:
        """Raise RuntimeError for dangerous defaults that must not reach production.

        Called at app startup in main.py lifespan so the process refuses to
        start rather than silently running with insecure config.
        """
        if self.env == "production" and "dev-secret-key" in self.secret_key:
            # S2: a predictable secret_key lets attackers forge approval tokens
            raise RuntimeError(
                "SECRET_KEY must be changed for production. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )


settings = Settings()
