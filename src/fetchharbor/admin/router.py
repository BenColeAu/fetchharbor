import secrets
from collections import defaultdict, deque
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..config import Settings
from ..registry import ServiceRegistry
from .metrics import MetricsStore
from .store import AdminConfiguration, ConfigurationStore


def build_admin_router(settings: Settings, registry: ServiceRegistry, metrics: MetricsStore, store: ConfigurationStore) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    failed_attempts: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))

    def authorize(request: Request, x_admin_token: str | None = Header(default=None)) -> str:
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
        if not token or not x_admin_token or not secrets.compare_digest(x_admin_token, token):
            attempts.append(now)
            raise HTTPException(401, "Invalid admin token")
        attempts.clear()
        return actor

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> str:
        if not settings.admin_enabled:
            raise HTTPException(404, "Admin is disabled")
        return DASHBOARD_HTML

    @router.get("/api/overview")
    async def overview(_: str = Depends(authorize)) -> dict:
        return {"application": {"environment": settings.env, "payment_mode": settings.payment_mode, "service_count": len(registry.services)}, "metrics": metrics.snapshot(), "services": registry.catalog()}

    @router.get("/api/configuration")
    async def configuration(_: str = Depends(authorize)) -> dict:
        return store.current()

    @router.put("/api/configuration")
    async def update_configuration(payload: AdminConfiguration, actor: str = Depends(authorize)) -> dict:
        if payload.payment_mode == "x402":
            raise HTTPException(409, "x402 cannot be enabled until the settlement middleware is installed and verified")
        return store.update(payload, actor)

    @router.get("/api/security")
    async def security(_: str = Depends(authorize)) -> dict:
        token = settings.resolved_admin_token()
        checks = [
            {"name": "Admin authentication", "status": "pass" if len(token) >= 32 else "blocker", "detail": "Use a random token of at least 32 characters, preferably from a mounted secret."},
            {"name": "Payment enforcement", "status": "blocker", "detail": "The verified x402 settlement middleware has not yet been ported; keep payment mode disabled."},
            {"name": "Security headers", "status": "pass" if settings.security_headers_enabled else "warning", "detail": "Browser hardening headers."},
            {"name": "Outbound request policy", "status": "pass", "detail": "Private, loopback and link-local targets are blocked."},
            {"name": "Committed secrets", "status": "pass", "detail": "Secrets are supplied through ignored environment files."},
        ]
        return {"checks": checks, "audit": store.audit_events()}

    return router


DASHBOARD_HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FetchHarbor Admin</title><style>
:root{color-scheme:dark;--bg:#08111d;--panel:#101d2c;--line:#20334a;--text:#e8f0f7;--muted:#91a4b8;--accent:#43d6b5;--warn:#f6c65b}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#08111d,#0b1725 55%,#102535);color:var(--text);font:14px system-ui,sans-serif}.wrap{max-width:1400px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}h1{font-size:26px;margin:0}h2{font-size:15px;margin:0 0 14px;color:#bfd0df}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.panel{background:rgba(16,29,44,.94);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 16px 40px #0003}.span4{grid-column:span 4}.span6{grid-column:span 6}.span8{grid-column:span 8}.span12{grid-column:span 12}.metric{font-size:28px;font-weight:700;margin-top:8px}.row{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}.warning{color:var(--warn)}.pass{color:var(--accent)}input,select{width:100%;background:#091522;border:1px solid #294057;color:var(--text);padding:9px;border-radius:8px}label{display:block;color:var(--muted);margin:10px 0 5px}button{background:var(--accent);color:#062219;border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer}.login{display:flex;gap:8px}.login input{width:280px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}@media(max-width:850px){.span4,.span6,.span8{grid-column:span 12}.top{align-items:flex-start;gap:14px;flex-direction:column}.login input{width:220px}}
</style></head><body><div class="wrap"><div class="top"><div><h1>FetchHarbor Admin</h1><div class="muted">Operations, configuration and security</div></div><div class="login"><input id="token" type="password" placeholder="Admin token"><button onclick="loadAll()">Connect</button></div></div><div id="content" class="grid"><section class="panel span12"><h2>CONTROL PLANE</h2><p class="muted">Enter the admin token to load protected operational data.</p></section></div></div>
<script>const headers=()=>({'X-Admin-Token':document.querySelector('#token').value,'Content-Type':'application/json'});const fmt=b=>b>1073741824?(b/1073741824).toFixed(2)+' GiB':(b/1048576).toFixed(1)+' MiB';async function api(path,opts={}){const r=await fetch('/admin/api/'+path,{...opts,headers:headers()});if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json()}async function loadAll(){try{const[o,c,s]=await Promise.all([api('overview'),api('configuration'),api('security')]);render(o,c,s)}catch(e){document.querySelector('#content').innerHTML=`<section class="panel span12"><h2>ACCESS FAILED</h2><p class="warning">${e.message}</p></section>`}}function render(o,c,s){const routes=o.metrics.routes.map(x=>`<tr><td>${x.route}</td><td>${x.requests}</td><td>${x.errors}</td><td>${x.average_duration_ms} ms</td><td>${x.last_status}</td></tr>`).join('')||'<tr><td colspan="5" class="muted">No requests recorded yet</td></tr>';const checks=s.checks.map(x=>`<div class="row"><div><b>${x.name}</b><div class="muted">${x.detail}</div></div><span class="${x.status}">${x.status.toUpperCase()}</span></div>`).join('');document.querySelector('#content').innerHTML=`<section class="panel span4"><h2>UPTIME</h2><div class="metric">${o.metrics.uptime_seconds}s</div><div class="muted">${o.application.environment}</div></section><section class="panel span4"><h2>PROCESS MEMORY</h2><div class="metric">${fmt(o.metrics.process.rss_bytes)}</div><div class="muted">${o.metrics.process.threads} threads</div></section><section class="panel span4"><h2>HOST LOAD</h2><div class="metric">${o.metrics.host.cpu_percent}%</div><div class="muted">Memory ${o.metrics.host.memory_percent}% · Disk ${o.metrics.host.disk_percent}%</div></section><section class="panel span8"><h2>ROUTE MONITORING</h2><table><thead><tr><th>Route</th><th>Calls</th><th>Errors</th><th>Average</th><th>Last</th></tr></thead><tbody>${routes}</tbody></table></section><section class="panel span4"><h2>SECURITY POSTURE</h2>${checks}</section><section class="panel span6"><h2>RUNTIME CONFIGURATION</h2><form><label>Public URL</label><input name="public_url" value="${c.public_url}"><label>Payment mode</label><select name="payment_mode"><option ${c.payment_mode==='disabled'?'selected':''}>disabled</option><option ${c.payment_mode==='x402'?'selected':''}>x402</option></select><label>Request timeout (seconds)</label><input name="request_timeout_seconds" type="number" value="${c.request_timeout_seconds}"><label>Maximum download bytes</label><input name="max_download_bytes" type="number" value="${c.max_download_bytes}"><button type="submit" style="margin-top:14px">Save configuration</button></form></section><section class="panel span6"><h2>SERVICE PRICING (USDC)</h2><form><label>Scrape</label><input name="price_scrape_usdc" value="${c.price_scrape_usdc}"><label>HTML to Markdown</label><input name="price_html_to_md_usdc" value="${c.price_html_to_md_usdc}"><label>PDF Parse</label><input name="price_pdf_parse_usdc" value="${c.price_pdf_parse_usdc}"><button type="submit" style="margin-top:14px">Save pricing</button></form></section>`;document.querySelectorAll('form').forEach(f=>f.onsubmit=save)}async function save(e){e.preventDefault();const data=Object.fromEntries(new FormData(e.target));for(const k of['request_timeout_seconds','max_download_bytes'])if(k in data)data[k]=Number(data[k]);try{await api('configuration',{method:'PUT',body:JSON.stringify(data)});await loadAll()}catch(err){alert(err.message)}}</script></body></html>'''
