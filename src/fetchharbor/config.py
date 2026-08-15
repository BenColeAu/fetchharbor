from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FETCHHARBOR_", env_file=".env", extra="ignore")
    env: Literal["development", "test", "production"] = "development"
    public_url: str = "http://localhost:8080"
    payment_mode: Literal["disabled", "x402"] = "disabled"
    x402_network: str = "eip155:8453"
    x402_pay_to: str = "0x0000000000000000000000000000000000000000"
    x402_asset: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    x402_facilitator: str = "https://x402.org/facilitator"
    max_download_bytes: int = 20 * 1024 * 1024
    request_timeout_seconds: float = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()

