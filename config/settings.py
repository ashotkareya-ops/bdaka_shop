from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    bot_name: str = "BDAKA SHOP"
    admin_ids: str = ""
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = "redis://localhost:6379/0"
    currency: str = "RUB"

    sandromania_base_url: str = "https://api.sandromania.shop"
    sandromania_api_key: str = ""
    sandromania_api_secret: str = ""
    sandromania_poll_attempts: int = 8
    sandromania_poll_interval: float = 2.0

    platega_base_url: str = "https://app.platega.io"
    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_webhook_host: str = "127.0.0.1"
    platega_webhook_port: int = 8080
    platega_webhook_path: str = "/api/payments/platega/webhook"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def admins(self) -> set[int]:
        return {
            int(x.strip())
            for x in self.admin_ids.split(",")
            if x.strip().isdigit()
        }

    @property
    def platega_enabled(self) -> bool:
        return bool(self.platega_merchant_id and self.platega_secret)

    @property
    def sandromania_enabled(self) -> bool:
        return bool(
            self.sandromania_api_key and self.sandromania_api_secret
        )


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
