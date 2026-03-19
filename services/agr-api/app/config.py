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
    clerk_webhook_secret: str = ""
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
