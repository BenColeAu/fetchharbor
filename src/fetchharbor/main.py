import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .admin.metrics import metrics, monitoring_middleware
from .admin.store import ConfigurationStore
from .config import get_settings
from .discovery import x402_manifest
from .payments import install_x402
from .public import render_landing
from .registry import ServiceRegistry
from .runtime_status import write_runtime_status
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
metrics.configure_shared_events(settings.request_event_path, writer=True)
write_runtime_status(settings, len(registry.services))
service_methods = {
    service.path: tuple(method.upper() for method in service.methods)
    for service in registry.services
}


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code != 404:
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html and request.method != "HEAD":
        return HTMLResponse(
            """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="/static/favicon.svg"><title>404 · FetchHarbor</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#08111d;color:#e8f0f7;font:16px system-ui}.card{max-width:560px;padding:40px;border:1px solid #294057;border-radius:16px;background:#101d2c;text-align:center}h1{font-size:64px;margin:0;color:#43d6b5}a{color:#43d6b5}</style></head><body><main class="card"><img src="/static/logo.svg" alt="FetchHarbor" width="210"><h1>404</h1><p>This harbor does not have a route at that address.</p><a href="/">Return to FetchHarbor</a></main></body></html>""",
            status_code=404,
        )
    return JSONResponse({"detail": "Not Found"}, status_code=404)


async def security_headers(request: Request, call_next):
    configuration_store.refresh_live()
    allowed_methods = service_methods.get(request.url.path)
    if allowed_methods and request.method not in allowed_methods:
        response = JSONResponse(
            {"detail": "Method not allowed"},
            status_code=405,
            headers={"Allow": ", ".join(allowed_methods)},
        )
    else:
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
    if request.url.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    if settings.env == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


for service in registry.services:
    app.include_router(service.router, tags=[service.name])
install_x402(app, registry, settings)
# Register monitoring after x402 so middleware-generated payment challenges and
# settlement failures are included in the lightweight request history.
app.middleware("http")(monitoring_middleware)
# Register this after x402 so it remains outside middleware-generated 402
# responses as well as ordinary application responses.
app.middleware("http")(security_headers)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing(request: Request) -> Response:
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
    write_runtime_status(settings, len(registry.services))
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
