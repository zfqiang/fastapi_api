from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "FastAPI Async API"
    database_url: str = (
        "mysql+asyncmy://app:app@localhost:3306/app_db?charset=utf8mb4"
    )
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "local-development-secret-change-before-deploying"
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_allow_credentials: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    auth_rate_limit_requests: int = 10

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.app_env == "production" and (
            self.secret_key == "local-development-secret-change-before-deploying"
            or len(self.secret_key) < 32
        ):
            raise ValueError("Production requires a secret key of at least 32 characters")
        if self.access_token_minutes < 1 or self.refresh_token_days < 1:
            raise ValueError("Token lifetimes must be positive")
        if (
            self.rate_limit_requests < 1
            or self.rate_limit_window_seconds < 1
            or self.auth_rate_limit_requests < 1
        ):
            raise ValueError("Rate limit values must be positive")
        if self.cors_allow_credentials and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins cannot be used with credentials")
        return self


settings = Settings()
