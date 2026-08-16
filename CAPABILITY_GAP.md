# FetchHarbor capability comparison

This review compares FetchHarbor's deliberately small, self-hosted core with
current public capabilities documented by Firecrawl, Apify, Browserless,
ScrapingBee and Zyte. It is a product roadmap, not a promise that every hosted
platform feature belongs in the base image.

## Where FetchHarbor is differentiated

- Self-hosted Docker/Compose deployment with private networking and restricted
  egress.
- A small registry contract that keeps routes, discovery, pricing and optional
  x402 enforcement aligned.
- Accountless, per-request x402 settlement instead of a mandatory subscription
  or platform API key.
- Optional local Ollama inference with NVIDIA GPU support.
- Operator-owned configuration, secrets, data and receiving wallet.

## Material gaps

| Capability | Comparable services | FetchHarbor today | Recommendation |
| --- | --- | --- | --- |
| Crawl and map | Firecrawl crawls sites and maps their URLs; Apify runs multi-page Actors | Single-URL scrape only | Add asynchronous `crawl` and lightweight `map` plug-ins backed by a bounded job store |
| Search plus scrape | Firecrawl combines web search with extraction | Not built in | Add an optional search-provider adapter; keep provider credentials outside core |
| Rendered browser | Browserless and Zyte expose rendered HTML, screenshots and browser actions | HTTP fetch only | Add an optional Playwright service container with strict concurrency, time and egress limits |
| Structured extraction | Firecrawl and Zyte accept prompts or JSON schemas | Markdown/text outputs | Add schema-constrained extraction using an operator-selected local or remote model |
| Document breadth and OCR | Firecrawl parses PDF, Office files and scanned pages | Text PDFs only | Extend document adapters; keep OCR in an optional heavier profile |
| Async jobs, batches and webhooks | Firecrawl batch/crawl jobs and Apify runs support polling and webhooks | Synchronous requests | Build a small persistent job API before adding long-running services |
| Sessions, cookies and geography | Zyte, ScrapingBee and browser platforms support sessions and location controls | Intentionally stateless | Add opt-in encrypted session storage and pluggable proxy policies, never arbitrary client proxy URLs |
| Cache and retention controls | Firecrawl exposes cache, lockdown and zero-retention modes | No response cache | Add operator-controlled cache policy with explicit retention and purge behavior |
| SDKs and examples | Major platforms provide language SDKs and extensive recipes | OpenAPI and cURL | Generate small Python/TypeScript clients from OpenAPI after APIs stabilize |
| Usage and customer controls | Hosted services expose keys, quotas, usage and billing dashboards | Operator monitoring only | Add optional consumer identities, per-client limits and settlement history without bloating the anonymous x402 path |
| Marketplace depth | Apify publishes reusable Actors; Firecrawl exposes MCP tools | Registry and Bazaar discovery foundation | Add signed plug-in metadata, compatibility checks and install/upgrade lifecycle before accepting third-party code |

## Recommended sequence

1. **Job foundation:** persistent job state, bounded queues, cancellation,
   webhook signatures and retention controls.
2. **Crawl and map plug-ins:** the clearest capability improvement without a
   browser-sized base stack.
3. **Structured extraction:** JSON Schema output through the existing Ollama
   profile, with deterministic validation and token bounds.
4. **Optional browser profile:** Playwright rendering, screenshot and actions in
   its own isolated container.
5. **Operator and consumer controls:** settlement history, per-service usage,
   quotas and API credentials where an operator wants them.
6. **Plug-in lifecycle:** signed manifests, version compatibility, health checks
   and rollback before a public plug-in marketplace.

## Sources reviewed

- [Firecrawl API overview](https://docs.firecrawl.dev/api-reference/v2-introduction)
- [Firecrawl scrape](https://docs.firecrawl.dev/api-reference/endpoint/scrape)
- [Firecrawl document parsing](https://docs.firecrawl.dev/features/parse)
- [Firecrawl MCP](https://docs.firecrawl.dev/mcp)
- [Apify Actors](https://docs.apify.com/actors)
- [Apify platform introduction](https://docs.apify.com/get-started)
- [Browserless REST APIs](https://docs.browserless.io/rest-apis/intro)
- [ScrapingBee documentation](https://www.scrapingbee.com/documentation/)
- [Zyte API capabilities](https://docs.zyte.com/zyte-api/usage/index.html)
