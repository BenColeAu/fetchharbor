from decimal import Decimal
from typing import Any

from .config import Settings
from .registry import ServiceRegistry


def bazaar_extensions(service, method: str) -> dict[str, Any]:
    """Build one SDK-validated Bazaar declaration for a service method."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension

    body_type = service.body_types.get(method.upper())
    if body_type is None and method.upper() in {"POST", "PUT", "PATCH"}:
        body_type = "json"
    extensions = declare_discovery_extension(
        input=service.input_example_for(method),
        input_schema=service.input_schema_for(method),
        body_type=body_type,
        output=OutputConfig(
            example=service.output_example,
            schema=service.output_schema or None,
        ),
    )
    # The HTTP middleware normally enriches this at request time. The static
    # manifest has no request context, so declare the known route method here.
    extensions["bazaar"]["info"]["input"]["method"] = method.upper()
    return extensions


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
                    "extensions": bazaar_extensions(service, method),
                }
            )
    return {"x402Version": 2, "resources": resources}
