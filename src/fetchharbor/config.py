from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

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
    # Circle's Base USDC contract signs EIP-3009 authorizations with the
    # EIP-712 domain name "USD Coin".  This is protocol data, not a display
    # label: using "USDC" produces signatures that the contract rejects.
    x402_asset_name: str = "USD Coin"
    x402_asset_version: str = "2"
    x402_asset_decimals: int = Field(default=6, ge=0, le=18)
    x402_max_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    x402_facilitator: str = "https://x402.org/facilitator"
    x402_facilitator_auth: Literal["none", "cdp"] = "none"
    x402_cdp_api_key_id: str = ""
    x402_cdp_api_key_id_file: Path | None = None
    x402_cdp_api_key_secret: str = ""
    x402_cdp_api_key_secret_file: Path | None = None
    admin_managed_secret_dir: Path = Path("data/secrets")
    price_scrape_usdc: str = "0.01"
    price_html_to_md_usdc: str = "0.005"
    price_pdf_parse_usdc: str = "0.01"
    price_chat_usdc: str = "0.01"
    price_audio_speech_usdc: str = "0.04"
    price_audio_transcribe_usdc: str = "0.025"
    price_audio_subtitles_usdc: str = "0.035"
    price_audio_transcribe_summary_usdc: str = "0.05"
    price_audio_convert_usdc: str = "0.015"
    max_download_bytes: int = 20 * 1024 * 1024
    request_timeout_seconds: float = 30
    ollama_enabled: bool = False
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_max_prompt_characters: int = Field(default=8_000, ge=1, le=8_000)
    ollama_max_output_tokens: int = Field(default=512, ge=1, le=32_768)
    ollama_max_concurrency: int = Field(default=2, ge=1, le=128)
    ollama_queue_timeout_seconds: float = Field(default=1, gt=0, le=60)
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    ollama_keep_alive: str = "5m"
    media_enabled: bool = False
    media_worker_url: str = "http://media-worker:8090"
    media_worker_token_file: Path | None = None
    media_max_upload_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024
    )
    media_max_audio_seconds: int = Field(default=300, ge=1, le=900)
    media_max_tts_characters: int = Field(default=2_000, ge=1, le=5_000)
    media_timeout_seconds: float = Field(default=180, gt=0, le=600)
    media_summary_max_characters: int = Field(default=20_000, ge=1, le=40_000)
    admin_enabled: bool = False
    admin_host: str = ""
    admin_token: str = ""
    admin_token_file: Path | None = None
    admin_session_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    admin_config_path: Path = Path("data/admin-config.json")
    audit_log_path: Path = Path("data/admin-audit.jsonl")
    request_event_path: Path = Path("data/request-events.jsonl")
    runtime_status_path: Path = Path("data/runtime-status.json")
    security_headers_enabled: bool = True
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    outbound_proxy_url: str = ""
    require_outbound_proxy: bool = False
    request_source_tracking_enabled: bool = True
    request_source_proxy: Literal["direct", "cloudflare"] = "direct"
    request_source_ip_mode: Literal["full", "masked", "none"] = "masked"
    request_source_retention_seconds: int = Field(default=86400, ge=60, le=604800)

    @field_validator(
        "admin_token_file",
        "x402_cdp_api_key_id_file",
        "x402_cdp_api_key_secret_file",
        "media_worker_token_file",
        mode="before",
    )
    @classmethod
    def empty_admin_token_file_is_unset(cls, value):
        return None if value in (None, "") else value

    @model_validator(mode="after")
    def validate_production_guards(self) -> "Settings":
        if self.ollama_enabled:
            parsed_ollama_url = urlparse(self.ollama_base_url)
            if (
                parsed_ollama_url.scheme not in {"http", "https"}
                or not parsed_ollama_url.hostname
            ):
                raise ValueError("Ollama base URL must be an absolute HTTP(S) URL")
            if not self.ollama_model.strip():
                raise ValueError("Ollama model must not be empty")
        if self.media_enabled:
            parsed_media_url = urlparse(self.media_worker_url)
            if (
                parsed_media_url.scheme not in {"http", "https"}
                or not parsed_media_url.hostname
            ):
                raise ValueError("Media worker URL must be an absolute HTTP(S) URL")
            try:
                media_token = self.resolved_media_worker_token()
            except OSError as exc:
                raise ValueError("Media worker credential could not be read") from exc
            if len(media_token) < 32:
                raise ValueError(
                    "Media worker credential must contain at least 32 characters"
                )
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
                    raise ValueError(
                        "Base mainnet CDP facilitator requires CDP authentication"
                    )
            if self.x402_facilitator_auth == "cdp":
                try:
                    key_id = self.resolved_cdp_api_key_id()
                    key_secret = self.resolved_cdp_api_key_secret()
                except OSError as exc:
                    raise ValueError(
                        "CDP facilitator credential could not be read"
                    ) from exc
                if not key_id or not key_secret:
                    raise ValueError(
                        "CDP facilitator authentication requires both credentials"
                    )
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
        managed = self.admin_managed_secret_dir / "cdp_api_key_id.txt"
        if managed.exists():
            return managed.read_text(encoding="utf-8").strip()
        return self.x402_cdp_api_key_id.strip()

    def resolved_cdp_api_key_secret(self) -> str:
        if self.x402_cdp_api_key_secret_file:
            return self.x402_cdp_api_key_secret_file.read_text(encoding="utf-8").strip()
        managed = self.admin_managed_secret_dir / "cdp_api_key_secret.txt"
        if managed.exists():
            return managed.read_text(encoding="utf-8").strip()
        return self.x402_cdp_api_key_secret.strip()

    def resolved_media_worker_token(self) -> str:
        if self.media_worker_token_file:
            return self.media_worker_token_file.read_text(encoding="utf-8").strip()
        return ""

    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    def service_price(self, service_name: str, default: str) -> str:
        key = service_name.replace("-", "_")
        return str(getattr(self, f"price_{key}_usdc", default))


@lru_cache
def get_settings() -> Settings:
    return Settings()
