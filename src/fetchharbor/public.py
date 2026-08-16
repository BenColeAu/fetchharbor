from html import escape

from .config import Settings
from .registry import ServiceRegistry


def render_landing(registry: ServiceRegistry, settings: Settings) -> str:
    cards = []
    for service in registry.services:
        methods = " · ".join(service.methods)
        price = settings.service_price(service.name, service.price_usdc)
        cards.append(
            f"""<article class="card service">
            <div class="service-top"><span class="method">{escape(methods)}</span><span class="price">{escape(price)} USDC</span></div>
            <h3>{escape(service.name.replace("-", " ").title())}</h3>
            <p>{escape(service.description)}</p>
            <code>{escape(service.path)}</code>
            </article>"""
        )

    payment_label = (
        "x402 enabled" if settings.payment_mode == "x402" else "payments disabled"
    )
    payment_class = "live" if settings.payment_mode == "x402" else "preview"
    services_html = "".join(cards)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="FetchHarbor is a modular, self-hosted API harbor for scraping, document conversion and local AI, with optional x402 payments.">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<title>FetchHarbor · Modular content APIs</title>
<style>
:root{{--ink:#eaf2f7;--muted:#99acba;--ocean:#07141d;--deep:#092332;--panel:#0d2938;--line:#1e4555;--mint:#62e6bd;--sky:#66c7ff;--sand:#ffd38a}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;color:var(--ink);background:radial-gradient(circle at 78% 5%,#174558 0,transparent 29rem),linear-gradient(145deg,var(--ocean),var(--deep));font:16px/1.6 Inter,ui-sans-serif,system-ui,sans-serif}}a{{color:inherit}}.shell{{max-width:1160px;margin:auto;padding:0 24px}}nav{{height:74px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff12}}.brand{{display:flex;align-items:center;text-decoration:none}}.brand img{{width:180px;height:40px;object-fit:contain;object-position:left center}}.navlinks{{display:flex;align-items:center;gap:22px}}.navlinks a{{color:var(--muted);text-decoration:none;font-size:14px}}.navlinks .button,.button{{color:#06251d;background:var(--mint);padding:10px 16px;border-radius:10px;font-weight:800;text-decoration:none}}.hero{{padding:92px 0 72px;display:grid;grid-template-columns:1.35fr .65fr;gap:54px;align-items:center}}.eyebrow{{display:inline-flex;align-items:center;gap:9px;border:1px solid var(--line);background:#0b2633cc;border-radius:999px;padding:6px 11px;color:#bdd1dc;font-size:13px}}.dot{{width:8px;height:8px;background:var(--mint);border-radius:50%;box-shadow:0 0 18px var(--mint)}}h1{{font-size:clamp(42px,7vw,76px);line-height:1.02;letter-spacing:-.055em;margin:24px 0}}h1 em{{font-style:normal;color:var(--mint)}}.lead{{font-size:19px;color:#b7c8d2;max-width:680px}}.actions{{display:flex;gap:12px;flex-wrap:wrap;margin-top:30px}}.secondary{{padding:9px 15px;border:1px solid #426271;border-radius:10px;text-decoration:none;font-weight:700}}.terminal{{background:#050d12;border:1px solid #254755;border-radius:16px;overflow:hidden;box-shadow:0 30px 80px #0008}}.terminal-bar{{padding:11px 14px;border-bottom:1px solid #18313c;color:#78919e;font-size:12px}}pre{{margin:0;padding:20px;overflow:auto;color:#cde5ed;font:13px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace}}pre b{{color:var(--mint)}}section{{padding:68px 0}}.section-head{{display:flex;justify-content:space-between;gap:30px;align-items:end;margin-bottom:26px}}h2{{font-size:34px;line-height:1.15;letter-spacing:-.035em;margin:0}}.section-head p{{color:var(--muted);max-width:520px;margin:0}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}}.card{{background:linear-gradient(145deg,#102f3eeb,#0b202ceb);border:1px solid var(--line);border-radius:16px;padding:22px}}.service-top{{display:flex;justify-content:space-between;gap:10px;align-items:center}}.method{{color:var(--sky);font:700 11px ui-monospace,monospace}}.price{{color:var(--sand);font-size:12px}}h3{{margin:22px 0 6px;font-size:19px}}.card p{{color:var(--muted);min-height:52px}}.card code{{color:var(--mint);font-size:13px}}.steps{{counter-reset:steps}}.step{{position:relative}}.step:before{{counter-increment:steps;content:"0" counter(steps);display:block;color:var(--mint);font:800 13px ui-monospace,monospace;margin-bottom:32px}}.status{{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:24px;border:1px solid var(--line);border-radius:16px;background:#071820aa}}.status strong{{display:block;font-size:18px}}.status p{{color:var(--muted);margin:2px 0 0}}.badge{{border-radius:999px;padding:7px 12px;font-size:12px;font-weight:800;white-space:nowrap}}.badge.live{{background:#143c32;color:var(--mint)}}.badge.preview{{background:#3b321e;color:var(--sand)}}footer{{margin-top:50px;padding:30px 0 48px;border-top:1px solid #ffffff12;color:var(--muted);display:flex;justify-content:space-between;gap:20px;font-size:13px}}@media(max-width:820px){{.hero{{grid-template-columns:1fr;padding-top:60px}}.grid{{grid-template-columns:1fr}}.navlinks a:not(.button){{display:none}}.section-head,.status,footer{{align-items:flex-start;flex-direction:column}}.brand img{{width:150px}}}}
</style></head><body><div class="shell">
<nav><a class="brand" href="/" aria-label="FetchHarbor home"><img src="/static/logo.svg" alt="FetchHarbor"></a><div class="navlinks"><a href="#services">Services</a><a href="/.well-known/x402.json">x402 discovery</a><a href="https://github.com/BenColeAu/fetchharbor" target="_blank" rel="noopener noreferrer">GitHub ↗</a><a href="/docs" class="button">API docs →</a></div></nav>
<main><div class="hero"><div><div class="eyebrow"><span class="dot"></span>Self-hosted · modular · agent-ready</div><h1>Useful content in.<br><em>Clean data out.</em></h1><p class="lead">FetchHarbor turns web pages, HTML, PDFs and local AI models into focused HTTP services. Discover what is available, call one endpoint, and optionally settle each request through x402.</p><div class="actions"><a class="button" href="/docs">Explore the API</a><a class="secondary" href="/services">View service JSON</a></div></div>
<div class="terminal"><div class="terminal-bar">POST /html-to-md</div><pre><b>curl</b> -X POST \\
  {escape(settings.public_url)}/html-to-md \\
  -H "Content-Type: application/json" \\
  -d '{{"html":"&lt;h1&gt;Hello&lt;/h1&gt;"}}'

<b>→</b> {{"markdown":"# Hello"}}</pre></div></div>
<section id="services"><div class="section-head"><div><div class="eyebrow">LIVE CATALOG</div><h2>Capabilities at this harbor</h2></div><p>The catalog comes from the same registry that generates the API and x402 discovery document, so enabled services and prices stay aligned.</p></div><div class="grid">{services_html}</div></section>
<section><div class="section-head"><div><div class="eyebrow">HOW IT WORKS</div><h2>One predictable flow</h2></div><p>Designed for scripts, applications, agents and service marketplaces—not just human-operated dashboards.</p></div><div class="grid steps"><article class="card step"><h3>Discover</h3><p>Read <code>/.well-known/x402.json</code> or <code>/services</code> to find enabled capabilities, methods and current prices.</p></article><article class="card step"><h3>Request</h3><p>Send normal HTTP input. OpenAPI documents the exact schema, limits and output for every registered service.</p></article><article class="card step"><h3>Settle when enabled</h3><p>An unpaid request receives standard x402 payment requirements. A compatible client settles and retries without an account or subscription.</p></article></div></section>
<section><div class="status"><div><strong>Deployment status</strong><p>{len(registry.services)} services registered · health and readiness checks available</p></div><span class="badge {payment_class}">{escape(payment_label)}</span></div></section></main>
<footer><span>FetchHarbor · composable content infrastructure</span><span><a href="/health">Health</a> · <a href="/openapi.json">OpenAPI JSON</a> · <a href="https://github.com/BenColeAu/fetchharbor" target="_blank" rel="noopener noreferrer">GitHub repository</a></span></footer>
</div></body></html>"""
