from unittest.mock import patch

from fetchharbor.payments import CdpFacilitatorAuth


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
