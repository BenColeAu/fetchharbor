# Production readiness

FetchHarbor has a lean hardened deployment path, but mainnet payment readiness still requires an operator-owned end-to-end settlement test. The application does not claim mainnet readiness merely because middleware is installed.

## Required before public deployment

1. Run the official x402 middleware on Base Sepolia and prove the unpaid, invalid-payment, verified and settled request paths. A manifest is not payment enforcement. Bazaar indexing occurs only after successful settlement.
2. Use a production facilitator for mainnet. The default `https://x402.org/facilitator` is testnet-only; the optional mainnet overlay supports deployment-specific CDP credentials through Docker secrets.
3. Use `compose.production.yaml` or an equivalent trusted TLS proxy. Do not expose Uvicorn directly to the internet.
4. Set `FETCHHARBOR_ALLOWED_HOSTS` to the real public hostname and restrict trusted forwarded-header sources at the process or network boundary.
5. Enable admin only on a private network, VPN, or separately protected hostname. Mount the admin credential as a Docker secret and set `FETCHHARBOR_ADMIN_TOKEN_FILE` to its path. Use at least 32 random characters.
6. Keep production container images pinned to reviewed immutable digests. Refresh the tag and digest together through a reviewed dependency-update process.
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

The `x402 Testnet Settlement` workflow is manual and uses the protected `x402-testnet` GitHub environment. Add a dedicated Base Sepolia wallet private key as the `EVM_PRIVATE_KEY` environment secret and its public address as the `EVM_WALLET_ADDRESS` environment variable. The workflow verifies that they match, starts FetchHarbor with the wallet as the test recipient, proves the unpaid challenge, performs a signed payment, and requires a successful settlement receipt. Never reuse a mainnet-funded wallet for this test.

## Deferred deployment validation

The automated gates do not replace host-specific release work. Before accepting production traffic, the operator must still test the actual domain and TLS renewal, VM firewall rules, backup restoration and rollback. Live facilitator authentication and a deliberately limited-value mainnet settlement remain separate release approvals.

## Administrator release runbook

### 1. Domain and TLS

The administrator owns DNS, certificates and renewal monitoring. For direct ingress, set `FETCHHARBOR_PUBLIC_HOST`, `FETCHHARBOR_ADMIN_HOST`, `FETCHHARBOR_PUBLIC_URL` and `FETCHHARBOR_ALLOWED_HOSTS`, then start `compose.production.yaml`. Caddy obtains and renews certificates automatically; preserve both Caddy volumes and alert on certificate or renewal errors.

For Cloudflare Tunnel, create a remotely managed tunnel in Cloudflare Zero Trust and add two public-hostname routes:

- the public API hostname to `http://api:8080`
- the admin hostname to `http://api:8080`, protected by a Cloudflare Access policy

Put only the tunnel token in `secrets/cloudflare_tunnel_token.txt`, set the same host values in `.env`, and start:

```bash
docker compose -f compose.yaml -f compose.production.yaml -f compose.cloudflare-tunnel.yaml up --build -d
```

The Cloudflare overlay places the direct Caddy ingress behind the inactive `direct-ingress` profile, publishes no host ports, and runs `cloudflared` from an immutable image digest. FetchHarbor also rejects admin routes unless the request host exactly matches `FETCHHARBOR_ADMIN_HOST`. Do not disable that check. If Cloudflare Browser Integrity Check or another WAF rule blocks non-browser API clients, add a narrowly scoped API-path exception rather than disabling zone-wide protection.

### 2. Host firewall

Apply firewall changes from an existing console session and preserve management access before enabling deny-by-default rules.

- Cloudflare Tunnel deployment: deny all unsolicited inbound traffic. Allow established traffic, required administrator management access, DNS/NTP/OS updates, HTTPS egress, and Cloudflare Tunnel egress on TCP and UDP port 7844. Do not open 80, 443 or 8080 on the host.
- Direct Caddy deployment: allow inbound TCP 80 and TCP/UDP 443, restrict SSH/RDP or other management ports to the administrator network, and never expose 8080 or Docker bridge subnets.
- Keep the Docker API socket and daemon ports inaccessible remotely. Recheck effective rules after Docker upgrades because Docker manages packet-filter rules.

### 3. Whole-host backup and restore

An entire-host or VM backup is acceptable only when it includes the repository/configuration, Docker named volumes, secret files and Docker engine state. Use a cold or application-consistent backup:

1. Record the deployed Git commit and resolved image digests.
2. Stop the Compose project and confirm its containers have exited.
3. Stop Docker, or use a VM snapshot mechanism that guarantees filesystem consistency.
4. Back up the entire host to encrypted storage outside that host.
5. Restart Docker and FetchHarbor, then check `/health/ready`.

Restore onto an isolated host first. Restore the complete backup, start Docker and the same Compose project, verify configuration/audit history and health, and only then reconnect DNS or the tunnel. A backup is not release-qualified until this restore drill succeeds.

### 4. Rollback

Before each release, retain the last known-good Git commit, resolved image digests and a pre-release whole-host backup. If health or payment verification fails, disconnect public ingress, stop the new project, restore the backup, check out the recorded commit, rebuild using its pinned dependencies/images, and start with the previous configuration. Verify health, unpaid `402` behavior, admin isolation and a testnet paid request before reconnecting ingress. Never roll application code backward while retaining a newer, incompatible data volume unless that release explicitly documents compatibility.

### 5. Base mainnet configuration (no settlement)

FetchHarbor's FastScrape-compatible mainnet example uses Base mainnet USDC:

- network: `eip155:8453`
- asset: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- EIP-712 asset name/version: `USD Coin` / `2`
- facilitator: `https://api.cdp.coinbase.com/platform/v2/x402`
- facilitator authentication: short-lived CDP JWTs generated independently for `/supported`, `/verify` and `/settle`

Copy the values from `.env.mainnet.example` into `.env`, replace `FETCHHARBOR_X402_PAY_TO` with the operator's receiving address, and set operator-approved prices. The receiving wallet is public configuration; FetchHarbor does not need its private key. Create a least-privilege CDP API key, store its ID and secret as `secrets/cdp_api_key_id.txt` and `secrets/cdp_api_key_secret.txt`, and do not put either in `.env`.

Start with both production and mainnet overlays:

```bash
docker compose -f compose.yaml -f compose.production.yaml -f compose.mainnet.yaml up --build -d
docker compose -f compose.yaml -f compose.production.yaml -f compose.mainnet.yaml exec api python -m fetchharbor.mainnet_preflight
```

The preflight authenticates to the facilitator and verifies advertised Base-mainnet exact-payment support. It does not sign, submit or settle a payment. Then make an unpaid request and confirm HTTP `402`, inspect `PAYMENT-REQUIRED`, `/.well-known/x402.json`, the network, asset, payee and atomic prices before exposing traffic.

The application refuses to start if Base mainnet is paired with the testnet-only x402.org facilitator, if the CDP facilitator lacks CDP authentication, or if credentials cannot be read. Other facilitators remain pluggable: configure their URL and `none` authentication when appropriate; support for a new authentication scheme should be implemented as another explicit provider rather than hard-coded headers.

### 6. Deliberately deferred settlement

Do not run `scripts/x402_settlement_test.py` with a funded mainnet wallet during deployment preparation. The operator's final release action is a manual, limited-value request from a dedicated release wallet after domain, tunnel/firewall, restore and rollback checks pass. Verify the returned settlement receipt and transaction on Base, confirm the receiving-wallet balance, then decide whether to leave payments enabled.

## Operator references

- [CDP x402 network support](https://docs.cdp.coinbase.com/x402/network-support)
- [CDP API authentication](https://docs.cdp.coinbase.com/api-reference/v2/authentication)
- [CDP x402 troubleshooting](https://docs.cdp.coinbase.com/x402/support/troubleshooting)
- [Cloudflare Tunnel firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)
- [Cloudflare remotely managed tunnel setup](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/)
