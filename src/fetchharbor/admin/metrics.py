from collections import defaultdict, deque
from dataclasses import dataclass
from html import escape
from ipaddress import ip_address, ip_network
from threading import Lock
from time import monotonic, time

import psutil
from fastapi import Request


@dataclass
class RouteMetric:
    requests: int = 0
    errors: int = 0
    total_duration_ms: float = 0
    last_status: int = 0
    last_seen: float = 0


class MetricsStore:
    def __init__(self) -> None:
        self.started_at = time()
        self._routes: dict[str, RouteMetric] = defaultdict(RouteMetric)
        self._recent: deque[dict] = deque(maxlen=100)
        self._lock = Lock()

    def record(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        *,
        source_ip: str | None = None,
        country: str | None = None,
        ray_id: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        key = f"{method} {escape(path)}"
        with self._lock:
            metric = self._routes[key]
            metric.requests += 1
            metric.errors += int(status >= 400)
            metric.total_duration_ms += duration_ms
            metric.last_status = status
            metric.last_seen = time()
            self._recent.append(
                {
                    "route": key,
                    "status": status,
                    "duration_ms": round(duration_ms, 2),
                    "at": metric.last_seen,
                    "source_ip": source_ip,
                    "country": country,
                    "ray_id": ray_id,
                    "user_agent": user_agent,
                }
            )

    def snapshot(self, retention_seconds: int | None = None) -> dict:
        process = psutil.Process()
        memory = process.memory_info()
        with self._lock:
            routes = [
                {
                    "route": key,
                    "requests": value.requests,
                    "errors": value.errors,
                    "average_duration_ms": round(
                        value.total_duration_ms / value.requests, 2
                    ),
                    "last_status": value.last_status,
                    "last_seen": value.last_seen,
                }
                for key, value in sorted(self._routes.items())
            ]
            recent = list(reversed(self._recent))
            if retention_seconds is not None:
                cutoff = time() - retention_seconds
                recent = [event for event in recent if event["at"] >= cutoff]
        return {
            "uptime_seconds": round(time() - self.started_at),
            "process": {
                "cpu_percent": process.cpu_percent(),
                "rss_bytes": memory.rss,
                "threads": process.num_threads(),
            },
            "host": {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
            },
            "routes": routes,
            "recent": recent,
        }


metrics = MetricsStore()


def _masked_ip(value: str, mode: str) -> str | None:
    if mode == "none":
        return None
    try:
        parsed = ip_address(value)
    except ValueError:
        return None
    if mode == "full":
        return str(parsed)
    prefix = 24 if parsed.version == 4 else 48
    return str(ip_network(f"{parsed}/{prefix}", strict=False))


def request_source(request: Request, settings) -> dict[str, str | None]:
    if not settings.request_source_tracking_enabled:
        return {"source_ip": None, "country": None, "ray_id": None, "user_agent": None}
    peer = request.client.host if request.client else ""
    candidate = peer
    country = ray_id = None
    if settings.request_source_proxy == "cloudflare":
        forwarded = request.headers.get("cf-connecting-ip", "")
        # Cloudflare overwrites these at its edge. This mode is safe only when the
        # origin is not directly reachable; production Compose enforces that.
        if forwarded:
            candidate = forwarded
        raw_country = request.headers.get("cf-ipcountry", "").upper()
        if (len(raw_country) == 2 and raw_country.isalpha()) or raw_country == "T1":
            country = raw_country
        raw_ray = request.headers.get("cf-ray", "")
        if (
            raw_ray
            and len(raw_ray) <= 128
            and all(c.isalnum() or c in "-_" for c in raw_ray)
        ):
            ray_id = raw_ray
    agent = request.headers.get("user-agent", "")[:160] or None
    return {
        "source_ip": _masked_ip(candidate, settings.request_source_ip_mode),
        "country": country,
        "ray_id": ray_id,
        "user_agent": agent,
    }


async def monitoring_middleware(request: Request, call_next):
    from ..config import get_settings

    started = monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        metrics.record(
            request.method,
            request.url.path,
            status,
            (monotonic() - started) * 1000,
            **request_source(request, get_settings()),
        )
