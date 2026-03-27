from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://agr:password@localhost:5432/agr_dev"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "dev-secret-key-not-for-production"
    env: str = "development"
    api_base_url: str = "http://localhost:8000"
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    resend_api_key: str = ""
    slack_bot_token: str = ""
    slack_channel_id: str = ""  # e.g. C0123456789 — channel to post approvals
    clerk_webhook_secret: str = ""
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""

    # CORS — restrict to known dashboard origin in production.
    # Use ["*"] only for development. On-prem: set to ["https://your-dashboard-domain.com"]
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

    # Copilot (LLM-powered policy assistant) — paid plans only
    anthropic_api_key: str = ""
    copilot_model: str = "claude-sonnet-4-20250514"
    copilot_max_tokens: int = 1024
    copilot_enabled: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}

    def validate_production_settings(self) -> None:
        """Raise RuntimeError for dangerous defaults that must not reach production.

        Called at app startup in main.py lifespan so the process refuses to
        start rather than silently running with insecure config.
        """
        if self.env == "production":
            # S2: a predictable secret_key lets attackers forge approval tokens
            if "dev-secret-key" in self.secret_key:
                raise RuntimeError(
                    "SECRET_KEY must be changed for production. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
            # M5: wildcard CORS allows any website to make credentialed requests
            if self.cors_origins == ["*"]:
                raise RuntimeError(
                    "CORS_ORIGINS must be restricted in production. "
                    "Set CORS_ORIGINS to your dashboard domain(s), e.g. "
                    'CORS_ORIGINS=["https://dashboard.agr.dev"]'
                )


settings = Settings()
