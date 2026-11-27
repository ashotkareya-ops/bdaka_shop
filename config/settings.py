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
    shop_reviews_url: str = "https://t.me/bdaka_reviews"
    shop_news_url: str = "https://t.me/bdaka_store"
    shop_chat_url: str = "https://t.me/+jBNfIlXR13RhNmUy"
    shop_support_url: str = "https://t.me/bdaka1"

    sandromania_base_url: str = "https://api.sandromania.shop"
    sandromania_api_key: str = ""
    sandromania_api_secret: str = ""
    # Admin-only /simulatepay for testing the fulfilment flow without a real payment. Keep OFF in production.
    allow_test_payments: bool = Field(default=False, alias="ALLOW_TEST_PAYMENTS")
    supplier_low_balance_rub: float = Field(default=500.0, alias="SUPPLIER_LOW_BALANCE_RUB")
    api_secret_encryption_key: str = Field(default="", alias="API_SECRET_ENCRYPTION_KEY")
    api_public_url: str = Field(default="", alias="API_PUBLIC_URL")
    sandromania_poll_attempts: int = 8
    sandromania_poll_interval: float = 2.0
    supplier_sync_interval_seconds: int = Field(default=14400, alias="SUPPLIER_SYNC_INTERVAL_SECONDS")

    platega_base_url: str = "https://app.platega.io"
    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_webhook_host: str = "127.0.0.1"
    platega_webhook_port: int = 8080
    platega_webhook_path: str = "/api/payments/platega/webhook"

    # Crypto Pay (Crypto Bot): https://help.crypt.bot/crypto-pay-api
    crypto_pay_token: str = Field(default="", alias="CRYPTO_PAY_TOKEN")
    crypto_pay_testnet: bool = Field(default=False, alias="CRYPTO_PAY_TESTNET")
    # Comma-separated list, e.g. "USDT,TON,BTC". Empty = every asset enabled in your Crypto Pay app.
    crypto_pay_accepted_assets: str = Field(default="USDT,TON", alias="CRYPTO_PAY_ACCEPTED_ASSETS")
    # Fixed USD->RUB rate for balance top-ups. 0 = use the live USDT/RUB rate from Crypto Pay.
    crypto_usd_rub_rate: float = Field(default=0.0, alias="CRYPTO_USD_RUB_RATE")
    crypto_pay_expires_in: int = Field(default=3600, alias="CRYPTO_PAY_EXPIRES_IN")
    crypto_pay_poll_interval: float = Field(default=15.0, alias="CRYPTO_PAY_POLL_INTERVAL")
    crypto_pay_webhook_path: str = Field(
        default="/api/payments/cryptobot/webhook", alias="CRYPTO_PAY_WEBHOOK_PATH"
    )
    # Run the local aiohttp server (webhooks + /health). Not required for Crypto Pay: polling works without it.
    webhook_server_enabled: bool = Field(default=False, alias="WEBHOOK_SERVER_ENABLED")

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
    def crypto_pay_enabled(self) -> bool:
        return bool(self.crypto_pay_token)

    @property
    def crypto_accepted_assets(self) -> list[str]:
        return [a.strip().upper() for a in self.crypto_pay_accepted_assets.split(",") if a.strip()]

    @property
    def sandromania_enabled(self) -> bool:
        return bool(
            self.sandromania_api_key and self.sandromania_api_secret
        )


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
