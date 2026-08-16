from unittest.mock import patch

from fastapi.testclient import TestClient

from fetchharbor.admin.store import AdminConfiguration, ConfigurationStore
from fetchharbor.config import Settings
from fetchharbor.main import app, settings
from fetchharbor.services.scrape import _validate_public_url

client = TestClient(app)


def test_empty_admin_token_file_uses_inline_token() -> None:
    configured = Settings(admin_token="inline-token", admin_token_file="")
    assert configured.resolved_admin_token() == "inline-token"


def test_x402_rejects_placeholder_wallet() -> None:
    try:
        Settings(payment_mode="x402")
    except ValueError as exc:
        assert "receiving wallet" in str(exc)
    else:
        raise AssertionError("x402 accepted the placeholder wallet")


def test_base_mainnet_rejects_testnet_facilitator() -> None:
    try:
        Settings(
            payment_mode="x402",
            x402_network="eip155:8453",
            x402_pay_to="0x1111111111111111111111111111111111111111",
        )
    except ValueError as exc:
        assert "testnet-only" in str(exc)
    else:
        raise AssertionError("Base mainnet accepted the testnet facilitator")


def test_base_mainnet_cdp_facilitator_requires_authentication() -> None:
    try:
        Settings(
            payment_mode="x402",
            x402_network="eip155:8453",
            x402_pay_to="0x1111111111111111111111111111111111111111",
            x402_asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            x402_facilitator="https://api.cdp.coinbase.com/platform/v2/x402",
        )
    except ValueError as exc:
        assert "authentication" in str(exc)
    else:
        raise AssertionError("Base mainnet CDP facilitator accepted missing authentication")


def test_production_proxy_guard_fails_closed() -> None:
    try:
        Settings(env="production", require_outbound_proxy=True, outbound_proxy_url="")
    except ValueError as exc:
        assert "proxy" in str(exc)
    else:
        raise AssertionError("production accepted a missing required proxy")


def test_production_admin_rejects_weak_token() -> None:
    try:
        Settings(env="production", admin_enabled=True, admin_token="too-short")
    except ValueError as exc:
        assert "admin" in str(exc)
    else:
        raise AssertionError("production accepted a weak admin credential")


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["services"] == 3
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").json()["status"] == "ready"


def test_html_to_markdown_get_contract() -> None:
    response = client.get("/html-to-md", params={"html": "<h1>Hello</h1>"})
    assert response.status_code == 200
    assert response.json()["markdown"] == "# Hello"


def test_discovery_contains_six_route_entries() -> None:
    response = client.get("/.well-known/x402.json")
    assert response.status_code == 200
    assert response.json()["x402Version"] == 2
    assert len(response.json()["resources"]) == 6


def test_repository_defaults_do_not_contain_original_operator_wallet() -> None:
    response = client.get("/.well-known/x402.json")
    payees = {item["accepts"][0]["payTo"] for item in response.json()["resources"]}
    assert payees == {"0x0000000000000000000000000000000000000000"}


def test_admin_is_disabled_by_default() -> None:
    response = client.get("/admin/api/overview", headers={"X-Admin-Token": "anything"})
    assert response.status_code == 404


def test_admin_requires_token_when_enabled() -> None:
    previous_enabled, previous_token = settings.admin_enabled, settings.admin_token
    settings.admin_enabled, settings.admin_token = (
        True,
        "a-secure-test-token-that-is-long-enough",
    )
    try:
        assert client.get("/admin/api/overview").status_code == 401
        response = client.get(
            "/admin/api/overview", headers={"X-Admin-Token": settings.admin_token}
        )
        assert response.status_code == 200
        assert "metrics" in response.json()
        response = client.put(
            "/admin/api/configuration",
            headers={"X-Admin-Token": settings.admin_token},
            json={"payment_mode": "x402"},
        )
        assert response.status_code == 409
    finally:
        settings.admin_enabled, settings.admin_token = previous_enabled, previous_token


def test_security_headers_are_applied() -> None:
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_price_update_is_deferred_until_restart(tmp_path) -> None:
    config_path = tmp_path / "admin-config.json"
    configured = Settings(
        admin_config_path=config_path,
        audit_log_path=tmp_path / "admin-audit.jsonl",
    )
    store = ConfigurationStore(configured)
    result = store.update(AdminConfiguration(price_scrape_usdc="0.25"), "test")

    assert configured.price_scrape_usdc == "0.01"
    assert result["configuration"]["price_scrape_usdc"] == "0.25"
    assert result["restart_required"] == ["price_scrape_usdc"]

    restarted = Settings(
        admin_config_path=config_path,
        audit_log_path=tmp_path / "admin-audit.jsonl",
    )
    ConfigurationStore(restarted)
    assert restarted.price_scrape_usdc == "0.25"


def test_admin_dashboard_escapes_dynamic_values() -> None:
    previous_enabled = settings.admin_enabled
    settings.admin_enabled = True
    try:
        response = client.get("/admin")
        assert "const esc=" in response.text
        assert "${esc(c.public_url)}" in response.text
    finally:
        settings.admin_enabled = previous_enabled


def test_admin_host_is_enforced_by_the_application() -> None:
    previous_enabled, previous_host = settings.admin_enabled, settings.admin_host
    settings.admin_enabled, settings.admin_host = True, "testserver"
    try:
        assert client.get("/admin", headers={"Host": "localhost"}).status_code == 404
        assert client.get("/admin", headers={"Host": settings.admin_host}).status_code == 200
    finally:
        settings.admin_enabled, settings.admin_host = previous_enabled, previous_host


def test_enforced_proxy_owns_destination_dns_validation() -> None:
    previous_required = settings.require_outbound_proxy
    settings.require_outbound_proxy = True
    try:
        with patch("fetchharbor.services.scrape.socket.getaddrinfo") as resolver:
            _validate_public_url("https://example.com/")
            resolver.assert_not_called()
    finally:
        settings.require_outbound_proxy = previous_required
