import json
import secrets
from collections import defaultdict, deque
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..config import Settings
from ..registry import ServiceRegistry
from .dashboard import DASHBOARD_HTML
from .metrics import MetricsStore
from .store import AdminConfiguration, ConfigurationStore


def build_admin_router(
    settings: Settings,
    registry: ServiceRegistry,
    metrics: MetricsStore,
    store: ConfigurationStore,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    failed_attempts: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))

    def require_admin_host(request: Request) -> None:
        if settings.admin_host and request.url.hostname != settings.admin_host:
            raise HTTPException(404, "Not found")

    def authorize(
        request: Request, x_admin_token: str | None = Header(default=None)
    ) -> str:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        actor = request.client.host if request.client else "unknown"
        now = monotonic()
        attempts = failed_attempts[actor]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many failed admin authentication attempts")
        token = settings.resolved_admin_token()
        if (
            not token
            or not x_admin_token
            or not secrets.compare_digest(x_admin_token, token)
        ):
            attempts.append(now)
            raise HTTPException(401, "Invalid admin token")
        attempts.clear()
        return actor

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request) -> str:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        return DASHBOARD_HTML

    @router.get("/", include_in_schema=False)
    async def dashboard_with_trailing_slash(request: Request) -> RedirectResponse:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        return RedirectResponse(url="/admin", status_code=307)

    @router.get("/api/overview", include_in_schema=False)
    async def overview(_: str = Depends(authorize)) -> dict:
        return {
            "application": {
                "environment": settings.env,
                "payment_mode": settings.payment_mode,
                "service_count": len(registry.services),
            },
            "payment": {
                "mode": settings.payment_mode,
                "network": settings.x402_network,
                "asset": settings.x402_asset,
                "receiving_wallet": settings.x402_pay_to,
            },
            "metrics": metrics.snapshot(),
            "services": registry.catalog(),
        }

    @router.get("/api/configuration", include_in_schema=False)
    async def configuration(_: str = Depends(authorize)) -> dict:
        return store.current()

    @router.put("/api/configuration", include_in_schema=False)
    async def update_configuration(
        payload: AdminConfiguration, actor: str = Depends(authorize)
    ) -> dict:
        try:
            return store.update(payload, actor)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/facilitator-credentials", include_in_schema=False)
    async def facilitator_credentials(_: str = Depends(authorize)) -> dict:
        return store.facilitator_credentials_status()

    @router.put("/api/facilitator-credentials", include_in_schema=False)
    async def update_facilitator_credentials(
        request: Request, actor: str = Depends(authorize)
    ) -> dict:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 20_480:
                raise HTTPException(413, "Credential payload is too large")
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Credential payload must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(422, "Credential payload must be an object")
        key_id, key_secret = payload.get("api_key_id"), payload.get("api_key_secret")
        if (
            not isinstance(key_id, str)
            or not isinstance(key_secret, str)
            or not 1 <= len(key_id) <= 4096
            or not 1 <= len(key_secret) <= 16384
        ):
            raise HTTPException(
                422,
                "Both facilitator credentials are required and must be within the supported size limits",
            )
        try:
            return store.update_facilitator_credentials(key_id, key_secret, actor)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/security", include_in_schema=False)
    async def security(_: str = Depends(authorize)) -> dict:
        token = settings.resolved_admin_token()
        credentials = store.facilitator_credentials_status()
        checks = [
            {
                "name": "Admin authentication",
                "status": "pass" if len(token) >= 32 else "blocker",
                "detail": "Use a random token of at least 32 characters, preferably from a mounted secret.",
            },
            {
                "name": "Payment enforcement",
                "status": "pass" if settings.payment_mode == "x402" else "warning",
                "detail": "Official x402 v2 middleware is installed; payment changes require restart.",
            },
            {
                "name": "Security headers",
                "status": "pass" if settings.security_headers_enabled else "warning",
                "detail": "Browser hardening headers.",
            },
            {
                "name": "Outbound request policy",
                "status": "pass" if settings.outbound_proxy_url else "warning",
                "detail": "Production should use the restricted egress proxy.",
            },
            {
                "name": "Facilitator credentials",
                "status": "pass" if credentials["configured"] else "warning",
                "detail": "Secrets are never returned by the admin API or included in audit events.",
            },
        ]
        return {
            "checks": checks,
            "audit": store.audit_events(),
            "facilitator_credentials": credentials,
        }

    return router
