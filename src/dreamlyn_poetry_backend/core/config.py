from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Dreamlyn Poetry Backend"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://poetry:poetry@localhost:5432/poetry"

    jwt_secret: SecretStr = SecretStr("replace-with-at-least-32-random-bytes")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=30, ge=1)
    refresh_cookie_name: str = "poetry_refresh_token"
    refresh_cookie_domain: str | None = None
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    admin_docs_username: str = "admin"
    admin_docs_password: SecretStr = SecretStr("change-me")

    cors_allowed_origins: list[str] = ["http://localhost:5173"]
    litellm_base_url: AnyHttpUrl = AnyHttpUrl("http://litellm-master:4000")
    litellm_model: str = "timur"
    generation_timeout_seconds: float = Field(default=300.0, gt=0)
    s3_download_timeout_seconds: float = Field(default=120.0, gt=0)
    generation_min_duration_seconds: float = Field(default=5.0, gt=0)
    generation_max_duration_seconds: float = Field(default=30.0, gt=0)
    generation_max_prompt_length: int = Field(default=4000, ge=1)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def validate_runtime_secrets(self) -> None:
        jwt_secret = self.jwt_secret.get_secret_value()
        admin_password = self.admin_docs_password.get_secret_value()
        if len(jwt_secret.encode("utf-8")) < 32 or jwt_secret.startswith("replace-with-"):
            raise RuntimeError("JWT_SECRET must contain at least 32 non-placeholder bytes.")
        if admin_password == "change-me":
            raise RuntimeError("ADMIN_DOCS_PASSWORD must not use the example value.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
