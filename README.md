# FetchHarbor

FetchHarbor is a modular, self-hosted content-service platform designed for a headless VM. It carries forward the FastScrape route contract while separating services, x402/Bazaar discovery, and optional MCP/Ollama integrations.

## Included routes

- `GET|POST /scrape`
- `GET|POST /html-to-md`
- `GET|POST /pdf-parse`
- `GET /services`
- `GET /.well-known/x402.json`
- `GET /health`

## Start locally

```bash
cp .env.example .env
docker compose up --build -d
curl http://localhost:8080/health
```

Optional profiles remain internal to the Compose network:

```bash
docker compose --profile ollama up -d
docker compose --profile mcp up -d
```

## Add a service

Create a module under `src/fetchharbor/services`, expose an `APIRouter` and one `ServiceDefinition`, then add it to `BUILTIN_SERVICES`. The registry adds its router, service catalog entry, x402 requirements and Bazaar discovery metadata.

## Payment migration status

The initial scaffold preserves x402 v2 requirements and Bazaar discovery metadata, but defaults `FETCHHARBOR_PAYMENT_MODE=disabled`. Before production cutover, port the verified FastScrape settlement middleware into a payment adapter and run paid Base-network compatibility tests. Never enable production traffic based only on the discovery manifest.

## Operations

The API container runs as an unprivileged user with a read-only filesystem, health check, restart policy, CPU/memory boundaries, and an isolated internal network. Ollama is never published to the host by default.

