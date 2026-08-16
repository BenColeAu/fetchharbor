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
        raise AssertionError(
            "Base mainnet CDP facilitator accepted missing authentication"
        )


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


def test_public_landing_page_explains_the_service() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Useful content in." in response.text
    assert "Capabilities at this harbor" in response.text
    assert "/.well-known/x402.json" in response.text
    assert "/docs" in response.text
    assert "/scrape" in response.text
    assert "/static/logo.svg" in response.text
    assert "<h3>html-to-md</h3>" in response.text
    assert "<h3>pdf-parse</h3>" in response.text
    assert 'href="https://github.com/BenColeAu/fetchharbor"' in response.text
    assert client.get("/static/favicon.svg").status_code == 200


def test_admin_hostname_root_redirects_to_dashboard() -> None:
    previous_host = settings.admin_host
    settings.admin_host = "testserver"
    try:
        response = client.get(
            "/", headers={"Host": settings.admin_host}, follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "/admin"
    finally:
        settings.admin_host = previous_host


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
    previous_enabled, previous_token, previous_host = (
        settings.admin_enabled,
        settings.admin_token,
        settings.admin_host,
    )
    settings.admin_enabled, settings.admin_token, settings.admin_host = (
        True,
        "a-secure-test-token-that-is-long-enough",
        "testserver",
    )
    try:
        assert client.get("/admin/api/overview").status_code == 401
        response = client.get(
            "/admin/api/overview", headers={"X-Admin-Token": settings.admin_token}
        )
        assert response.status_code == 200
        assert "metrics" in response.json()
        assert response.json()["payment"]["network"] == settings.x402_network
        assert response.json()["payment"]["asset"] == settings.x402_asset
        response = client.put(
            "/admin/api/configuration",
            headers={"X-Admin-Token": settings.admin_token},
            json={"payment_mode": "x402"},
        )
        assert response.status_code == 409
    finally:
        settings.admin_enabled, settings.admin_token, settings.admin_host = (
            previous_enabled,
            previous_token,
            previous_host,
        )


def test_security_headers_are_applied() -> None:
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "cdn.jsdelivr.net" not in response.headers["content-security-policy"]


def test_api_docs_csp_allows_only_its_required_external_assets() -> None:
    response = client.get("/docs")
    policy = response.headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in policy
    assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in policy
    assert "connect-src 'self'" in policy


def test_public_openapi_does_not_advertise_admin_capabilities() -> None:
    schema = client.get("/openapi.json").json()
    assert not any(path.startswith("/admin") for path in schema["paths"])
    assert "AdminConfiguration" not in schema.get("components", {}).get("schemas", {})


def test_public_openapi_uses_stable_service_names() -> None:
    schema = client.get("/openapi.json").json()
    expected = {
        ("/scrape", "get"): ("scrape (GET)", "scrape_get"),
        ("/scrape", "post"): ("scrape (POST)", "scrape_post"),
        ("/html-to-md", "get"): ("html-to-md (GET)", "html_to_md_get"),
        ("/html-to-md", "post"): ("html-to-md (POST)", "html_to_md_post"),
        ("/pdf-parse", "get"): ("pdf-parse (GET)", "pdf_parse_get"),
        ("/pdf-parse", "post"): ("pdf-parse (POST)", "pdf_parse_post"),
    }
    if "/chat" in schema["paths"]:
        expected[("/chat", "post")] = ("chat", "chat")
    for (path, method), (summary, operation_id) in expected.items():
        operation = schema["paths"][path][method]
        assert operation["summary"] == summary
        assert operation["operationId"] == operation_id


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


def test_payout_address_update_is_validated_audited_and_restart_required(
    tmp_path,
) -> None:
    config_path = tmp_path / "admin-config.json"
    configured = Settings(
        admin_config_path=config_path,
        audit_log_path=tmp_path / "admin-audit.jsonl",
    )
    store = ConfigurationStore(configured)
    wallet = "0x1111111111111111111111111111111111111111"
    result = store.update(AdminConfiguration(x402_pay_to=wallet), "test")

    assert configured.x402_pay_to != wallet
    assert result["configuration"]["x402_pay_to"] == wallet
    assert result["configuration"]["active_x402_pay_to"] != wallet
    assert result["restart_required"] == ["x402_pay_to"]
    assert store.audit_events()[0]["fields"] == ["x402_pay_to"]

    restarted = Settings(
        admin_config_path=config_path,
        audit_log_path=tmp_path / "admin-audit.jsonl",
    )
    ConfigurationStore(restarted)
    assert restarted.x402_pay_to == wallet


def test_payout_address_rejects_zero_and_malformed_addresses() -> None:
    for address in ("not-a-wallet", "0x" + ("0" * 40)):
        try:
            AdminConfiguration(x402_pay_to=address)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid payout address: {address}")


def test_invalid_persisted_payout_address_blocks_startup(tmp_path) -> None:
    config_path = tmp_path / "admin-config.json"
    config_path.write_text('{"x402_pay_to":"not-a-wallet"}', encoding="utf-8")
    configured = Settings(
        admin_config_path=config_path,
        audit_log_path=tmp_path / "admin-audit.jsonl",
    )
    try:
        ConfigurationStore(configured)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid persisted payout address was accepted")


def test_admin_dashboard_escapes_dynamic_values() -> None:
    previous_enabled, previous_host = settings.admin_enabled, settings.admin_host
    settings.admin_enabled, settings.admin_host = True, "testserver"
    try:
        response = client.get("/admin")
        assert "const esc=" in response.text
        assert "${esc(c.public_url)}" in response.text
        assert 'href="https://github.com/BenColeAu/fetchharbor"' in response.text
    finally:
        settings.admin_enabled, settings.admin_host = previous_enabled, previous_host


def test_admin_host_is_enforced_by_the_application() -> None:
    previous_enabled, previous_host = settings.admin_enabled, settings.admin_host
    settings.admin_enabled, settings.admin_host = True, "testserver"
    try:
        assert client.get("/admin", headers={"Host": "localhost"}).status_code == 404
        assert (
            client.get("/admin", headers={"Host": settings.admin_host}).status_code
            == 200
        )
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
