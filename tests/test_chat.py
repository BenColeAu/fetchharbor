from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from fetchharbor.config import Settings
from fetchharbor.discovery import x402_manifest
from fetchharbor.registry import ServiceRegistry
from fetchharbor.services import configured_services
from fetchharbor.services.chat import _limiters, ollama_chat


class FakeAsyncClient:
    def __init__(self, response: httpx.Response, **_):
        self.response = response
        self.payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, _url: str, json: dict):
        self.payload = json
        return self.response


def response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status, json=body, request=httpx.Request("POST", "http://ollama/api/chat")
    )


def test_chat_service_is_only_registered_when_enabled() -> None:
    assert [service.name for service in configured_services(Settings())] == [
        "scrape",
        "html-to-md",
        "pdf-parse",
    ]
    assert [
        service.name for service in configured_services(Settings(ollama_enabled=True))
    ] == ["scrape", "html-to-md", "pdf-parse", "chat"]


def test_enabled_chat_requires_valid_provider_configuration() -> None:
    with pytest.raises(ValueError, match="base URL"):
        Settings(ollama_enabled=True, ollama_base_url="ollama")
    with pytest.raises(ValueError, match="model"):
        Settings(ollama_enabled=True, ollama_model="")


def test_enabled_chat_is_published_in_discovery() -> None:
    configured = Settings(ollama_enabled=True)
    registry = ServiceRegistry()
    for service in configured_services(configured):
        registry.register(service)

    chat_resources = [
        item
        for item in x402_manifest(registry, configured)["resources"]
        if item["resource"].endswith("/chat")
    ]
    assert len(chat_resources) == 1
    assert (
        chat_resources[0]["extensions"]["bazaar"]["info"]["input"]["method"] == "POST"
    )
    assert chat_resources[0]["accepts"][0]["amount"] == "10000"


@pytest.mark.asyncio
async def test_ollama_chat_returns_bounded_contract() -> None:
    configured = Settings(ollama_enabled=True)
    provider_response = response(
        200,
        {
            "model": "llama3.2:3b",
            "message": {"role": "assistant", "content": "Hello!"},
            "prompt_eval_count": 12,
            "eval_count": 3,
        },
    )
    fake = FakeAsyncClient(provider_response)
    _limiters.clear()
    with (
        patch("fetchharbor.services.chat.get_settings", return_value=configured),
        patch("fetchharbor.services.chat.httpx.AsyncClient", return_value=fake),
    ):
        result = await ollama_chat("Say hello")

    assert result.response == "Hello!"
    assert result.prompt_tokens == 12
    assert fake.payload["stream"] is False
    assert fake.payload["options"]["num_predict"] == 512


@pytest.mark.asyncio
async def test_ollama_chat_fails_closed_on_provider_error() -> None:
    configured = Settings(ollama_enabled=True)
    fake = FakeAsyncClient(response(500, {"error": "model unavailable"}))
    _limiters.clear()
    with (
        patch("fetchharbor.services.chat.get_settings", return_value=configured),
        patch("fetchharbor.services.chat.httpx.AsyncClient", return_value=fake),
        pytest.raises(HTTPException) as error,
    ):
        await ollama_chat("Hello")
    assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_ollama_chat_fails_closed_on_provider_timeout() -> None:
    configured = Settings(ollama_enabled=True)
    _limiters.clear()
    with (
        patch("fetchharbor.services.chat.get_settings", return_value=configured),
        patch(
            "fetchharbor.services.chat.httpx.AsyncClient",
            side_effect=httpx.TimeoutException("controlled timeout"),
        ),
        pytest.raises(HTTPException) as error,
    ):
        await ollama_chat("Hello")
    assert error.value.status_code == 504


@pytest.mark.asyncio
async def test_ollama_chat_rejects_operator_prompt_limit() -> None:
    configured = Settings(ollama_enabled=True, ollama_max_prompt_characters=5)
    with (
        patch("fetchharbor.services.chat.get_settings", return_value=configured),
        pytest.raises(HTTPException) as error,
    ):
        await ollama_chat("too long")
    assert error.value.status_code == 413
