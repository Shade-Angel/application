from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://balancer:balancer@localhost:5432/balancer"
    redis_url: str = "redis://localhost:6379/0"
    ais_url: str = "http://localhost:8001"
    balancer_url: str = "http://localhost:8000"
    webhook_secret: str = "local-demo-secret"
    api_key: str = "local-demo-key"
    worker_concurrency: int = 16
    review_status: str = "await"
    open_statuses: str = "processed,await"
    closed_statuses: str = "accept,reject"
    reassign_only_secondary: bool = True
    reassign_on_deactivate: bool = False
    limit_tz: str = "Europe/Moscow"
    confirm_timeout: int = 15
    max_attempts: int = 5


settings = Settings()
