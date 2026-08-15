# Production readiness

FetchHarbor has a lean hardened deployment path, but mainnet payment readiness still requires an operator-owned end-to-end settlement test. The application does not claim mainnet readiness merely because middleware is installed.

## Required before public deployment

1. Run the official x402 middleware on Base Sepolia and prove the unpaid, invalid-payment, verified and settled request paths. A manifest is not payment enforcement. Bazaar indexing occurs only after successful settlement.
2. Use a production facilitator for mainnet. The default `https://x402.org/facilitator` is testnet-only; CDP authentication is deployment-specific and is not configured by this repository.
3. Use `compose.production.yaml` or an equivalent trusted TLS proxy. Do not expose Uvicorn directly to the internet.
4. Set `FETCHHARBOR_ALLOWED_HOSTS` to the real public hostname and restrict trusted forwarded-header sources at the process or network boundary.
5. Enable admin only on a private network, VPN, or separately protected hostname. Mount the admin credential as a Docker secret and set `FETCHHARBOR_ADMIN_TOKEN_FILE` to its path. Use at least 32 random characters.
6. Pin production container images to reviewed immutable digests, including Ollama. The example uses `latest` only as a development convenience.
7. Run vulnerability and dependency scans in CI, back up the data volume, test restoration, and connect optional external alerting if needed.

## Scaling limitations

Monitoring counters and authentication throttles are in process memory. Runtime configuration is persisted to one JSON file. These mechanisms are deliberately scoped to one API container. Before horizontal scaling, move throttling to a shared service or edge proxy and configuration/audit data to a transactional shared database. External metrics systems are optional and are not part of the clean default stack.

Resource metrics describe the container-visible process and host values. Container quota interpretation varies by runtime, so production alerts should use the Docker/VM monitoring system as the authoritative source.

FetchHarbor blocks private, loopback and link-local destinations and revalidates every redirect. The production Compose overlay also removes the API's direct edge attachment and sends outbound traffic through Squid, which independently blocks private, local, metadata and reserved ranges. Operators should additionally enforce VM firewall rules so Docker configuration changes cannot bypass this boundary.

## Backups

Stop or quiesce the API before taking a filesystem-level backup of the `fetchharbor-data` volume. Store encrypted copies away from the VM and perform periodic restore tests. Caddy state should also be retained; the egress proxy has no persistent data. A backup that has never been restored is not a verified backup.

## Secrets

Never commit `.env`. Prefer Compose secrets or an external secret manager. The application never returns the admin token, wallet credentials, facilitator credentials, or environment contents through admin APIs.

## Release gate

A production release should require passing unit/integration tests, a real testnet verify-and-settle test for every paid route, container build and health-check validation, dependency and image scanning, reverse-proxy/TLS validation, backup restoration, and a rollback exercise.

The `x402 Testnet Settlement` workflow is manual and uses the protected `x402-testnet` GitHub environment. Add a dedicated Base Sepolia wallet private key as the `EVM_PRIVATE_KEY` environment secret. The workflow derives only its public address, starts FetchHarbor with the wallet as the test recipient, proves the unpaid challenge, performs a signed payment, and requires a successful settlement receipt. Never reuse a mainnet-funded wallet for this test.
