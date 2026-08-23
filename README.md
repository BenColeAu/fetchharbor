<p align="center"><img src="src/fetchharbor/static/logo.svg" alt="FetchHarbor" width="286"></p>

# FetchHarbor

[![Docker CI](https://github.com/BenColeAu/fetchharbor/actions/workflows/docker-ci.yml/badge.svg)](https://github.com/BenColeAu/fetchharbor/actions/workflows/docker-ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

FetchHarbor is a modular, self-hosted content-service platform designed for a headless VM. It carries forward the FastScrape route contract while separating services, x402/Bazaar discovery, and optional MCP/Ollama integrations.

It is operator-neutral: the repository contains no personal wallet, domain, API credential, or production price. Each deployment supplies those values through environment configuration.

## Included routes

- `GET|POST /scrape`
- `GET|POST /html-to-md`
- `GET|POST /pdf-parse`
- `POST /chat` when `FETCHHARBOR_OLLAMA_ENABLED=true`
- `GET /services`
- `GET /.well-known/x402.json`
- `GET /health`, `/health/live`, `/health/ready`

## Start locally

```bash
cp .env.example .env
docker compose up --build -d
curl http://localhost:8080/health
```

Every push and pull request is also tested entirely on a free GitHub-hosted Linux runner. The Docker CI workflow validates Compose, builds the production image, runs tests in an image stage, starts the API, checks container health, exercises public/admin contracts, confirms x402 fails closed, and removes all test resources.

Container dependencies are installed from the committed, hash-verified `requirements.lock` and `requirements-test.lock` files. When changing dependency ranges in `pyproject.toml`, regenerate both locks with Python 3.12 and `pip-tools==7.5.3`, review the resolved changes, then rebuild and test the image before committing them.

Optional profiles remain internal to the Compose network:

```bash
docker compose -f compose.yaml -f compose.ollama-download.yaml --profile ollama up -d ollama
docker compose -f compose.yaml -f compose.ollama-download.yaml exec ollama ollama pull llama3.2:3b
docker compose --profile ollama up -d --force-recreate ollama
docker compose --profile ollama up --build -d
docker compose --profile mcp up -d
```

The download overlay grants Ollama temporary outbound access but publishes no
port. Recreating Ollama without the overlay returns it to the internal-only
network; the downloaded model remains in `ollama-data`.

NVIDIA hosts with the container runtime installed can add GPU acceleration without
changing the portable default stack:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml --profile ollama up -d
```

The overlay reserves one NVIDIA GPU for Ollama only. Omit it for CPU fallback.

Enable the built-in chat service with `FETCHHARBOR_OLLAMA_ENABLED=true`. It is
registered only when enabled, so disabled deployments do not advertise an
unavailable route. See [EXTENDING.md](EXTENDING.md) for configuration and testing.

## Add a service

Create a module under `src/fetchharbor/services`, expose an `APIRouter` and one `ServiceDefinition`, then add it to `BUILTIN_SERVICES`. The registry adds its router, service catalog entry, x402 requirements and Bazaar discovery metadata.

See [EXTENDING.md](EXTENDING.md) for the universal plug-and-play service contract,
configuration and security checklist, testing requirements, and a complete Ollama
chat adapter example. The same pattern supports local functions, internal
containers, hosted APIs, databases, queues, and other providers.

## Payments

FetchHarbor includes the official x402 v2 FastAPI middleware and generates its protected routes from the same service registry used by discovery. Payment remains disabled by default. The example configuration targets Base Sepolia and the signup-free testnet facilitator. Set a real receiving wallet before enabling `FETCHHARBOR_PAYMENT_MODE=x402`.

Mainnet requires a production facilitator and a deliberate network/asset change. A release is not considered mainnet-verified until a real paid request has passed verification and settlement.

Payment and operator settings are customisable without editing source code:

| Setting | Purpose |
| --- | --- |
| `FETCHHARBOR_PUBLIC_URL` | Operator's public service URL |
| `FETCHHARBOR_X402_NETWORK` | CAIP-2 payment network identifier |
| `FETCHHARBOR_X402_PAY_TO` | Operator's receiving wallet |
| `FETCHHARBOR_X402_ASSET` | Accepted payment asset contract |
| `FETCHHARBOR_X402_ASSET_NAME` | Payment asset display/protocol name |
| `FETCHHARBOR_X402_ASSET_VERSION` | Payment asset signature-domain version |
| `FETCHHARBOR_X402_ASSET_DECIMALS` | Conversion between displayed and atomic prices |
| `FETCHHARBOR_X402_FACILITATOR` | Settlement facilitator |
| `FETCHHARBOR_X402_FACILITATOR_AUTH` | `none` or short-lived `cdp` JWT authentication |
| `FETCHHARBOR_X402_CDP_API_KEY_ID_FILE` | Mounted CDP key-ID secret |
| `FETCHHARBOR_X402_CDP_API_KEY_SECRET_FILE` | Mounted CDP signing-key secret |
| `FETCHHARBOR_PRICE_SCRAPE_USDC` | Scrape price |
| `FETCHHARBOR_PRICE_HTML_TO_MD_USDC` | HTML conversion price |
| `FETCHHARBOR_PRICE_PDF_PARSE_USDC` | PDF parsing price |
| `FETCHHARBOR_PRICE_CHAT_USDC` | Ollama chat price |
| `FETCHHARBOR_OLLAMA_ENABLED` | Register the optional `/chat` capability |
| `FETCHHARBOR_OLLAMA_BASE_URL` | Private or operator-approved Ollama API URL |
| `FETCHHARBOR_OLLAMA_MODEL` | Installed model used by `/chat` |
| `FETCHHARBOR_OLLAMA_MAX_PROMPT_CHARACTERS` | Per-request prompt bound |
| `FETCHHARBOR_OLLAMA_MAX_OUTPUT_TOKENS` | Per-request generation bound |
| `FETCHHARBOR_OLLAMA_MAX_CONCURRENCY` | Maximum simultaneous generations |

The committed `.env.example` uses only inert placeholders. Operators copy it to `.env`; `.env` is ignored by Git. New service modules can add their own configuration through the same settings model.

## Operations

The API container runs as an unprivileged user with a read-only filesystem, health check, restart policy, CPU/memory boundaries, and an isolated internal network. Ollama is never published to the host by default.

For a lean production stack, create `secrets/admin_token.txt`, set the public hostname in `.env`, then run:

```bash
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

This adds Caddy, a restricted Squid egress proxy, and a separate private admin process. Caddy serves only the public API. The public process does not register admin routes, and Docker publishes the admin process only on `127.0.0.1:8081`. The API has no direct edge-network attachment in this deployment.

No Prometheus, Grafana, Redis or PostgreSQL services are included. Built-in bounded monitoring and JSON/audit storage remain intentionally single-VM features.

## Admin control plane

Production Compose enables the private admin process and reads its strong token from the Docker secret. Open `http://127.0.0.1:8081`; its root redirects to `/admin`. The dashboard retains its authenticated settings, service pricing, security posture, audit trail, and recent-request view. The public process shares at most 100 sanitized events and a secret-free runtime-health snapshot through the private data volume; bodies, query strings, authorization data, credentials, proxy addresses, and payment headers are never written. Operational settings marked live are reloaded by the public process after saving. Payment, pricing, payout, network, asset and facilitator changes remain staged until a deliberate restart.

Admin is absent from the public process. Never add its loopback port to Cloudflare Tunnel, Caddy, a router, or another ingress. For remote administration, use an operator-controlled SSH port forward or private VPN to host loopback. See [PRODUCTION.md](PRODUCTION.md) for release blockers and deployment requirements.

The optional `compose.cloudflare-tunnel.yaml` overlay replaces direct Caddy ingress with a pinned, outbound-only Cloudflare Tunnel connector. The optional `compose.mainnet.yaml` overlay mounts CDP facilitator credentials without placing them in `.env`. See [PRODUCTION.md](PRODUCTION.md) for the exact release sequence.

Operators can also stage the complete x402 network, asset, payout, facilitator,
authentication and pricing configuration from the protected admin panel. CDP
credentials may be stored in the persistent data volume without ever being
returned by the API; externally mounted secrets remain supported and take
precedence. All payment changes require a deliberate application restart.
