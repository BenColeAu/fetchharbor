import hashlib
import hmac
import json
import secrets
from collections import defaultdict, deque
from time import monotonic, time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
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

    cookie_name = "fetchharbor_admin_session"

    def record_failed_attempt(actor: str) -> None:
        now = monotonic()
        attempts = failed_attempts[actor]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many failed admin authentication attempts")
        attempts.append(now)

    def session_cookie() -> str:
        issued = int(time())
        payload = f"{issued}.{secrets.token_urlsafe(24)}"
        signature = hmac.new(
            settings.resolved_admin_token().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payload}.{signature}"

    def valid_session(value: str) -> bool:
        token = settings.resolved_admin_token()
        if not token:
            return False
        try:
            issued_text, nonce, supplied = value.split(".", 2)
            issued = int(issued_text)
        except (TypeError, ValueError):
            return False
        if not nonce or issued > int(time()) + 30:
            return False
        if int(time()) - issued > settings.admin_session_ttl_seconds:
            return False
        payload = f"{issued_text}.{nonce}"
        expected = hmac.new(
            token.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return secrets.compare_digest(supplied, expected)

    def set_session_cookie(response: Response) -> None:
        response.set_cookie(
            cookie_name,
            session_cookie(),
            max_age=settings.admin_session_ttl_seconds,
            httponly=True,
            secure=settings.env == "production",
            samesite="strict",
            path="/admin",
        )

    def authorize(
        request: Request,
        response: Response,
        x_admin_token: str | None = Header(default=None),
    ) -> str:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        actor = request.client.host if request.client else "unknown"
        token = settings.resolved_admin_token()
        header_valid = bool(
            token and x_admin_token and secrets.compare_digest(x_admin_token, token)
        )
        cookie_valid = valid_session(request.cookies.get(cookie_name, ""))
        if not header_valid and not cookie_valid:
            record_failed_attempt(actor)
            raise HTTPException(401, "Invalid admin token")
        failed_attempts[actor].clear()
        request.state.admin_cookie_authenticated = cookie_valid and not header_valid
        if cookie_valid:
            set_session_cookie(response)
        return actor

    def require_same_origin(request: Request) -> None:
        origin = request.headers.get("origin", "")
        parsed = urlparse(origin)
        expected_scheme = (
            "https" if settings.env == "production" else request.url.scheme
        )
        if parsed.scheme != expected_scheme or parsed.hostname != settings.admin_host:
            raise HTTPException(403, "Admin mutation origin is not allowed")

    def require_mutation_origin(request: Request) -> None:
        if getattr(request.state, "admin_cookie_authenticated", False):
            require_same_origin(request)

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

    @router.post("/api/session", include_in_schema=False)
    async def create_session(
        request: Request,
        response: Response,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        actor = request.client.host if request.client else "unknown"
        token = settings.resolved_admin_token()
        if (
            not token
            or not x_admin_token
            or not secrets.compare_digest(x_admin_token, token)
        ):
            record_failed_attempt(actor)
            raise HTTPException(401, "Invalid admin token")
        failed_attempts[actor].clear()
        set_session_cookie(response)
        return {
            "status": "authenticated",
            "expires_in": settings.admin_session_ttl_seconds,
        }

    @router.delete("/api/session", include_in_schema=False)
    async def delete_session(request: Request, response: Response) -> dict:
        require_admin_host(request)
        require_same_origin(request)
        response.delete_cookie(cookie_name, path="/admin")
        return {"status": "signed_out"}

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
            "metrics": metrics.snapshot(settings.request_source_retention_seconds),
            "services": registry.catalog(),
        }

    @router.get("/api/configuration", include_in_schema=False)
    async def configuration(_: str = Depends(authorize)) -> dict:
        return store.current()

    @router.put("/api/configuration", include_in_schema=False)
    async def update_configuration(
        request: Request,
        payload: AdminConfiguration,
        actor: str = Depends(authorize),
    ) -> dict:
        require_mutation_origin(request)
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
        require_mutation_origin(request)
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
            {
                "name": "Request source attribution",
                "status": "pass"
                if settings.request_source_tracking_enabled
                else "warning",
                "detail": (
                    "Cloudflare headers are enabled; keep the origin private."
                    if settings.request_source_proxy == "cloudflare"
                    else "Using the direct network peer address."
                ),
            },
        ]
        return {
            "checks": checks,
            "audit": store.audit_events(),
            "facilitator_credentials": credentials,
        }

    return router
