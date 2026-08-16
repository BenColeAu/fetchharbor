"""Validate Base mainnet configuration and facilitator access without settling funds."""

from .config import get_settings
from .payments import CdpFacilitatorAuth


def main() -> None:
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient

    settings = get_settings()
    if settings.payment_mode != "x402":
        raise RuntimeError("payment mode must be x402")
    if settings.x402_network != "eip155:8453":
        raise RuntimeError("preflight expects Base mainnet (eip155:8453)")

    auth_provider = None
    if settings.x402_facilitator_auth == "cdp":
        auth_provider = CdpFacilitatorAuth(
            settings.x402_facilitator,
            settings.resolved_cdp_api_key_id(),
            settings.resolved_cdp_api_key_secret(),
        )
    client = HTTPFacilitatorClient(
        FacilitatorConfig(url=settings.x402_facilitator, auth_provider=auth_provider)
    )
    supported = client.get_supported()
    kinds = [kind.model_dump(by_alias=True) for kind in supported.kinds]
    if not any(
        kind.get("scheme") == "exact" and kind.get("network") == settings.x402_network
        for kind in kinds
    ):
        raise RuntimeError(
            "facilitator does not advertise exact payments on Base mainnet"
        )
    print(
        "Mainnet preflight passed without settlement:",
        {
            "network": settings.x402_network,
            "asset": settings.x402_asset,
            "pay_to": settings.x402_pay_to,
            "facilitator": settings.x402_facilitator,
        },
    )


if __name__ == "__main__":
    main()
