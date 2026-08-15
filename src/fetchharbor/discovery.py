from decimal import Decimal
from typing import Any

from .config import Settings
from .registry import ServiceRegistry


def x402_manifest(registry: ServiceRegistry, settings: Settings) -> dict[str, Any]:
    resources = []
    for service in registry.services:
        price = settings.service_price(service.name, service.price_usdc)
        for method in service.methods:
            resources.append(
                {
                    "resource": f"{settings.public_url.rstrip('/')}{service.path}",
                    "type": "http",
                    "x402Version": 2,
                    "description": service.description,
                    "accepts": [
                        {
                            "scheme": "exact",
                            "network": settings.x402_network,
                            "amount": str(
                                int(Decimal(price) * (10**settings.x402_asset_decimals))
                            ),
                            "asset": settings.x402_asset,
                            "payTo": settings.x402_pay_to,
                            "maxTimeoutSeconds": settings.x402_max_timeout_seconds,
                            "extra": {
                                "name": settings.x402_asset_name,
                                "version": settings.x402_asset_version,
                            },
                        }
                    ],
                    "extensions": {
                        "bazaar": {
                            "info": {
                                "input": {"type": "http", "method": method},
                                "output": {
                                    "type": "json",
                                    "example": service.output_example,
                                },
                            },
                            "schema": service.input_schema,
                        }
                    },
                }
            )
    return {"x402Version": 2, "resources": resources}
