import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from fetchharbor.config import Settings
from fetchharbor.discovery import x402_manifest
from fetchharbor.registry import ServiceRegistry
from fetchharbor.services import configured_services
from fetchharbor.services.media import (
    MEDIA_SERVICES,
    EncodedAudioRequest,
    _validate_audio,
    summary_definition,
)


def media_settings(token_file: Path, **overrides) -> Settings:
    token_file.write_text("m" * 48, encoding="utf-8")
    return Settings(media_worker_token_file=token_file, **overrides)


def test_media_services_are_opt_in_and_summary_requires_ollama(
    tmp_path: Path,
) -> None:
    base = [service.name for service in configured_services(Settings())]
    media = [
        service.name
        for service in configured_services(
            media_settings(tmp_path / "media-token", media_enabled=True)
        )
    ]
    media_with_ollama = [
        service.name
        for service in configured_services(
            media_settings(
                tmp_path / "media-ollama-token",
                media_enabled=True,
                ollama_enabled=True,
            )
        )
    ]

    assert base == ["scrape", "html-to-md", "pdf-parse"]
    assert media == [
        *base,
        "audio-speech",
        "audio-transcribe",
        "audio-subtitles",
        "audio-convert",
    ]
    assert media_with_ollama[-1] == "audio-transcribe-summary"


def test_media_discovery_uses_json_schemas_and_configured_prices(
    tmp_path: Path,
) -> None:
    settings = media_settings(tmp_path / "media-token", media_enabled=True)
    registry = ServiceRegistry()
    for service in configured_services(settings):
        registry.register(service)

    resources = {
        item["resource"]: item
        for item in x402_manifest(registry, settings)["resources"]
    }
    speech = resources[f"{settings.public_url}/v1/audio/speech"]
    transcription = resources[f"{settings.public_url}/audio/transcribe"]

    assert speech["accepts"][0]["amount"] == "40000"
    assert transcription["accepts"][0]["amount"] == "25000"
    assert transcription["extensions"]["bazaar"]["info"]["input"]["method"] == "POST"
    assert transcription["extensions"]["bazaar"]["info"]["input"]["bodyType"] == "json"
    schema = transcription["extensions"]["bazaar"]["schema"]["properties"]["input"][
        "properties"
    ]["body"]
    assert schema["required"] == ["audio_base64"]
    assert "filename" not in schema["properties"]


def test_bazaar_output_examples_include_every_required_field() -> None:
    for service in (*MEDIA_SERVICES, summary_definition):
        required = set(service.output_schema.get("required", []))
        assert required <= set(service.output_example), service.name


def test_audio_validation_rejects_invalid_and_oversized_data() -> None:
    with pytest.raises(HTTPException, match="valid base64"):
        _validate_audio(EncodedAudioRequest(audio_base64="!!!!"))

    payload = EncodedAudioRequest(audio_base64=base64.b64encode(b"12345").decode())
    with patch("fetchharbor.services.media.get_settings") as configured:
        configured.return_value.media_max_upload_bytes = 4
        with pytest.raises(HTTPException, match="configured limit"):
            _validate_audio(payload)


@pytest.mark.asyncio
async def test_transcription_forwards_only_bounded_contract() -> None:
    payload = base64.b64encode(b"small-audio").decode()
    expected = {"status": "success", "text": "hello", "language": "en"}
    with patch(
        "fetchharbor.services.media._worker", new=AsyncMock(return_value=expected)
    ) as worker:
        from fetchharbor.services.media import transcribe

        result = await transcribe(EncodedAudioRequest(audio_base64=payload))

    assert result == expected
    forwarded = worker.await_args.args[1]
    assert set(forwarded) == {"audio_base64", "language"}
    assert base64.b64decode(forwarded["audio_base64"]) == b"small-audio"
