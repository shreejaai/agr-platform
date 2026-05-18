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

    # Approval SLA — how long pending approvals stay open before expiring.
    # default_sla_hours is used when EvaluateRequest.sla_hours is unset.
    # max_sla_hours caps any caller-supplied SLA to prevent unbounded pending rows.
    default_sla_hours: int = 48
    max_sla_hours: int = 168  # 7 days
    # Hours added to expires_at when an approval is escalated. The new expiry
    # is clamped to created_at + max_sla_hours so escalation cannot extend
    # an approval beyond the absolute SLA ceiling.
    escalation_extension_hours: int = 24

    # Webhook delivery — configurable timeout per attempt (seconds)
    webhook_timeout: float = 10.0
    webhook_secret_rotation_hours: int = 24

    # W3.4 — per-plugin timeout for compliance checks. A plugin exceeding this
    # budget is cancelled and surfaced as a warning-level advisory finding so
    # the evaluation path is never blocked by a slow/hung plugin.
    compliance_plugin_timeout_ms: int = 250

    cedar_pool_size: int = 4
    cedar_require_cli: bool = False
    rate_limit_per_second: int = 50
    rate_limit_burst: int = 100
    rate_limit_enabled: bool = True
    # W3.3 — what to do when Redis is unreachable. "open" allows the request
    # (legacy behaviour, safe for dev); "closed" rejects with 503 + Retry-After
    # to prevent stampedes during a Redis outage. Production should use closed.
    rate_limit_fail_mode: str = "open"
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "agr-api"

    # Request body size cap (bytes). Enforced by BodySizeLimitMiddleware.
    max_request_body_bytes: int = 256 * 1024  # 256 KB

    # Production safety escape hatches. Both default off; setting either to
    # True opts the operator out of the corresponding hard check in
    # validate_production_settings(). Used for staged migrations or test envs
    # that intentionally run in degraded mode.
    allow_cedar_fallback_in_prod: bool = False
    allow_db_only_approvals_in_prod: bool = False

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

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate_production_settings(self) -> None:
        """Raise RuntimeError for dangerous defaults that must not reach production.

        Called at app startup in main.py lifespan so the process refuses to
        start rather than silently running with insecure config. Collects all
        problems and reports them in a single error so operators can fix the
        full set in one pass instead of whack-a-mole.
        """
        if not self.is_production:
            return

        problems: list[str] = []

        if "dev-secret-key" in self.secret_key:
            # S2: a predictable secret_key lets attackers forge approval tokens
            problems.append(
                "SECRET_KEY must be changed for production. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )

        if self.cors_uses_wildcard:
            problems.append(
                "CORS_ORIGINS must not be '*' in production. "
                "Set CORS_ORIGINS to the explicit list of allowed dashboard/app origins."
            )

        if not self.redis_url.strip():
            problems.append(
                "REDIS_URL must be set in production (required for rate limiting, "
                "idempotency, and the evaluate cache). Run a Redis instance and set "
                "REDIS_URL=redis://host:6379."
            )

        if "sqlite" in self.database_url.lower():
            problems.append(
                "DATABASE_URL must point at PostgreSQL in production, not SQLite. "
                "SQLite has no RLS support and is not safe for multi-tenant deployments."
            )

        if not self.cedar_require_cli and not self.allow_cedar_fallback_in_prod:
            problems.append(
                "CEDAR_REQUIRE_CLI must be true in production, or set "
                "ALLOW_CEDAR_FALLBACK_IN_PROD=true to explicitly run the Python regex "
                "fallback (NOT recommended — decisions may differ from Cedar semantics)."
            )

        if self.webhook_timeout > 30:
            problems.append(
                f"WEBHOOK_TIMEOUT={self.webhook_timeout}s is too high for production. "
                "Set WEBHOOK_TIMEOUT to <= 30 to avoid blocking worker threads on "
                "slow receivers."
            )

        if not self.temporal_host.strip() and not self.allow_db_only_approvals_in_prod:
            problems.append(
                "TEMPORAL_HOST must be set in production, or set "
                "ALLOW_DB_ONLY_APPROVALS_IN_PROD=true to explicitly accept the "
                "DB-only fallback (no durable retry, no escalation timers)."
            )

        if self.max_request_body_bytes <= 0 or self.max_request_body_bytes > 10 * 1024 * 1024:
            problems.append(
                f"MAX_REQUEST_BODY_BYTES={self.max_request_body_bytes} is out of range "
                "(must be 1..10485760). 256 KB is the recommended default."
            )

        if self.rate_limit_enabled and self.rate_limit_fail_mode.lower() != "closed":
            problems.append(
                "RATE_LIMIT_FAIL_MODE must be 'closed' in production so that "
                "Redis outages cannot let unbounded traffic bypass quotas. Set "
                "RATE_LIMIT_FAIL_MODE=closed (recommended) or RATE_LIMIT_ENABLED=false."
            )

        if problems:
            joined = "\n  - " + "\n  - ".join(problems)
            raise RuntimeError(
                "Refusing to start: production configuration has "
                f"{len(problems)} problem(s):{joined}"
            )


settings = Settings()
