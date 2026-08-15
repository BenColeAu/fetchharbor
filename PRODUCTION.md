# Production readiness

FetchHarbor is structured for production deployment, but version 0.1 is not yet safe to expose as a paid mainnet service. The `/admin/api/security` report deliberately shows the unported x402 settlement middleware as a blocker.

## Required before public deployment

1. Port and test the official Python x402 resource-server middleware. A manifest is not payment enforcement. Bazaar indexing occurs only after a facilitator successfully settles a payment.
2. Use a production facilitator for mainnet. The default `https://x402.org/facilitator` is intended for Base Sepolia or Solana Devnet testing; configure a production facilitator explicitly.
3. Terminate HTTPS at a trusted reverse proxy such as Caddy, Traefik or Nginx. Do not expose Uvicorn directly to the internet.
4. Set `FETCHHARBOR_ALLOWED_HOSTS` to the real public hostname and restrict trusted forwarded-header sources at the process or network boundary.
5. Enable admin only on a private network, VPN, or separately protected hostname. Mount the admin credential as a Docker secret and set `FETCHHARBOR_ADMIN_TOKEN_FILE` to its path. Use at least 32 random characters.
6. Pin production container images to reviewed immutable digests, including Ollama. The example uses `latest` only as a development convenience.
7. Run vulnerability and dependency scans in CI, back up the data volume, test restoration, and configure external alerting.

## Scaling limitations

Monitoring counters and authentication throttles are in process memory. Runtime configuration is persisted to one JSON file. These mechanisms work for a single API container, but they are not consistent across replicas. Before horizontal scaling, move metrics to Prometheus/OpenTelemetry, throttling to Redis or the edge proxy, and configuration/audit data to a transactional shared database.

Resource metrics describe the container-visible process and host values. Container quota interpretation varies by runtime, so production alerts should use the Docker/VM monitoring system as the authoritative source.

FetchHarbor blocks private, loopback and link-local destinations and revalidates every redirect. DNS resolution and connection are still separate operations, so high-risk deployments should force scraper traffic through a dedicated egress proxy/firewall that also blocks private address ranges; this closes DNS-rebinding and network-policy gaps outside the Python process.

## Secrets

Never commit `.env`. Prefer Compose secrets or an external secret manager. The application never returns the admin token, wallet credentials, facilitator credentials, or environment contents through admin APIs.

## Release gate

A production release should require passing unit/integration tests, a real testnet verify-and-settle test for every paid route, container build and health-check validation, dependency and image scanning, reverse-proxy/TLS validation, backup restoration, and a rollback exercise.
