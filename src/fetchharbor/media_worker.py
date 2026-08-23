import asyncio
import base64
import binascii
import hmac
import io
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

import av
import soundfile as sf
from av.error import FFmpegError
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from kokoro_onnx import Kokoro
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FETCHHARBOR_MEDIA_", extra="ignore")
    token_file: Path = Path("/run/secrets/media_worker_token")
    model_dir: Path = Path("/models")
    whisper_model: str = "whisper-small"
    whisper_device: Literal["cpu", "cuda"] = "cpu"
    whisper_compute_type: str = "int8"
    max_upload_bytes: int = 25 * 1024 * 1024
    max_audio_seconds: int = 300
    max_tts_characters: int = 2_000
    max_output_bytes: int = 50 * 1024 * 1024
    queue_timeout_seconds: float = 1.0
    process_timeout_seconds: float = 150.0

    def token(self) -> str:
        return self.token_file.read_text(encoding="utf-8").strip()


settings = WorkerSettings()
app = FastAPI(
    title="FetchHarbor private media worker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
capacity = asyncio.Semaphore(1)


class AudioPayload(BaseModel):
    audio_base64: str = Field(min_length=4, max_length=36_000_000)
    language: str | None = Field(default=None, min_length=2, max_length=16)


class SubtitlePayload(AudioPayload):
    format: Literal["srt", "vtt"] = "srt"


class ConvertPayload(AudioPayload):
    format: Literal["wav", "mp3", "opus", "flac"] = "mp3"


class SpeechPayload(BaseModel):
    input: str = Field(min_length=1, max_length=5_000)
    voice: Literal["af_sarah", "af_heart", "am_adam", "am_michael"] = "af_sarah"
    response_format: Literal["wav"] = "wav"
    speed: float = Field(default=1.0, ge=0.75, le=1.25)


def authorize(x_media_worker_token: str = Header(default="")) -> None:
    try:
        expected = settings.token()
    except OSError as exc:
        raise HTTPException(503, "Media worker is not configured") from exc
    if not expected or not hmac.compare_digest(x_media_worker_token, expected):
        raise HTTPException(401, "Unauthorized")


def decode_audio(payload: AudioPayload) -> tuple[bytes, float]:
    try:
        data = base64.b64decode(payload.audio_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "Invalid audio encoding") from exc
    if not data or len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Audio input exceeds the configured limit")
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            streams = [stream for stream in container.streams if stream.type == "audio"]
            if not streams:
                raise HTTPException(
                    415, "Input does not contain a supported audio stream"
                )
            duration = (
                float(container.duration / av.time_base)
                if container.duration is not None
                else None
            )
            if duration is None and streams[0].duration is not None:
                duration = float(streams[0].duration * streams[0].time_base)
    except HTTPException:
        raise
    except (FFmpegError, OSError, ValueError) as exc:
        raise HTTPException(415, "Invalid or unsupported audio") from exc
    if duration is None or duration <= 0:
        raise HTTPException(422, "Audio duration could not be determined")
    if duration > settings.max_audio_seconds:
        raise HTTPException(413, "Audio duration exceeds the configured limit")
    return data, duration


async def with_capacity(function, *args):
    try:
        await asyncio.wait_for(
            capacity.acquire(), timeout=settings.queue_timeout_seconds
        )
    except TimeoutError as exc:
        raise HTTPException(429, "Media worker is busy") from exc
    try:
        # A Python worker thread cannot be safely cancelled. Keeping the semaphore
        # until the job actually completes prevents timed-out client requests from
        # creating overlapping CPU/model work. Subprocess conversions enforce their
        # own hard timeout in convert_bytes().
        return await asyncio.to_thread(function, *args)
    finally:
        capacity.release()


@lru_cache(maxsize=1)
def whisper_model():
    from faster_whisper import WhisperModel

    model_path = settings.model_dir / settings.whisper_model
    if not model_path.is_dir():
        raise RuntimeError("Whisper model is not installed")
    return WhisperModel(
        str(model_path),
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        cpu_threads=max(1, min(12, os.cpu_count() or 1)),
        local_files_only=True,
    )


@lru_cache(maxsize=1)
def speech_model() -> Kokoro:
    model = settings.model_dir / "kokoro-v1.0.onnx"
    voices = settings.model_dir / "voices-v1.0.bin"
    if not model.is_file() or not voices.is_file():
        raise RuntimeError("Speech model is not installed")
    return Kokoro(str(model), str(voices))


def transcribe_bytes(data: bytes, duration: float, language: str | None) -> dict:
    try:
        segments, info = whisper_model().transcribe(
            io.BytesIO(data),
            language=language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        rows = [
            {"start": segment.start, "end": segment.end, "text": segment.text.strip()}
            for segment in segments
        ]
    except Exception as exc:
        raise HTTPException(422, "Audio could not be transcribed") from exc
    return {
        "status": "success",
        "text": " ".join(row["text"] for row in rows).strip(),
        "segments": rows,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration_seconds": round(duration, 3),
        "model": settings.whisper_model,
    }


def timestamp(seconds: float, separator: str) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def render_subtitles(segments: list[dict], output_format: str) -> str:
    if output_format == "vtt":
        blocks = ["WEBVTT", ""]
        separator = "."
    else:
        blocks = []
        separator = ","
    for index, segment in enumerate(segments, start=1):
        if output_format == "srt":
            blocks.append(str(index))
        blocks.append(
            f"{timestamp(segment['start'], separator)} --> "
            f"{timestamp(segment['end'], separator)}"
        )
        blocks.extend((segment["text"], ""))
    return "\n".join(blocks).rstrip() + "\n"


def synthesize(payload: SpeechPayload) -> dict:
    try:
        samples, sample_rate = speech_model().create(
            payload.input,
            voice=payload.voice,
            speed=payload.speed,
            lang="en-us",
        )
        output = io.BytesIO()
        sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
        audio = output.getvalue()
    except Exception as exc:
        raise HTTPException(422, "Speech could not be generated") from exc
    if len(audio) > settings.max_output_bytes:
        raise HTTPException(413, "Generated speech exceeds the output limit")
    return {
        "status": "success",
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "format": "wav",
        "sample_rate": sample_rate,
        "duration_seconds": round(len(samples) / sample_rate, 3),
        "voice": payload.voice,
    }


CONVERSION_ARGUMENTS = {
    "wav": ["-c:a", "pcm_s16le"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
    "opus": ["-c:a", "libopus", "-b:a", "96k"],
    "flac": ["-c:a", "flac"],
}


def convert_bytes(data: bytes, output_format: str) -> dict:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        input_path = Path(directory) / "input.media"
        output_path = Path(directory) / f"output.{output_format}"
        input_path.write_bytes(data)
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-map_metadata",
            "-1",
            "-vn",
            "-sn",
            "-dn",
            "-t",
            str(settings.max_audio_seconds),
            *CONVERSION_ARGUMENTS[output_format],
            str(output_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=settings.process_timeout_seconds,
            )
            output = output_path.read_bytes()
        except (subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(422, "Audio conversion failed") from exc
    if len(output) > settings.max_output_bytes:
        raise HTTPException(413, "Converted audio exceeds the output limit")
    return {
        "status": "success",
        "audio_base64": base64.b64encode(output).decode("ascii"),
        "format": output_format,
        "size_bytes": len(output),
    }


@app.exception_handler(Exception)
async def unexpected_error(_, __):
    return JSONResponse({"detail": "Media processing failed"}, status_code=500)


@app.get("/health")
async def health() -> dict:
    models_ready = all(
        (
            (settings.model_dir / settings.whisper_model).is_dir(),
            (settings.model_dir / "kokoro-v1.0.onnx").is_file(),
            (settings.model_dir / "voices-v1.0.bin").is_file(),
        )
    )
    if not models_ready:
        raise HTTPException(503, "Media models are not installed")
    return {"status": "ready"}


@app.post("/speech", dependencies=[Depends(authorize)])
async def speech(payload: SpeechPayload) -> dict:
    if len(payload.input) > settings.max_tts_characters:
        raise HTTPException(413, "Speech input exceeds the configured limit")
    return await with_capacity(synthesize, payload)


@app.post("/transcribe", dependencies=[Depends(authorize)])
async def transcribe(payload: AudioPayload) -> dict:
    data, duration = decode_audio(payload)
    return await with_capacity(transcribe_bytes, data, duration, payload.language)


@app.post("/subtitles", dependencies=[Depends(authorize)])
async def subtitles(payload: SubtitlePayload) -> dict:
    data, duration = decode_audio(payload)
    result = await with_capacity(transcribe_bytes, data, duration, payload.language)
    return {
        **result,
        "format": payload.format,
        "subtitles": render_subtitles(result["segments"], payload.format),
    }


@app.post("/convert", dependencies=[Depends(authorize)])
async def convert(payload: ConvertPayload) -> dict:
    data, duration = decode_audio(payload)
    result = await with_capacity(convert_bytes, data, payload.format)
    return {**result, "source_duration_seconds": round(duration, 3)}
