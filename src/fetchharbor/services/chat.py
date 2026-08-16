import asyncio

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import get_settings
from ..registry import ServiceDefinition

router = APIRouter()
_limiters: dict[int, asyncio.Semaphore] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)


class ChatResponse(BaseModel):
    status: str = "success"
    model: str
    response: str
    prompt_tokens: int | None = None
    response_tokens: int | None = None


class OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str


class OllamaResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    message: OllamaMessage
    prompt_eval_count: int | None = None
    eval_count: int | None = None


def _capacity_limiter(limit: int) -> asyncio.Semaphore:
    if limit not in _limiters:
        _limiters[limit] = asyncio.Semaphore(limit)
    return _limiters[limit]


async def ollama_chat(message: str) -> ChatResponse:
    settings = get_settings()
    if not settings.ollama_enabled:
        raise HTTPException(404, "Chat service is disabled")
    if len(message) > settings.ollama_max_prompt_characters:
        raise HTTPException(413, "Chat prompt is too large")

    limiter = _capacity_limiter(settings.ollama_max_concurrency)
    try:
        await asyncio.wait_for(
            limiter.acquire(), timeout=settings.ollama_queue_timeout_seconds
        )
    except TimeoutError as exc:
        raise HTTPException(503, "Chat service is busy") from exc

    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
        "think": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": {"num_predict": settings.ollama_max_output_tokens},
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.ollama_timeout_seconds, trust_env=False
        ) as client:
            result = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat", json=payload
            )
            result.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Chat provider timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, "Chat provider rejected the request") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "Chat provider is unavailable") from exc
    finally:
        limiter.release()

    try:
        body = OllamaResponse.model_validate(result.json())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(502, "Chat provider returned an invalid response") from exc
    return ChatResponse(
        model=body.model,
        response=body.message.content,
        prompt_tokens=body.prompt_eval_count,
        response_tokens=body.eval_count,
    )


@router.post("/chat", response_model=ChatResponse, summary="chat", operation_id="chat")
async def chat(request: ChatRequest) -> ChatResponse:
    return await ollama_chat(request.message)


definition = ServiceDefinition(
    name="chat",
    path="/chat",
    methods=("POST",),
    price_usdc="0.01",
    description="Return a bounded chat response from the configured Ollama model.",
    router=router,
    input_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 8000}
        },
        "required": ["message"],
        "additionalProperties": False,
    },
    input_example={"message": "Explain this topic briefly."},
    output_example={
        "status": "success",
        "model": "llama3.2:3b",
        "response": "Hello! How can I help?",
        "prompt_tokens": 14,
        "response_tokens": 8,
    },
)
