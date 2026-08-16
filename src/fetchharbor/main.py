import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .admin.metrics import metrics, monitoring_middleware
from .admin.router import build_admin_router
from .admin.store import ConfigurationStore
from .config import get_settings
from .discovery import x402_manifest
from .payments import install_x402
from .public import render_landing
from .registry import ServiceRegistry
from .services import configured_services

settings = get_settings()
registry = ServiceRegistry()
for service in configured_services(settings):
    registry.register(service)

app = FastAPI(
    title="FetchHarbor",
    version="0.1.0",
    description="Modular x402 content services for self-hosted deployments",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts())
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)
configuration_store = ConfigurationStore(settings)
app.middleware("http")(monitoring_middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if settings.security_headers_enabled:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'"
            )
    return response


for service in registry.services:
    app.include_router(service.router, tags=[service.name])
install_x402(app, registry, settings)
app.include_router(build_admin_router(settings, registry, metrics, configuration_store))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing(request: Request) -> Response:
    if settings.admin_host and request.url.hostname == settings.admin_host:
        return RedirectResponse(url="/admin", status_code=307)
    return HTMLResponse(render_landing(registry, settings))


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {
        "status": "ok",
        "services": len(registry.services),
        "payment_mode": settings.payment_mode,
    }


@app.get("/health/live", include_in_schema=False)
async def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def readiness() -> dict:
    checked: set[Path] = set()
    for configured_path in (settings.admin_config_path, settings.audit_log_path):
        directory = Path(configured_path).parent.resolve()
        if directory in checked:
            continue
        checked.add(directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory):
                pass
        except OSError as exc:
            raise HTTPException(503, "Persistent storage is not writable") from exc
    return {"status": "ready", "services": len(registry.services)}


@app.get("/services", summary="service catalog", operation_id="list_services")
async def services() -> list[dict]:
    catalog = registry.catalog()
    for item in catalog:
        item["price_usdc"] = settings.service_price(item["name"], item["price_usdc"])
    return catalog


@app.get(
    "/.well-known/x402.json",
    summary="x402 discovery",
    operation_id="x402_discovery",
)
async def discovery() -> dict:
    return x402_manifest(registry, settings)
