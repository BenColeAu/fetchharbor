import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings


def write_runtime_status(settings: Settings, service_count: int) -> None:
    """Publish a sanitized snapshot for the isolated admin process."""
    path = Path(settings.runtime_status_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "updated_at": datetime.now(UTC).isoformat(),
        "environment": settings.env,
        "service_count": service_count,
        "payment_mode": settings.payment_mode,
        "security_headers_enabled": settings.security_headers_enabled,
        "outbound_proxy_configured": bool(settings.outbound_proxy_url),
        "outbound_proxy_required": settings.require_outbound_proxy,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(status, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_runtime_status(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def runtime_status_is_fresh(status: dict[str, Any] | None) -> bool:
    if not status:
        return False
    try:
        updated_at = datetime.fromisoformat(str(status["updated_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    if updated_at.tzinfo is None:
        return False
    age = datetime.now(UTC) - updated_at.astimezone(UTC)
    return -timedelta(seconds=5) <= age <= timedelta(seconds=90)
