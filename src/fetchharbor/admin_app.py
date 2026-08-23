from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .admin.metrics import metrics
from .admin.router import build_admin_router
from .admin.store import ConfigurationStore
from .config import get_settings
from .registry import ServiceRegistry
from .services import configured_services

settings = get_settings()
registry = ServiceRegistry()
for service in configured_services(settings):
    registry.register(service)
configuration_store = ConfigurationStore(settings)
metrics.configure_shared_events(settings.request_event_path, writer=False)

app = FastAPI(
    title="FetchHarbor private administration",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts())
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)
app.include_router(build_admin_router(settings, registry, metrics, configuration_store))


@app.middleware("http")
async def private_admin_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'"
    )
    return response


@app.get("/", include_in_schema=False)
async def admin_root() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=307)
