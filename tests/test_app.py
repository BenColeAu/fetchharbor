from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from fetchharbor.admin.metrics import MetricsStore
from fetchharbor.admin.store import AdminConfiguration, ConfigurationStore
from fetchharbor.config import Settings
from fetchharbor.main import app, settings
from fetchharbor.services.scrape import _validate_public_url

client = TestClient(app)


def test_egress_proxy_health_check_requires_a_real_manager_response() -> None:
    configuration = Path("deploy/egress-proxy/squid.conf").read_text(encoding="utf-8")
    compose = Path("compose.production.yaml").read_text(encoding="utf-8")
    assert "http_access allow localhost manager" in configuration
    assert "http_access deny manager" in configuration
    assert "grep -q '^Squid Object Cache:'" in compose


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


def test_service_routes_reject_unsupported_methods_consistently() -> None:
    for path, allowed in {
        "/scrape": "GET, POST",
        "/html-to-md": "GET, POST",
        "/pdf-parse": "GET, POST",
    }.items():
        for method in ("HEAD", "PUT", "PATCH", "DELETE", "TRACE"):
            response = client.request(method, path)
            assert response.status_code == 405
            assert response.headers["allow"] == allowed
            assert response.headers["x-content-type-options"] == "nosniff"
            if method != "HEAD":
                assert response.json() == {"detail": "Method not allowed"}


def test_unknown_service_path_does_not_disclose_method_policy() -> None:
    response = client.head("/not-an-enabled-capability")
    assert response.status_code == 404
    assert "allow" not in response.headers


def test_unknown_api_route_returns_json_404() -> None:
    response = client.get(
        "/not-an-enabled-capability", headers={"Accept": "application/json"}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_unknown_browser_route_returns_branded_html_404() -> None:
    response = client.get("/not-an-enabled-capability", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "FetchHarbor" in response.text
    assert "<h1>404</h1>" in response.text
    assert "admin" not in response.text.lower()


def test_scrape_timeout_fails_closed() -> None:
    with patch(
        "fetchharbor.services.scrape.httpx.AsyncClient",
        side_effect=httpx.TimeoutException("controlled timeout"),
    ):
        response = client.get("/scrape", params={"url": "https://example.com"})
    assert response.status_code == 504
    assert response.json() == {"detail": "Remote request timed out"}


def test_pdf_upload_limit_is_enforced_before_parsing() -> None:
    previous_limit = settings.max_download_bytes
    settings.max_download_bytes = 5
    try:
        response = client.post(
            "/pdf-parse",
            files={"file": ("oversized.pdf", b"123456", "application/pdf")},
        )
        assert response.status_code == 413
        assert response.json() == {"detail": "PDF is too large"}
    finally:
        settings.max_download_bytes = previous_limit


def test_discovery_contains_six_route_entries() -> None:
    response = client.get("/.well-known/x402.json")
    assert response.status_code == 200
    assert response.json()["x402Version"] == 2
    assert len(response.json()["resources"]) == 6
    for resource in response.json()["resources"]:
        extension = resource["extensions"]["bazaar"]
        assert extension["info"]["input"]["method"] in {"GET", "POST"}
        assert extension["schema"]["$schema"].endswith("2020-12/schema")


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
        assert response.status_code == 422
    finally:
        settings.admin_enabled, settings.admin_token, settings.admin_host = (
            previous_enabled,
            previous_token,
            previous_host,
        )


def test_admin_session_survives_refresh_and_protects_mutations() -> None:
    previous = (
        settings.admin_enabled,
        settings.admin_token,
        settings.admin_host,
        settings.env,
    )
    settings.admin_enabled = True
    settings.admin_token = "a-secure-test-token-that-is-long-enough"
    settings.admin_host = "testserver"
    settings.env = "test"
    try:
        with TestClient(app) as session_client:
            login = session_client.post(
                "/admin/api/session",
                headers={"X-Admin-Token": settings.admin_token},
            )
            assert login.status_code == 200
            cookie = login.headers["set-cookie"]
            assert "HttpOnly" in cookie
            assert "SameSite=strict" in cookie
            assert "Path=/admin" in cookie

            refreshed = session_client.get("/admin/api/overview")
            assert refreshed.status_code == 200
            assert "set-cookie" in refreshed.headers

            rejected = session_client.put(
                "/admin/api/configuration", json={"request_timeout_seconds": 30}
            )
            assert rejected.status_code == 403

            accepted = session_client.put(
                "/admin/api/configuration",
                headers={"Origin": "http://testserver"},
                json={"request_timeout_seconds": 30},
            )
            assert accepted.status_code == 200

            signed_out = session_client.delete(
                "/admin/api/session", headers={"Origin": "http://testserver"}
            )
            assert signed_out.status_code == 200
            assert session_client.get("/admin/api/overview").status_code == 401
    finally:
        (
            settings.admin_enabled,
            settings.admin_token,
            settings.admin_host,
            settings.env,
        ) = previous


def test_admin_rejects_tampered_session_cookie() -> None:
    previous = settings.admin_enabled, settings.admin_token, settings.admin_host
    settings.admin_enabled = True
    settings.admin_token = "a-secure-test-token-that-is-long-enough"
    settings.admin_host = "testserver"
    try:
        with TestClient(app) as session_client:
            session_client.cookies.set(
                "fetchharbor_admin_session", "1.fake.invalid", path="/admin"
            )
            assert session_client.get("/admin/api/overview").status_code == 401
    finally:
        settings.admin_enabled, settings.admin_token, settings.admin_host = previous


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


def test_admin_managed_facilitator_credentials_are_not_disclosed(tmp_path) -> None:
    configured = Settings(
        admin_config_path=tmp_path / "admin-config.json",
        audit_log_path=tmp_path / "admin-audit.jsonl",
        admin_managed_secret_dir=tmp_path / "secrets",
    )
    store = ConfigurationStore(configured)
    status = store.update_facilitator_credentials(
        "organizations/test/apiKeys/key-id", "private-secret-value", "test"
    )

    assert status["configured"] is True
    assert status["source"] == "admin"
    assert status["key_id_fingerprint"]
    assert "private-secret-value" not in str(status)
    assert "private-secret-value" not in str(store.audit_events())
    assert configured.resolved_cdp_api_key_secret() == "private-secret-value"


def test_external_facilitator_credentials_cannot_be_replaced(tmp_path) -> None:
    key_id = tmp_path / "external-id"
    key_secret = tmp_path / "external-secret"
    key_id.write_text("external-id", encoding="utf-8")
    key_secret.write_text("external-secret", encoding="utf-8")
    configured = Settings(
        x402_cdp_api_key_id_file=key_id,
        x402_cdp_api_key_secret_file=key_secret,
        admin_config_path=tmp_path / "admin-config.json",
        audit_log_path=tmp_path / "admin-audit.jsonl",
    )
    store = ConfigurationStore(configured)
    assert store.facilitator_credentials_status()["source"] == "external"
    try:
        store.update_facilitator_credentials("replacement", "replacement", "test")
    except ValueError as exc:
        assert "externally managed" in str(exc)
    else:
        raise AssertionError("externally managed credentials were replaced")


def test_complete_payment_configuration_is_validated_and_restart_gated(
    tmp_path,
) -> None:
    configured = Settings(
        admin_config_path=tmp_path / "admin-config.json",
        audit_log_path=tmp_path / "admin-audit.jsonl",
        admin_managed_secret_dir=tmp_path / "secrets",
    )
    store = ConfigurationStore(configured)
    store.update_facilitator_credentials("key-id", "private-key", "test")
    result = store.update(
        AdminConfiguration(
            payment_mode="x402",
            x402_network="eip155:8453",
            x402_asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            x402_pay_to="0x1111111111111111111111111111111111111111",
            x402_facilitator="https://api.cdp.coinbase.com/platform/v2/x402",
            x402_facilitator_auth="cdp",
        ),
        "test",
    )
    assert configured.payment_mode == "disabled"
    assert "payment_mode" in result["restart_required"]

    restarted = Settings(
        admin_config_path=tmp_path / "admin-config.json",
        audit_log_path=tmp_path / "admin-audit.jsonl",
        admin_managed_secret_dir=tmp_path / "secrets",
    )
    ConfigurationStore(restarted)
    assert restarted.payment_mode == "x402"


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
        assert response.headers["cache-control"].startswith("no-store")
        assert 'id="token" type="password"' in response.text
        assert 'autocomplete="off"' in response.text
        assert "Recent incoming requests" in response.text
        assert "refreshed every 10 seconds" in response.text
        assert "o.metrics.recent" in response.text
    finally:
        settings.admin_enabled, settings.admin_host = previous_enabled, previous_host


def test_recent_request_monitoring_is_bounded_and_payload_free() -> None:
    monitoring = MetricsStore()
    for index in range(125):
        monitoring.record("GET", f"/route-{index}", 200, 1.25)

    recent = monitoring.snapshot()["recent"]
    assert len(recent) == 100
    assert recent[0]["route"] == "GET /route-124"
    assert set(recent[0]) == {"route", "status", "duration_ms", "at"}
    assert all("query" not in event and "body" not in event for event in recent)


def test_invalid_facilitator_secret_is_not_reflected(tmp_path) -> None:
    previous_enabled, previous_token, previous_host = (
        settings.admin_enabled,
        settings.admin_token,
        settings.admin_host,
    )
    settings.admin_enabled = True
    settings.admin_token = "a-secure-test-token-that-is-long-enough"
    settings.admin_host = "testserver"
    marker = "DO-NOT-REFLECT-THIS-SECRET"
    try:
        response = client.put(
            "/admin/api/facilitator-credentials",
            headers={"X-Admin-Token": settings.admin_token},
            json={"api_key_id": "key-id", "api_key_secret": marker * 1000},
        )
        assert response.status_code in {413, 422}
        assert marker not in response.text
        assert response.headers["cache-control"].startswith("no-store")
    finally:
        settings.admin_enabled, settings.admin_token, settings.admin_host = (
            previous_enabled,
            previous_token,
            previous_host,
        )


def test_admin_host_is_enforced_by_the_application() -> None:
    previous_enabled, previous_host = settings.admin_enabled, settings.admin_host
    settings.admin_enabled, settings.admin_host = True, "testserver"
    try:
        assert client.get("/admin", headers={"Host": "localhost"}).status_code == 404
        assert client.get("/admin/", headers={"Host": "localhost"}).status_code == 404
        assert (
            client.get("/admin", headers={"Host": settings.admin_host}).status_code
            == 200
        )
        trailing_slash = client.get(
            "/admin/", headers={"Host": settings.admin_host}, follow_redirects=False
        )
        assert trailing_slash.status_code == 307
        assert trailing_slash.headers["location"] == "/admin"
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
