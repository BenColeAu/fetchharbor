# Extending FetchHarbor

FetchHarbor capabilities are plug-and-play service modules. A service owns its HTTP
contract and implementation; one `ServiceDefinition` connects it to routing, the
service catalog, monitoring, x402 enforcement, and Bazaar discovery.

This guide applies to local functions, command-line tools, internal containers,
hosted APIs, databases, and AI providers. The Ollama chat example is one adapter,
not a special platform feature.

## The service contract

Every service module under `src/fetchharbor/services/` exports `definition`, a
`ServiceDefinition` containing:

| Field | Meaning |
| --- | --- |
| `name` | Stable, unique kebab-case identifier; also used for price lookup |
| `path` | Exact public API path |
| `methods` | Methods protected and advertised by FetchHarbor |
| `description` | Human- and machine-readable capability description |
| `price_usdc` | Safe default price as a decimal string |
| `router` | FastAPI router implementing every declared method/path |
| `input_schema` | JSON Schema published in Bazaar discovery |
| `output_example` | Representative JSON response published in discovery |

The definition is the source of truth. Do not add a route without declaring it,
because undeclared routes will not receive generated x402 protection or discovery
metadata. Likewise, do not declare methods that the router does not implement.

## Universal plug-in procedure

1. Define a small request and response contract. Set explicit input-size bounds.
2. Put provider-specific work behind a narrow adapter function or class.
3. Create the FastAPI router and translate dependency failures into appropriate
   `4xx`, `502`, `503`, or `504` responses without returning credentials or raw
   internal errors.
4. Export one `ServiceDefinition` with matching method, path, schema, and example.
5. Import the definition in `src/fetchharbor/services/__init__.py` and append it to
   `BUILTIN_SERVICES`.
6. Add typed settings to `Settings` for all operator-controlled values. Add inert
   examples to `.env.example`; use Docker secrets for credentials.
7. If the dependency needs another container, add it through an optional Compose
   profile or overlay. Keep it off the host network and avoid publishing its port.
8. Add contract, validation, dependency-failure, discovery, and x402 tests.
9. Rebuild the image. Startup registration occurs when the application imports, so
   a restart is required to add or remove a service or change protected pricing.

After registration, confirm all of the following:

```bash
curl http://localhost:8080/services
curl http://localhost:8080/.well-known/x402.json
curl http://localhost:8080/openapi.json
```

With payment disabled, exercise the handler normally. With x402 enabled, first
make an unpaid request and confirm it returns `402`; only then use the normal
limited-value settlement procedure.

## Worked example: chat through Ollama

This example exposes `POST /chat`. It uses Ollama's native `POST /api/chat`
endpoint with streaming disabled so the public FetchHarbor response remains one
bounded JSON document.

Create `src/fetchharbor/services/chat.py`:

```python
import asyncio
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..registry import ServiceDefinition

router = APIRouter()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
CHAT_SLOTS = asyncio.Semaphore(int(os.getenv("OLLAMA_MAX_CONCURRENCY", "2")))


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)


class ChatResponse(BaseModel):
    status: str
    model: str
    response: str
    prompt_tokens: int | None = None
    response_tokens: int | None = None


async def ollama_chat(message: str) -> ChatResponse:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {"num_predict": 512},
    }
    try:
        await asyncio.wait_for(CHAT_SLOTS.acquire(), timeout=1)
    except TimeoutError as exc:
        raise HTTPException(503, "Chat service is busy") from exc

    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            result = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            result.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Chat provider timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "Chat provider is unavailable") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, "Chat provider rejected the request") from exc
    finally:
        CHAT_SLOTS.release()

    try:
        body = result.json()
        return ChatResponse(
            status="success",
            model=body.get("model", OLLAMA_MODEL),
            response=body["message"]["content"],
            prompt_tokens=body.get("prompt_eval_count"),
            response_tokens=body.get("eval_count"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(502, "Chat provider returned an invalid response") from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await ollama_chat(request.message)


definition = ServiceDefinition(
    name="chat",
    path="/chat",
    methods=("POST",),
    price_usdc="0.01",
    description="Return a bounded chat response from the configured model.",
    router=router,
    input_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 8000}
        },
        "required": ["message"],
        "additionalProperties": False,
    },
    output_example={
        "status": "success",
        "model": "llama3.2:3b",
        "response": "Hello! How can I help?",
        "prompt_tokens": 14,
        "response_tokens": 8,
    },
)
```

Register it in `src/fetchharbor/services/__init__.py`:

```python
from .chat import definition as chat
from .html_to_md import definition as html_to_md
from .pdf_parse import definition as pdf_parse
from .scrape import definition as scrape

BUILTIN_SERVICES = (scrape, html_to_md, pdf_parse, chat)
```

For an operator-configurable price, add this field to `Settings`:

```python
price_chat_usdc: str = "0.01"
```

and add this inert example to `.env.example`:

```dotenv
FETCHHARBOR_PRICE_CHAT_USDC=0.01
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_MAX_CONCURRENCY=2
```

`service_price()` automatically maps the service name `chat` to
`price_chat_usdc`. To make the price editable in the admin dashboard, also add a
validated `price_chat_usdc` field to `AdminConfiguration` and include it in
`RESTART_REQUIRED_FIELDS`. Pricing changes require restart because the payment
middleware is built at startup.

### Start and prepare Ollama

The existing `ollama` profile keeps port `11434` private to the Compose network:

```bash
docker compose --profile ollama up --build -d
docker compose exec ollama ollama pull llama3.2:3b
docker compose restart api
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Reply with one short greeting."}'
```

The image and model are separate artifacts: starting the container does not prove
the configured model is present. Pull and smoke-test every pinned model during
deployment. Do not expose Ollama's port publicly; its local API does not require
authentication. In production Compose, keep both `api` and `ollama` on the
`internal` network.

## Adapting the pattern to any provider

Keep the public `ChatRequest`, `ChatResponse`, route, and `ServiceDefinition`
stable, and replace only `ollama_chat()`:

- For a hosted model API, load its credential from a Docker secret, set a bounded
  timeout, and route outbound traffic through the production egress proxy.
- For a local command, run it without a shell, enforce a deadline, and never pass
  untrusted text as command options.
- For a database or queue, use a bounded connection pool and expose readiness only
  when the dependency is required for all traffic.
- For a long-running job, return a job identifier and expose a separate bounded
  status route instead of holding an HTTP worker indefinitely.
- For files, cap request and decompressed sizes, use `/tmp` or the data volume, and
  remove transient material after processing.

Provider details should not leak into the public response unless they are part of
the intentional contract. This makes adapters replaceable without breaking paid
clients or discovery metadata.

## Production acceptance checklist

A capability is ready only when:

- input length, output length, timeout, and concurrency are bounded;
- credentials are secret-mounted and absent from logs and responses;
- internal dependencies expose no host ports;
- outbound destinations comply with the egress policy;
- dependency errors fail closed and do not bypass x402;
- service catalog, OpenAPI, and Bazaar schemas match observed responses;
- unpaid requests return `402` when payment is enabled;
- unit tests mock the dependency and an integration test uses the real container;
- image digests, model names/versions, and resource requirements are documented;
- CPU, memory, disk, and accelerator capacity have been tested under expected load.

AI output is untrusted content. Do not execute model output, interpolate it into
shell or database commands, or allow tool calls without a separate allow-listed
authorization layer. If prompts may contain private data, document retention and
provider boundaries before deployment.

## Removing or disabling a capability

Remove its definition from `BUILTIN_SERVICES` and rebuild. This removes its router,
catalog entry, discovery record, and generated x402 rule together. An optional
dependency profile can then remain stopped. Before release, verify the old path is
`404` and is absent from `/services`, OpenAPI, and the x402 manifest.

For Ollama's current request and response fields, consult the official
[chat API](https://docs.ollama.com/api/chat), [streaming guide](https://docs.ollama.com/api/streaming),
and [authentication guidance](https://docs.ollama.com/api/authentication).
