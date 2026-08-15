from decimal import Decimal

from .config import Settings
from .registry import ServiceRegistry


def install_x402(app, registry: ServiceRegistry, settings: Settings) -> None:
    """Install the official x402 v2 resource-server middleware when enabled."""
    if settings.payment_mode != "x402":
        return

    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.schemas import AssetAmount
    from x402.server import x402ResourceServer

    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(url=settings.x402_facilitator)
    )
    server = x402ResourceServer(facilitator)
    if settings.x402_network.startswith("eip155:"):
        server.register(settings.x402_network, ExactEvmServerScheme())
    else:
        raise ValueError(
            "This build currently supports EVM x402 networks only; keep payment disabled for Solana"
        )

    routes = {}
    for service in registry.services:
        price = settings.service_price(service.name, service.price_usdc)
        amount = str(int(Decimal(price) * (10**settings.x402_asset_decimals)))
        for method in service.methods:
            routes[f"{method} {service.path}"] = RouteConfig(
                accepts=[
                    PaymentOption(
                        scheme="exact",
                        pay_to=settings.x402_pay_to,
                        price=AssetAmount(
                            amount=amount,
                            asset=settings.x402_asset,
                            extra={
                                "name": settings.x402_asset_name,
                                "version": settings.x402_asset_version,
                            },
                        ),
                        network=settings.x402_network,
                        max_timeout_seconds=settings.x402_max_timeout_seconds,
                    )
                ],
                mime_type="application/json",
                description=service.description,
            )
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
