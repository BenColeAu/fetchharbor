from unittest.mock import MagicMock, patch

from fastapi import FastAPI

from fetchharbor.config import Settings
from fetchharbor.payments import CdpFacilitatorAuth, install_x402
from fetchharbor.registry import ServiceDefinition, ServiceRegistry


def test_cdp_auth_generates_request_bound_headers() -> None:
    provider = CdpFacilitatorAuth(
        "https://api.cdp.coinbase.com/platform/v2/x402",
        "key-id",
        "key-secret",
    )
    with patch(
        "cdp.auth.utils.jwt.generate_jwt",
        side_effect=["verify-token", "settle-token", "supported-token"],
    ) as generate:
        headers = provider.get_auth_headers()

    assert headers.verify == {"Authorization": "Bearer verify-token"}
    assert headers.settle == {"Authorization": "Bearer settle-token"}
    assert headers.supported == {"Authorization": "Bearer supported-token"}
    calls = generate.call_args_list
    assert calls[0].args[0].request_method == "POST"
    assert calls[0].args[0].request_path == "/platform/v2/x402/verify"
    assert calls[1].args[0].request_path == "/platform/v2/x402/settle"
    assert calls[2].args[0].request_method == "GET"
    assert calls[2].args[0].request_path == "/platform/v2/x402/supported"


def test_cdp_auth_rejects_malformed_signing_key() -> None:
    provider = CdpFacilitatorAuth(
        "https://api.cdp.coinbase.com/platform/v2/x402",
        "key-id",
        "not-a-signing-key",
    )
    try:
        provider.get_auth_headers()
    except ValueError as exc:
        assert "Key must be" in str(exc)
    else:
        raise AssertionError("CDP authentication accepted a malformed signing key")


def test_paid_routes_declare_valid_bazaar_extensions() -> None:
    from x402.extensions.bazaar import (
        validate_discovery_extension,
        validate_discovery_extension_spec,
    )

    registry = ServiceRegistry()
    registry.register(
        ServiceDefinition(
            name="example",
            path="/example",
            description="Example service",
            price_usdc="0.01",
            router=MagicMock(),
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            input_example={"value": "hello"},
            output_example={"result": "hello"},
        )
    )
    configured = Settings(
        payment_mode="x402",
        x402_pay_to="0x1111111111111111111111111111111111111111",
    )
    test_app = FastAPI()
    with patch("x402.server.x402ResourceServer"):
        install_x402(test_app, registry, configured)
    payment_middleware = next(
        item
        for item in test_app.user_middleware
        if item.cls.__name__ == "PaymentMiddlewareASGI"
    )
    captured = payment_middleware.kwargs["routes"]

    assert set(captured) == {"GET /example", "POST /example"}
    for route in captured.values():
        assert route.resource == "http://localhost:8080/example"
        extension = route.extensions["bazaar"]
        assert validate_discovery_extension_spec(extension).valid
        # Runtime enrichment adds the HTTP method before full validation.
        enriched = {
            **extension,
            "info": {
                **extension["info"],
                "input": {**extension["info"]["input"], "method": "GET"},
            },
        }
        if "bodyType" in extension["info"]["input"]:
            enriched["info"]["input"]["method"] = "POST"
        assert validate_discovery_extension(enriched).valid
