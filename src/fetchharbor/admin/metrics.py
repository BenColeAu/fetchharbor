from collections import defaultdict, deque
from dataclasses import dataclass
from html import escape
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

    def record(self, method: str, path: str, status: int, duration_ms: float) -> None:
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
                }
            )

    def snapshot(self) -> dict:
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


async def monitoring_middleware(request: Request, call_next):
    started = monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        metrics.record(
            request.method, request.url.path, status, (monotonic() - started) * 1000
        )
