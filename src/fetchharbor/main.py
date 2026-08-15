from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .admin.metrics import metrics, monitoring_middleware
from .admin.router import build_admin_router
from .admin.store import ConfigurationStore
from .config import get_settings
from .discovery import x402_manifest
from .registry import ServiceRegistry
from .services import BUILTIN_SERVICES

settings = get_settings()
registry = ServiceRegistry()
for service in BUILTIN_SERVICES:
    registry.register(service)

app = FastAPI(
    title="FetchHarbor",
    version="0.1.0",
    description="Modular x402 content services for self-hosted deployments",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts())
configuration_store = ConfigurationStore(settings)
app.middleware("http")(monitoring_middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if settings.security_headers_enabled:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'"
        )
    return response


for service in registry.services:
    app.include_router(service.router, tags=[service.name])
app.include_router(build_admin_router(settings, registry, metrics, configuration_store))


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {
        "status": "ok",
        "services": len(registry.services),
        "payment_mode": settings.payment_mode,
    }


@app.get("/services")
async def services() -> list[dict]:
    catalog = registry.catalog()
    for item in catalog:
        item["price_usdc"] = settings.service_price(item["name"], item["price_usdc"])
    return catalog


@app.get("/.well-known/x402.json")
async def discovery() -> dict:
    return x402_manifest(registry, settings)
