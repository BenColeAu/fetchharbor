from typing import Any

from .config import Settings
from .registry import ServiceRegistry


def x402_manifest(registry: ServiceRegistry, settings: Settings) -> dict[str, Any]:
    resources = []
    for service in registry.services:
        price = settings.service_price(service.name, service.price_usdc)
        for method in service.methods:
            resources.append({
                "resource": f"{settings.public_url.rstrip('/')}{service.path}",
                "type": "http",
                "x402Version": 2,
                "description": service.description,
                "accepts": [{
                    "scheme": "exact", "network": settings.x402_network,
                    "amount": str(int(float(price) * 1_000_000)),
                    "asset": settings.x402_asset, "payTo": settings.x402_pay_to,
                    "maxTimeoutSeconds": 300,
                    "extra": {"name": "USD Coin", "version": "2"},
                }],
                "extensions": {"bazaar": {"info": {
                    "input": {"type": "http", "method": method},
                    "output": {"type": "json", "example": service.output_example},
                }, "schema": service.input_schema}},
            })
    return {"x402Version": 2, "resources": resources}
