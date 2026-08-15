# FetchHarbor

[![Docker CI](https://github.com/BenColeAu/fetchharbor/actions/workflows/docker-ci.yml/badge.svg)](https://github.com/BenColeAu/fetchharbor/actions/workflows/docker-ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

FetchHarbor is a modular, self-hosted content-service platform designed for a headless VM. It carries forward the FastScrape route contract while separating services, x402/Bazaar discovery, and optional MCP/Ollama integrations.

It is operator-neutral: the repository contains no personal wallet, domain, API credential, or production price. Each deployment supplies those values through environment configuration.

## Included routes

- `GET|POST /scrape`
- `GET|POST /html-to-md`
- `GET|POST /pdf-parse`
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

Optional profiles remain internal to the Compose network:

```bash
docker compose --profile ollama up -d
docker compose --profile mcp up -d
```

## Add a service

Create a module under `src/fetchharbor/services`, expose an `APIRouter` and one `ServiceDefinition`, then add it to `BUILTIN_SERVICES`. The registry adds its router, service catalog entry, x402 requirements and Bazaar discovery metadata.

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
| `FETCHHARBOR_PRICE_SCRAPE_USDC` | Scrape price |
| `FETCHHARBOR_PRICE_HTML_TO_MD_USDC` | HTML conversion price |
| `FETCHHARBOR_PRICE_PDF_PARSE_USDC` | PDF parsing price |

The committed `.env.example` uses only inert placeholders. Operators copy it to `.env`; `.env` is ignored by Git. New service modules can add their own configuration through the same settings model.

## Operations

The API container runs as an unprivileged user with a read-only filesystem, health check, restart policy, CPU/memory boundaries, and an isolated internal network. Ollama is never published to the host by default.

For a lean production stack, create `secrets/admin_token.txt`, set the two hostnames in `.env`, then run:

```bash
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

This adds only Caddy and a restricted Squid egress proxy. Caddy terminates HTTPS and hides `/admin` on the public hostname; the admin hostname should additionally be restricted by your VPN, tunnel or identity-aware access layer. The API has no direct edge-network attachment in this deployment. Scraping and facilitator traffic leave through the proxy, which rejects private, local, metadata and reserved destinations.

No Prometheus, Grafana, Redis or PostgreSQL services are included. Built-in bounded monitoring and JSON/audit storage remain intentionally single-VM features.

## Admin control plane

Set `FETCHHARBOR_ADMIN_ENABLED=true`, supply a strong token (preferably with `FETCHHARBOR_ADMIN_TOKEN_FILE`), and open `/admin`. The consolidated dashboard provides process/host and per-route monitoring, editable allow-listed runtime settings, service pricing, security posture checks, and a payload-free configuration audit trail.

Admin is disabled by default. Do not publish it directly to the internet; place it behind a VPN, private ingress, or an additional identity-aware proxy. See [PRODUCTION.md](PRODUCTION.md) for release blockers and deployment requirements.
