import secrets
from collections import defaultdict, deque
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..config import Settings
from ..registry import ServiceRegistry
from .metrics import MetricsStore
from .store import AdminConfiguration, ConfigurationStore


def build_admin_router(
    settings: Settings,
    registry: ServiceRegistry,
    metrics: MetricsStore,
    store: ConfigurationStore,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    failed_attempts: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))

    def require_admin_host(request: Request) -> None:
        if settings.admin_host and request.url.hostname != settings.admin_host:
            raise HTTPException(404, "Not found")

    def authorize(
        request: Request, x_admin_token: str | None = Header(default=None)
    ) -> str:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        actor = request.client.host if request.client else "unknown"
        now = monotonic()
        attempts = failed_attempts[actor]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many failed admin authentication attempts")
        token = settings.resolved_admin_token()
        if (
            not token
            or not x_admin_token
            or not secrets.compare_digest(x_admin_token, token)
        ):
            attempts.append(now)
            raise HTTPException(401, "Invalid admin token")
        attempts.clear()
        return actor

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request) -> str:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        return DASHBOARD_HTML

    @router.get("/", include_in_schema=False)
    async def dashboard_with_trailing_slash(request: Request) -> RedirectResponse:
        require_admin_host(request)
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        return RedirectResponse(url="/admin", status_code=307)

    @router.get("/api/overview", include_in_schema=False)
    async def overview(_: str = Depends(authorize)) -> dict:
        return {
            "application": {
                "environment": settings.env,
                "payment_mode": settings.payment_mode,
                "service_count": len(registry.services),
            },
            "payment": {
                "mode": settings.payment_mode,
                "network": settings.x402_network,
                "asset": settings.x402_asset,
                "receiving_wallet": settings.x402_pay_to,
            },
            "metrics": metrics.snapshot(),
            "services": registry.catalog(),
        }

    @router.get("/api/configuration", include_in_schema=False)
    async def configuration(_: str = Depends(authorize)) -> dict:
        return store.current()

    @router.put("/api/configuration", include_in_schema=False)
    async def update_configuration(
        payload: AdminConfiguration, actor: str = Depends(authorize)
    ) -> dict:
        if (
            payload.payment_mode is not None
            and payload.payment_mode != settings.payment_mode
        ):
            raise HTTPException(
                409,
                "Payment mode is startup-only; change it through deployment configuration and restart",
            )
        return store.update(payload, actor)

    @router.get("/api/security", include_in_schema=False)
    async def security(_: str = Depends(authorize)) -> dict:
        token = settings.resolved_admin_token()
        checks = [
            {
                "name": "Admin authentication",
                "status": "pass" if len(token) >= 32 else "blocker",
                "detail": "Use a random token of at least 32 characters, preferably from a mounted secret.",
            },
            {
                "name": "Payment enforcement",
                "status": "pass" if settings.payment_mode == "x402" else "warning",
                "detail": "Official x402 v2 middleware is installed; payment mode is controlled at startup.",
            },
            {
                "name": "Security headers",
                "status": "pass" if settings.security_headers_enabled else "warning",
                "detail": "Browser hardening headers.",
            },
            {
                "name": "Outbound request policy",
                "status": "pass" if settings.outbound_proxy_url else "warning",
                "detail": "Application URL checks are active; production should also use the restricted egress proxy.",
            },
            {
                "name": "Committed secrets",
                "status": "pass",
                "detail": "Secrets are supplied through ignored environment files.",
            },
        ]
        return {"checks": checks, "audit": store.audit_events()}

    return router


DASHBOARD_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="/static/favicon.svg" type="image/svg+xml"><title>FetchHarbor Admin</title><style>
:root{color-scheme:dark;--bg:#08111d;--panel:#101d2c;--line:#20334a;--text:#e8f0f7;--muted:#91a4b8;--accent:#43d6b5;--warn:#f6c65b}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#08111d,#0b1725 55%,#102535);color:var(--text);font:14px system-ui,sans-serif}.wrap{max-width:1400px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.controls{display:flex;align-items:center;gap:14px}.source{color:var(--muted);font-weight:700;text-decoration:none}.source:hover{color:var(--text)}h1{font-size:26px;margin:0}h2{font-size:15px;margin:0 0 14px;color:#bfd0df}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.panel{background:rgba(16,29,44,.94);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 16px 40px #0003}.span4{grid-column:span 4}.span6{grid-column:span 6}.span8{grid-column:span 8}.span12{grid-column:span 12}.metric{font-size:28px;font-weight:700;margin-top:8px}.row{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}.warning{color:var(--warn)}.pass{color:var(--accent)}input,select{width:100%;background:#091522;border:1px solid #294057;color:var(--text);padding:9px;border-radius:8px}label{display:block;color:var(--muted);margin:10px 0 5px}button{background:var(--accent);color:#062219;border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer}.login{display:flex;gap:8px}.login input{width:280px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}@media(max-width:850px){.span4,.span6,.span8{grid-column:span 12}.top,.controls{align-items:flex-start;gap:14px;flex-direction:column}.login input{width:220px}}
</style></head><body><div class="wrap"><div class="top"><div><img src="/static/logo.svg" alt="FetchHarbor" width="190" height="43"><div class="muted">Operations, configuration and security</div></div><div class="controls"><a class="source" href="https://github.com/BenColeAu/fetchharbor" target="_blank" rel="noopener noreferrer">GitHub repository ↗</a><div class="login"><input id="token" type="password" placeholder="Admin token"><button onclick="loadAll()">Connect</button></div></div></div><div id="content" class="grid"><section class="panel span12"><h2>CONTROL PLANE</h2><p class="muted">Enter the admin token to load protected operational data.</p></section></div></div>
<script>const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));const headers=()=>({'X-Admin-Token':document.querySelector('#token').value,'Content-Type':'application/json'});const fmt=b=>b>1073741824?(b/1073741824).toFixed(2)+' GiB':(b/1048576).toFixed(1)+' MiB';async function api(path,opts={}){const r=await fetch('/admin/api/'+path,{...opts,headers:headers()});if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json()}async function loadAll(){try{const[o,c,s]=await Promise.all([api('overview'),api('configuration'),api('security')]);render(o,c,s)}catch(e){document.querySelector('#content').innerHTML=`<section class="panel span12"><h2>ACCESS FAILED</h2><p class="warning">${esc(e.message)}</p></section>`}}function render(o,c,s){const routes=o.metrics.routes.map(x=>`<tr><td>${esc(x.route)}</td><td>${esc(x.requests)}</td><td>${esc(x.errors)}</td><td>${esc(x.average_duration_ms)} ms</td><td>${esc(x.last_status)}</td></tr>`).join('')||'<tr><td colspan="5" class="muted">No requests recorded yet</td></tr>';const checks=s.checks.map(x=>`<div class="row"><div><b>${esc(x.name)}</b><div class="muted">${esc(x.detail)}</div></div><span class="${esc(x.status)}">${esc(x.status.toUpperCase())}</span></div>`).join('');const pending=c.pending_restart.includes('x402_pay_to')?'<span class="warning">PENDING RESTART</span>':'<span class="pass">ACTIVE</span>';document.querySelector('#content').innerHTML=`<section class="panel span4"><h2>UPTIME</h2><div class="metric">${esc(o.metrics.uptime_seconds)}s</div><div class="muted">${esc(o.application.environment)}</div></section><section class="panel span4"><h2>PROCESS MEMORY</h2><div class="metric">${fmt(o.metrics.process.rss_bytes)}</div><div class="muted">${esc(o.metrics.process.threads)} threads</div></section><section class="panel span4"><h2>HOST LOAD</h2><div class="metric">${esc(o.metrics.host.cpu_percent)}%</div><div class="muted">Memory ${esc(o.metrics.host.memory_percent)}% · Disk ${esc(o.metrics.host.disk_percent)}%</div></section><section class="panel span8"><h2>ROUTE MONITORING</h2><table><thead><tr><th>Route</th><th>Calls</th><th>Errors</th><th>Average</th><th>Last</th></tr></thead><tbody>${routes}</tbody></table></section><section class="panel span4"><h2>SECURITY POSTURE</h2>${checks}</section><section class="panel span6"><h2>RUNTIME CONFIGURATION</h2><form><label>Public URL</label><input name="public_url" value="${esc(c.public_url)}"><label>Payment mode</label><select name="payment_mode"><option ${c.payment_mode==='disabled'?'selected':''}>disabled</option><option ${c.payment_mode==='x402'?'selected':''}>x402</option></select><label>Request timeout (seconds)</label><input name="request_timeout_seconds" type="number" value="${esc(c.request_timeout_seconds)}"><label>Maximum download bytes</label><input name="max_download_bytes" type="number" value="${esc(c.max_download_bytes)}"><button type="submit" style="margin-top:14px">Save configuration</button></form></section><section class="panel span6"><h2>SERVICE PRICING (USDC · RESTART REQUIRED)</h2><form><label>Scrape</label><input name="price_scrape_usdc" value="${esc(c.price_scrape_usdc)}"><label>HTML to Markdown</label><input name="price_html_to_md_usdc" value="${esc(c.price_html_to_md_usdc)}"><label>PDF Parse</label><input name="price_pdf_parse_usdc" value="${esc(c.price_pdf_parse_usdc)}"><label>Ollama Chat</label><input name="price_chat_usdc" value="${esc(c.price_chat_usdc)}"><button type="submit" style="margin-top:14px">Save pricing</button></form></section><section class="panel span12"><h2>PAYMENT SETTLEMENT · RESTART REQUIRED</h2><form data-sensitive="payout"><div class="row"><div><b>Active receiving wallet</b><div class="muted">${esc(c.active_x402_pay_to)}</div></div>${pending}</div><div class="row"><div><b>Active network</b><div class="muted">${esc(o.payment.network)}</div></div><div><b>Asset contract</b><div class="muted">${esc(o.payment.asset)}</div></div></div><label>Next receiving wallet (EVM)</label><input name="x402_pay_to" value="${esc(c.x402_pay_to)}" pattern="0x[0-9a-fA-F]{40}" minlength="42" maxlength="42" autocomplete="off" spellcheck="false" required><p class="muted">Payments are directed to this address only after FetchHarbor restarts. Verify the network, asset and complete address independently before enabling x402.</p><button type="submit">Save payout address</button></form></section>`;document.querySelectorAll('form').forEach(f=>f.onsubmit=save)}async function save(e){e.preventDefault();const data=Object.fromEntries(new FormData(e.target));for(const k of['request_timeout_seconds','max_download_bytes'])if(k in data)data[k]=Number(data[k]);if(e.target.dataset.sensitive==='payout'&&!confirm('Save this receiving wallet? It will become active only after FetchHarbor restarts. Verify the full address before continuing.'))return;try{const result=await api('configuration',{method:'PUT',body:JSON.stringify(data)});if(result.restart_required?.length)alert('Saved. Restart FetchHarbor to activate: '+result.restart_required.join(', '));await loadAll()}catch(err){alert(err.message)}}</script></body></html>"""
