import os
import subprocess
import sys
from unittest.mock import patch

from fetchharbor.config import Settings
from fetchharbor.mainnet_preflight import load_effective_settings


def test_x402_enabled_application_starts() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "FETCHHARBOR_ENV": "test",
            "FETCHHARBOR_PAYMENT_MODE": "x402",
            "FETCHHARBOR_X402_NETWORK": "eip155:84532",
            "FETCHHARBOR_X402_PAY_TO": "0x1111111111111111111111111111111111111111",
        }
    )
    check_script = """import base64
import json
from fastapi.testclient import TestClient
from fetchharbor.admin.metrics import metrics
from fetchharbor.main import app
assert 'PaymentMiddlewareASGI' in [m.cls.__name__ for m in app.user_middleware]
response = TestClient(app).get('/html-to-md', params={'html': '<h1>x</h1>'})
assert response.status_code == 402
assert any(event['status'] == 402 and event['route'] == 'GET /html-to-md' for event in metrics.snapshot()['recent'])
assert 'payment-required' in response.headers
assert response.headers['x-content-type-options'] == 'nosniff'
assert response.headers['x-frame-options'] == 'DENY'
encoded = response.headers['payment-required']
challenge = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4)))
assert challenge['resource']['url'] == 'http://localhost:8080/html-to-md'
bazaar = challenge['extensions']['bazaar']
assert bazaar['info']['input']['method'] == 'GET'
assert bazaar['info']['input']['queryParams']['html'] == '<h1>Hello</h1>'
"""
    completed = subprocess.run(
        [sys.executable, "-c", check_script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_mainnet_preflight_applies_admin_persisted_configuration(tmp_path) -> None:
    config_path = tmp_path / "admin-config.json"
    config_path.write_text(
        """{
  "payment_mode": "x402",
  "x402_network": "eip155:8453",
  "x402_asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  "x402_pay_to": "0x1111111111111111111111111111111111111111",
  "x402_facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
  "x402_facilitator_auth": "cdp"
}""",
        encoding="utf-8",
    )
    configured = Settings(
        env="test",
        admin_config_path=config_path,
        x402_cdp_api_key_id="test-key-id",
        x402_cdp_api_key_secret="test-key-secret",
    )

    with patch("fetchharbor.mainnet_preflight.get_settings", return_value=configured):
        effective = load_effective_settings()

    assert effective.payment_mode == "x402"
    assert effective.x402_network == "eip155:8453"
    assert effective.x402_pay_to == "0x1111111111111111111111111111111111111111"
