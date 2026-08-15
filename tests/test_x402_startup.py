import os
import subprocess
import sys


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
    check_script = """from fastapi.testclient import TestClient
from fetchharbor.main import app
assert 'PaymentMiddlewareASGI' in [m.cls.__name__ for m in app.user_middleware]
response = TestClient(app).get('/html-to-md', params={'html': '<h1>x</h1>'})
assert response.status_code == 402
assert 'payment-required' in response.headers
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
