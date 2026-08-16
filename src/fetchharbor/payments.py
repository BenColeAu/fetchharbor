from decimal import Decimal
from urllib.parse import urlparse

from .config import Settings
from .discovery import bazaar_extensions
from .registry import ServiceRegistry


class CdpFacilitatorAuth:
    """Create short-lived, request-bound CDP bearer tokens for x402 calls."""

    def __init__(self, facilitator_url: str, api_key_id: str, api_key_secret: str):
        parsed = urlparse(facilitator_url)
        self.host = parsed.netloc
        self.base_path = parsed.path.rstrip("/")
        self.api_key_id = api_key_id
        self.api_key_secret = api_key_secret

    def _authorization(self, method: str, endpoint: str) -> dict[str, str]:
        from cdp.auth.utils.jwt import JwtOptions, generate_jwt

        token = generate_jwt(
            JwtOptions(
                api_key_id=self.api_key_id,
                api_key_secret=self.api_key_secret,
                request_method=method,
                request_host=self.host,
                request_path=f"{self.base_path}/{endpoint}",
                expires_in=120,
            )
        )
        return {"Authorization": f"Bearer {token}"}

    def get_auth_headers(self):
        from x402.http import AuthHeaders

        return AuthHeaders(
            verify=self._authorization("POST", "verify"),
            settle=self._authorization("POST", "settle"),
            supported=self._authorization("GET", "supported"),
        )


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

    auth_provider = None
    if settings.x402_facilitator_auth == "cdp":
        auth_provider = CdpFacilitatorAuth(
            settings.x402_facilitator,
            settings.resolved_cdp_api_key_id(),
            settings.resolved_cdp_api_key_secret(),
        )
        # Parse the signing key and prove request-bound JWT generation before
        # the server begins accepting traffic. No network request is made.
        auth_provider.get_auth_headers()
    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(url=settings.x402_facilitator, auth_provider=auth_provider)
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
                resource=f"{settings.public_url.rstrip('/')}{service.path}",
                mime_type="application/json",
                description=service.description,
                extensions=bazaar_extensions(service, method),
            )
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
