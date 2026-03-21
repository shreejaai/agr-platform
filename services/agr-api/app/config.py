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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
