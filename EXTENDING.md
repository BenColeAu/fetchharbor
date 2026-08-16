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
| `input_example` | Safe, realistic input Bazaar can use to understand the route |
| `body_types` | Optional per-method body type overrides such as `{"POST": "form-data"}`; body methods otherwise default to JSON |
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
4. Export one `ServiceDefinition` with matching method, path, input schema,
   realistic input example, and output example. Set `body_types` for non-JSON
   body methods.
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

Validate that the method entry in `/.well-known/x402.json` contains an
`extensions.bazaar` declaration with the same input form clients must send. When
payments are enabled, decode `PAYMENT-REQUIRED` and confirm the live challenge
contains the same declaration and the configured HTTPS public resource URL.

With payment disabled, exercise the handler normally. With x402 enabled, first
make an unpaid request and confirm it returns `402`; only then use the normal
limited-value settlement procedure.

## Worked example: chat through Ollama

`POST /chat` is now a built-in optional capability. Its implementation in
`src/fetchharbor/services/chat.py` is the reference adapter for a service backed
by another container. It uses Ollama's native `POST /api/chat` endpoint with
streaming and model thinking disabled so FetchHarbor returns one bounded JSON
document.

The service demonstrates the production contract directly:

- it is registered, advertised and x402-protected only when explicitly enabled;
- request characters, generated tokens, concurrent generations, queue time and
  provider time are bounded by typed settings;
- provider errors are converted into stable `502`, `503`, or `504` responses;
- the provider response is validated before any value is returned to the client;
- proxy environment variables are ignored for the private container-to-container
  call; and
- its price is configurable in `.env` and the admin dashboard.

Configure it through the `FETCHHARBOR_OLLAMA_*` settings documented in
`.env.example`. Set `FETCHHARBOR_OLLAMA_ENABLED=true` to include the service at
the next application start. Pricing changes also require restart because the
payment middleware is built at startup.

### Start and prepare Ollama

The existing `ollama` profile keeps port `11434` private to the Compose network:

```bash
docker compose -f compose.yaml -f compose.ollama-download.yaml --profile ollama up -d ollama
docker compose -f compose.yaml -f compose.ollama-download.yaml exec ollama ollama pull llama3.2:3b
docker compose --profile ollama up -d --force-recreate ollama
docker compose --profile ollama up --build -d
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Reply with one short greeting."}'
```

The image and model are separate artifacts: starting the container does not prove
the configured model is present. The download overlay temporarily gives Ollama
outbound access without publishing its port. The forced recreation removes that
access while retaining the model volume. Pull and smoke-test every pinned model
during deployment. Do not expose Ollama's port publicly; its local API does not
require authentication. In production Compose, keep both `api` and `ollama` on
the `internal` network.

On a compatible NVIDIA host, include `compose.gpu.yaml` in the steady-state
Compose command. This reserves one GPU for Ollama only; omitting the overlay is
the CPU fallback. Verify the selected model fits in VRAM at the configured context
and concurrency rather than assuming that container GPU detection is sufficient.

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
