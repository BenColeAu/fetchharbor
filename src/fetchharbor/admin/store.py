import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator

from ..config import Settings


class AdminConfiguration(BaseModel):
    public_url: HttpUrl | None = None
    payment_mode: str | None = Field(default=None, pattern="^(disabled|x402)$")
    price_scrape_usdc: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,6})?$")
    price_html_to_md_usdc: str | None = Field(
        default=None, pattern=r"^\d+(\.\d{1,6})?$"
    )
    price_pdf_parse_usdc: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,6})?$")
    price_chat_usdc: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,6})?$")
    max_download_bytes: int | None = Field(default=None, ge=1024, le=100 * 1024 * 1024)
    request_timeout_seconds: float | None = Field(default=None, ge=1, le=300)
    security_headers_enabled: bool | None = None
    x402_pay_to: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")

    @field_validator("x402_pay_to")
    @classmethod
    def receiving_wallet_is_not_zero_address(cls, value: str | None) -> str | None:
        if value and value.lower() == "0x" + ("0" * 40):
            raise ValueError("Receiving wallet must not be the zero address")
        return value


EDITABLE_FIELDS = set(AdminConfiguration.model_fields)
RESTART_REQUIRED_FIELDS = {
    "price_scrape_usdc",
    "price_html_to_md_usdc",
    "price_pdf_parse_usdc",
    "price_chat_usdc",
    "x402_pay_to",
}


class ConfigurationStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings.admin_config_path)
        self.audit_path = Path(settings.audit_log_path)
        self._lock = Lock()
        self.apply(self._read())
        self._active_restart_values = {
            field: getattr(settings, field) for field in RESTART_REQUIRED_FIELDS
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        values = json.loads(self.path.read_text(encoding="utf-8"))
        return AdminConfiguration.model_validate(values).model_dump(
            exclude_none=True, mode="json"
        )

    def current(self) -> dict[str, Any]:
        current = {
            field: str(getattr(self.settings, field))
            if field == "public_url"
            else getattr(self.settings, field)
            for field in EDITABLE_FIELDS
        }
        persisted = self._read()
        for field in RESTART_REQUIRED_FIELDS:
            if field in persisted:
                current[field] = persisted[field]
        current["active_x402_pay_to"] = self._active_restart_values["x402_pay_to"]
        current["pending_restart"] = sorted(
            field
            for field in RESTART_REQUIRED_FIELDS
            if field in persisted
            and persisted[field] != self._active_restart_values[field]
        )
        return current

    def apply(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in EDITABLE_FIELDS and value is not None:
                setattr(self.settings, key, value)

    def update(self, configuration: AdminConfiguration, actor: str) -> dict[str, Any]:
        changes = configuration.model_dump(exclude_none=True, mode="json")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            current = self._read()
            current.update(changes)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(current, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            live_changes = {
                key: value
                for key, value in changes.items()
                if key not in RESTART_REQUIRED_FIELDS
            }
            self.apply(live_changes)
            self._audit(actor, changes)
        return {
            "configuration": self.current(),
            "restart_required": sorted(RESTART_REQUIRED_FIELDS.intersection(changes)),
        }

    def _audit(self, actor: str, changes: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "action": "configuration.update",
            "fields": sorted(changes),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def audit_events(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in reversed(lines)]
