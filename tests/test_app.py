from fastapi.testclient import TestClient

from fetchharbor.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["services"] == 3


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
