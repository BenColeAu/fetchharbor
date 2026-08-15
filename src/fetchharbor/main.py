from fastapi import FastAPI

from .config import get_settings
from .discovery import x402_manifest
from .registry import ServiceRegistry
from .services import BUILTIN_SERVICES

settings = get_settings()
registry = ServiceRegistry()
for service in BUILTIN_SERVICES:
    registry.register(service)

app = FastAPI(title="FetchHarbor", version="0.1.0", description="Modular x402 content services for self-hosted deployments")
for service in registry.services:
    app.include_router(service.router, tags=[service.name])


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "services": len(registry.services), "payment_mode": settings.payment_mode}


@app.get("/services")
async def services() -> list[dict]:
    catalog = registry.catalog()
    for item in catalog:
        item["price_usdc"] = settings.service_price(item["name"], item["price_usdc"])
    return catalog


@app.get("/.well-known/x402.json")
async def discovery() -> dict:
    return x402_manifest(registry, settings)
