from functools import lru_cache
from pathlib import Path
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
    price_scrape_usdc: str = "0.01"
    price_html_to_md_usdc: str = "0.005"
    price_pdf_parse_usdc: str = "0.01"
    max_download_bytes: int = 20 * 1024 * 1024
    request_timeout_seconds: float = 30
    admin_enabled: bool = False
    admin_token: str = ""
    admin_token_file: Path | None = None
    admin_config_path: Path = Path("data/admin-config.json")
    audit_log_path: Path = Path("data/admin-audit.jsonl")
    security_headers_enabled: bool = True
    allowed_hosts: str = "localhost,127.0.0.1,testserver"

    def resolved_admin_token(self) -> str:
        if self.admin_token_file:
            return self.admin_token_file.read_text(encoding="utf-8").strip()
        return self.admin_token

    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    def service_price(self, service_name: str, default: str) -> str:
        key = service_name.replace("-", "_")
        return str(getattr(self, f"price_{key}_usdc", default))


@lru_cache
def get_settings() -> Settings:
    return Settings()
