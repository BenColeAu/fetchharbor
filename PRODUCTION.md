# Production readiness

FetchHarbor has a lean hardened deployment path, but mainnet payment readiness still requires an operator-owned end-to-end settlement test. The application does not claim mainnet readiness merely because middleware is installed.

## Required before public deployment

1. Run the official x402 middleware on Base Sepolia and prove the unpaid, invalid-payment, verified and settled request paths. A manifest is not payment enforcement. Bazaar indexing occurs only after successful settlement.
2. Use a production facilitator for mainnet. The default `https://x402.org/facilitator` is testnet-only; the optional mainnet overlay supports deployment-specific CDP credentials through Docker secrets.
3. Use `compose.production.yaml` or an equivalent trusted TLS proxy. Do not expose Uvicorn directly to the internet.
4. Set `FETCHHARBOR_ALLOWED_HOSTS` to the real public hostname and restrict trusted forwarded-header sources at the process or network boundary.
5. Keep the separate admin process bound to `127.0.0.1`. Never add it to public Caddy, Cloudflare Tunnel, or another ingress. Mount its credential as a Docker secret and use at least 32 random characters.
6. Keep production container images pinned to reviewed immutable digests. Refresh the tag and digest together through a reviewed dependency-update process.
7. Run vulnerability and dependency scans in CI, back up the data volume, test restoration, and connect optional external alerting if needed.
8. Treat `requirements.lock` and `requirements-test.lock` as release artifacts. Regenerate and review them whenever `pyproject.toml` changes; Docker installs only hash-verified resolved dependencies from these files.

## Scaling limitations

Monitoring counters and authentication throttles are in process memory. The latest 100 sanitized public request events, runtime configuration and a secret-free public-process health snapshot are shared with the loopback-only admin process through bounded files in the private data volume. Live operational settings are reloaded after a protected admin save; payment, pricing, payout, network, asset and facilitator fields stay staged until restart. These mechanisms are deliberately scoped to one host. Before horizontal scaling, move throttling to a shared service or edge proxy and configuration/audit data to a transactional shared database.

## Optional Ollama chat service

`POST /chat` is built in but disabled by default. To enable it, set
`FETCHHARBOR_OLLAMA_ENABLED=true`, select the model and resource limits in `.env`,
and start production with the `ollama` profile. The Ollama API remains private to
the internal Compose network and is not published on the host.

```bash
docker compose -f compose.yaml -f compose.production.yaml \
  -f compose.ollama-download.yaml --profile ollama up -d ollama
docker compose -f compose.yaml -f compose.production.yaml \
  -f compose.ollama-download.yaml exec ollama ollama pull llama3.2:3b
docker compose -f compose.yaml -f compose.production.yaml \
  --profile ollama up -d --force-recreate ollama
docker compose -f compose.yaml -f compose.production.yaml \
  --profile ollama up --build -d
```

Confirm `chat` appears in `/services` and `POST /chat` succeeds while payment is
disabled. When x402 is enabled, confirm the same request returns `402` before a
payment is supplied. Pulling the model is an explicit deployment step; a healthy
empty Ollama container does not mean the selected model is installed. The
download overlay publishes no port and must be removed by the subsequent forced
recreation; verify Ollama then has only the `internal` network. Size CPU, RAM,
disk and any accelerator for the selected model and expected concurrency.

### NVIDIA GPU acceleration

On a host with a compatible NVIDIA driver and NVIDIA Container Toolkit, add
`compose.gpu.yaml` to the steady-state command:

```bash
docker compose -f compose.yaml -f compose.production.yaml \
  -f compose.gpu.yaml --profile ollama up -d
```

The overlay reserves one GPU for Ollama without publishing its API port. Verify
acceleration with `docker compose ... exec ollama ollama ps` while a request is
running; its `PROCESSOR` column should report GPU use. Omit the overlay to retain
CPU operation. An 8 GB GPU is suitable for the included 3B model, but model size,
context length and concurrent requests all consume VRAM; load-test larger models
before changing the production default.

Resource metrics describe the container-visible process and host values. Container quota interpretation varies by runtime, so production alerts should use the Docker/VM monitoring system as the authoritative source.

FetchHarbor blocks private, loopback and link-local destinations and revalidates every redirect. The production Compose overlay also removes the API's direct edge attachment and sends outbound traffic through Squid, which independently blocks private, local, metadata and reserved ranges. Operators should additionally enforce VM firewall rules so Docker configuration changes cannot bypass this boundary.

## Backups

Stop or quiesce the API before taking a filesystem-level backup of the `fetchharbor-data` volume. Store encrypted copies away from the VM and perform periodic restore tests. Caddy state should also be retained; the egress proxy has no persistent data. A backup that has never been restored is not a verified backup.

## Secrets

Never commit `.env`. Prefer Compose secrets or an external secret manager. The application never returns the admin token, wallet credentials, facilitator credentials, or environment contents through admin APIs.

The admin token is exchanged for a signed, HttpOnly, SameSite=Strict browser
session. The cookie is limited to `/admin` and expires
after 15 minutes by default; change the bounded lifetime with
`FETCHHARBOR_ADMIN_SESSION_TTL_SECONDS`. The token is cleared from the sign-in
field and is not stored in browser storage. Cookie-authenticated changes also
require the exact loopback origin, while local automation may continue to send
the admin token header directly. Use Logout on shared devices and never route
the admin listener through public ingress.

## Release gate

A production release should require passing unit/integration tests, a real testnet verify-and-settle test for every paid route, container build and health-check validation, dependency and image scanning, reverse-proxy/TLS validation, backup restoration, and a rollback exercise.

The `x402 Testnet Settlement` workflow is manual and uses the protected `x402-testnet` GitHub environment. Add a dedicated Base Sepolia wallet private key as the `EVM_PRIVATE_KEY` environment secret and its public address as the `EVM_WALLET_ADDRESS` environment variable. The workflow verifies that they match, starts FetchHarbor with the wallet as the test recipient, proves the unpaid challenge, performs a signed payment, and requires a successful settlement receipt. Never reuse a mainnet-funded wallet for this test.

## Deferred deployment validation

The automated gates do not replace host-specific release work. Before accepting production traffic, the operator must still test the actual domain and TLS renewal, VM firewall rules, backup restoration and rollback. Live facilitator authentication and a deliberately limited-value mainnet settlement remain separate release approvals.

## Administrator release runbook

The admin control plane can stage the payment mode, EVM receiving wallet,
network, asset contract, facilitator URL, authentication mode and service prices
under **Payment & Facilitator**. The complete prospective configuration is
validated, persisted and audited, but deliberately does not change the running
payment middleware. Restart FetchHarbor, then verify the panel reports the new
values as active before accepting paid traffic.

For CDP, an operator can save the API key ID and private key in the separate
credential form. The API never returns either value after saving and the audit
log records only that credentials changed. Admin-managed credentials live in
the persistent FetchHarbor data volume with restricted file permissions; they
are not encrypted by the application. Use disk encryption and strict host
access, or retain `compose.mainnet.yaml` and an external secret manager for a
higher-assurance deployment. A mounted external credential takes precedence and
the panel intentionally makes it read-only. FetchHarbor never requests or stores
the payout wallet's private key.

Submit admin-managed credentials only through the loopback admin panel. Admin
pages and responses are marked `no-store`; credential
validation errors never reflect submitted values; request bodies are size
limited; and the browser clears password fields after submission. FetchHarbor
does not log request bodies. Treat browser extensions, endpoint malware, host
administrators, Docker-volume access and backups as part of the trusted boundary:
application controls cannot protect a secret from a compromised browser or host.

### 1. Domain and TLS

The administrator owns DNS, certificates and renewal monitoring. For direct ingress, set `FETCHHARBOR_PUBLIC_HOST`, `FETCHHARBOR_PUBLIC_URL` and `FETCHHARBOR_ALLOWED_HOSTS`, then start `compose.production.yaml`. Caddy obtains and renews certificates automatically; preserve both Caddy volumes and alert on certificate or renewal errors.

For Cloudflare Tunnel, create one remotely managed public-hostname route from the
public API hostname to `http://api:8080`. Do not create an admin hostname or a
tunnel route to the `admin` service.

Put only the tunnel token in `secrets/cloudflare_tunnel_token.txt`, set the same host values in `.env`, and start:

```bash
docker compose -f compose.yaml -f compose.production.yaml -f compose.cloudflare-tunnel.yaml up --build -d
```

The Cloudflare overlay places the direct Caddy ingress behind the inactive `direct-ingress` profile, publishes no public host ports, and runs `cloudflared` from an immutable image digest. The separate admin process remains bound to host loopback. If Cloudflare Browser Integrity Check or another WAF rule blocks non-browser API clients, add a narrowly scoped API-path exception rather than disabling zone-wide protection.

The Cloudflare overlay also selects `FETCHHARBOR_REQUEST_SOURCE_PROXY=cloudflare`, allowing the protected admin dashboard to attribute requests using Cloudflare's overwritten `CF-Connecting-IP`, `CF-IPCountry`, and `CF-Ray` headers. This is safe only while the origin remains private. The default privacy mode stores masked `/24` IPv4 and `/48` IPv6 networks in a bounded, sanitized file in the private data volume; administrators can select full, masked, hidden, or disabled source collection and a 60-second to seven-day retention window. The file survives normal container restarts and retains at most 100 unexpired events. Country values are approximate. FetchHarbor never retains query strings, request bodies, authorization data, payment headers, or credentials in this monitoring history.

#### Cloudflare edge hardening

The tunnel prevents direct origin access, but it does not by itself decide whether
an HTTP request is malicious. Enable Cloudflare's **Free Managed Ruleset** for the
zone so known exploit probes are rejected before they reach FetchHarbor. Review
Security Events after enabling it and tune only a specific false positive; do not
create broad bypasses for the whole API or hostname.

Add rate limits for the resource-consuming public operations (`/scrape`,
`/pdf-parse`, `/html-to-md`, and `/chat`). Start with thresholds based on a short
load test and expected client behaviour, use a blocking response for clearly
abusive excess traffic, and review events before tightening them. Cloudflare's
free plan provides one rate-limiting rule, so group those paths in that rule when
necessary. The loopback-only admin listener is outside Cloudflare's public path.

Do not enable plain Bot Fight Mode without testing every API client. FetchHarbor
is intentionally called by software and agents, and that mode cannot be scoped
with skip rules. Managed WAF rules and endpoint rate limits are the safer default
for this API. Avoid keyword-based filters for strings such as SQL or JavaScript:
those strings can be legitimate scrape, conversion, or chat inputs. The
application already bounds inputs and downloads, rejects private-network fetches,
revalidates redirects, limits Ollama concurrency and execution time, and routes
production fetches through the private-destination-blocking egress proxy.

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

Either use the protected admin panel and restart the API, or copy the values
from `.env.mainnet.example` into `.env`. The receiving wallet is public
configuration; FetchHarbor does not need its private key. For externally managed
credentials, create a least-privilege CDP API key, store its ID and private key
as `secrets/cdp_api_key_id.txt` and `secrets/cdp_api_key_secret.txt`, and do not
put either in `.env`.

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
- [Cloudflare managed rules](https://developers.cloudflare.com/waf/managed-rules/)
- [Cloudflare WAF feature order](https://developers.cloudflare.com/waf/feature-interoperability/)
- [OWASP API4: Unrestricted Resource Consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/)
