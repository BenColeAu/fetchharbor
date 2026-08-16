from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FETCHHARBOR_", env_file=".env", extra="ignore"
    )
    env: Literal["development", "test", "production"] = "development"
    public_url: str = "http://localhost:8080"
    payment_mode: Literal["disabled", "x402"] = "disabled"
    x402_network: str = "eip155:84532"
    x402_pay_to: str = "0x0000000000000000000000000000000000000000"
    x402_asset: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    x402_asset_name: str = "USDC"
    x402_asset_version: str = "2"
    x402_asset_decimals: int = Field(default=6, ge=0, le=18)
    x402_max_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    x402_facilitator: str = "https://x402.org/facilitator"
    x402_facilitator_auth: Literal["none", "cdp"] = "none"
    x402_cdp_api_key_id: str = ""
    x402_cdp_api_key_id_file: Path | None = None
    x402_cdp_api_key_secret: str = ""
    x402_cdp_api_key_secret_file: Path | None = None
    price_scrape_usdc: str = "0.01"
    price_html_to_md_usdc: str = "0.005"
    price_pdf_parse_usdc: str = "0.01"
    max_download_bytes: int = 20 * 1024 * 1024
    request_timeout_seconds: float = 30
    admin_enabled: bool = False
    admin_host: str = ""
    admin_token: str = ""
    admin_token_file: Path | None = None
    admin_config_path: Path = Path("data/admin-config.json")
    audit_log_path: Path = Path("data/admin-audit.jsonl")
    security_headers_enabled: bool = True
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    outbound_proxy_url: str = ""
    require_outbound_proxy: bool = False

    @field_validator(
        "admin_token_file",
        "x402_cdp_api_key_id_file",
        "x402_cdp_api_key_secret_file",
        mode="before",
    )
    @classmethod
    def empty_admin_token_file_is_unset(cls, value):
        return None if value in (None, "") else value

    @model_validator(mode="after")
    def validate_production_guards(self) -> "Settings":
        if self.payment_mode == "x402":
            if self.x402_pay_to == "0x0000000000000000000000000000000000000000":
                raise ValueError("x402 requires a non-placeholder receiving wallet")
            if not self.x402_network.startswith("eip155:"):
                raise ValueError("this build currently supports EVM x402 networks only")
            if not self.x402_pay_to.startswith("0x") or len(self.x402_pay_to) != 42:
                raise ValueError("x402 receiving wallet must be a 20-byte EVM address")
            if not self.x402_asset.startswith("0x") or len(self.x402_asset) != 42:
                raise ValueError("x402 asset must be a 20-byte EVM contract address")
            if self.x402_network == "eip155:8453":
                if self.x402_facilitator.rstrip("/") == "https://x402.org/facilitator":
                    raise ValueError("x402.org facilitator is testnet-only")
                if (
                    self.x402_facilitator.rstrip("/")
                    == "https://api.cdp.coinbase.com/platform/v2/x402"
                    and self.x402_facilitator_auth != "cdp"
                ):
                    raise ValueError("Base mainnet CDP facilitator requires CDP authentication")
            if self.x402_facilitator_auth == "cdp":
                try:
                    key_id = self.resolved_cdp_api_key_id()
                    key_secret = self.resolved_cdp_api_key_secret()
                except OSError as exc:
                    raise ValueError("CDP facilitator credential could not be read") from exc
                if not key_id or not key_secret:
                    raise ValueError("CDP facilitator authentication requires both credentials")
        if (
            self.env == "production"
            and self.require_outbound_proxy
            and not self.outbound_proxy_url
        ):
            raise ValueError(
                "production outbound proxy enforcement is enabled but no proxy URL is configured"
            )
        if self.env == "production" and self.admin_enabled:
            try:
                token = self.resolved_admin_token()
            except OSError as exc:
                raise ValueError(
                    "production admin credential could not be read"
                ) from exc
            if len(token) < 32:
                raise ValueError(
                    "production admin requires a credential of at least 32 characters"
                )
        return self

    def resolved_admin_token(self) -> str:
        if self.admin_token_file:
            return self.admin_token_file.read_text(encoding="utf-8").strip()
        return self.admin_token

    def resolved_cdp_api_key_id(self) -> str:
        if self.x402_cdp_api_key_id_file:
            return self.x402_cdp_api_key_id_file.read_text(encoding="utf-8").strip()
        return self.x402_cdp_api_key_id.strip()

    def resolved_cdp_api_key_secret(self) -> str:
        if self.x402_cdp_api_key_secret_file:
            return self.x402_cdp_api_key_secret_file.read_text(encoding="utf-8").strip()
        return self.x402_cdp_api_key_secret.strip()

    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    def service_price(self, service_name: str, default: str) -> str:
        key = service_name.replace("-", "_")
        return str(getattr(self, f"price_{key}_usdc", default))


@lru_cache
def get_settings() -> Settings:
    return Settings()
