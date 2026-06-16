"""Web dashboard leve (#12/#14, port FUNCIONAL do Hermes web/ + web_server.py).

DIFERENÇA do Hermes (React/Vite/FastAPI): stdlib `http.server` + um app single-file (HTML+CSS+vanilla-JS,
ZERO build/dep) que faz fetch das APIs `/api/{status,sessions,config,logs}`. Entrega o MESMO valor —
ver status, sessões, config (read-only, nomes de env nunca valores) e logs num navegador — sem cadeia de
dep nova. `okami gui` sobe e abre. Localhost. **Read-only por design** (editar config pela web é risco;
dono-único edita o YAML direto).
"""
from __future__ import annotations

import html as _html
import json as _json


def render_status_html(data: dict) -> str:
    """HTML simples de status a partir de `data` (compat — usado por callers diretos/tests)."""
    rows = "".join(
        f"<tr><th style='text-align:left;padding:4px 12px'>{_html.escape(str(k))}</th>"
        f"<td style='padding:4px 12px'>{_html.escape(str(v))}</td></tr>"
        for k, v in (data or {}).items()
    )
    return ("<!doctype html><html lang='pt-br'><head><meta charset='utf-8'><title>Okami</title></head>"
            f"<body><h1>🐺 Okami — status</h1><table>{rows}</table></body></html>")


_APP_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Okami</title>
<style>
:root{--bg:#0d0d0f;--card:#16161a;--fg:#e8e8ea;--mut:#8a8a92;--accent:#ff7527;--cyan:#00dfe8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,sans-serif}
header{padding:18px 24px;border-bottom:1px solid #26262c;display:flex;gap:16px;align-items:center}
h1{font-size:18px;margin:0}nav{display:flex;gap:6px;margin-left:auto}
nav button{background:none;border:1px solid #2c2c34;color:var(--mut);padding:6px 12px;border-radius:8px;cursor:pointer}
nav button.active{color:var(--fg);border-color:var(--accent)}
main{padding:24px;max-width:860px;margin:0 auto}
.card{background:var(--card);border:1px solid #24242c;border-radius:12px;padding:16px;margin-bottom:14px}
table{border-collapse:collapse;width:100%}th{text-align:left;color:var(--mut);font-weight:500;padding:6px 10px}
td{padding:6px 10px;border-top:1px solid #222}
pre{white-space:pre-wrap;font-size:12px;color:#cfcfd4;max-height:60vh;overflow:auto;margin:0}
.tag{display:inline-block;background:#22222a;border-radius:6px;padding:2px 8px;margin:2px;font-size:12px}
.muted{color:var(--mut)}
</style></head><body>
<header><span style="font-size:22px">🐺</span><h1>Okami</h1>
<nav><button data-t="status" class="active">Status</button><button data-t="sessions">Sessões</button>
<button data-t="config">Config</button><button data-t="logs">Logs</button></nav></header>
<main id="app"><div class="card muted">carregando…</div></main>
<script>
const app=document.getElementById('app');let tab='status';
const TOKEN=new URLSearchParams(location.search).get('token');
const HDR=TOKEN?{'Authorization':'Bearer '+TOKEN}:{};
const esc=s=>String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const api=p=>fetch(p,{headers:HDR}).then(r=>r.json());
const ALLOW=['approvals.mode','sandbox.profile','sandbox.require_isolation','display.global.tool_progress','display.global.long_running_notifications','harness.max_steps','learning.review'];
async function load(){
 app.innerHTML='<div class="card muted">carregando…</div>';
 try{render(await api('/api/'+tab));}catch(e){app.innerHTML='<div class="card">erro: '+esc(e)+'</div>';}
}
function kv(o){return '<table>'+Object.entries(o||{}).map(([k,v])=>'<tr><th>'+esc(k)+'</th><td>'+(Array.isArray(v)?v.map(x=>'<span class=tag>'+esc(x)+'</span>').join(''):esc(v))+'</td></tr>').join('')+'</table>';}
async function showSession(sid){const d=await api('/api/session/'+encodeURIComponent(sid));app.innerHTML='<div class="card"><button onclick="load()">‹ voltar</button><h3>'+esc(sid)+'</h3>'+((d&&d.length)?d.map(m=>'<p><b>'+esc(m.role)+':</b> '+esc(m.text)+'</p>').join(''):'<span class=muted>sem turnos</span>')+'</div>';}
async function saveCfg(){const k=document.getElementById('ck').value,v=document.getElementById('cv').value;const r=await fetch('/api/config',{method:'POST',headers:{...HDR,'Content-Type':'application/json'},body:JSON.stringify({key:k,value:v})});const d=await r.json();document.getElementById('cmsg').textContent=d.ok?'✓ salvo':('✗ '+(d.error||'erro'));}
function cfgForm(){return '<div class="card"><h3>Editar (allowlist)</h3>chave <select id=ck>'+ALLOW.map(k=>'<option>'+k+'</option>').join('')+'</select> valor <input id=cv> <button onclick="saveCfg()">salvar</button> <span id=cmsg class=muted></span><p class=muted>só chaves não-segredo; grava em okami.local.yaml</p></div>';}
function render(d){
 if(tab==='status'){app.innerHTML='<div class="card">'+kv(d)+'</div>';}
 else if(tab==='sessions'){app.innerHTML='<div class="card">'+((d&&d.length)?'<table><tr><th>chat</th><th>turnos</th><th>atualizado</th></tr>'+d.map(s=>'<tr class="srow" style="cursor:pointer" data-sid="'+esc(s.chat_id)+'"><td>'+esc(s.chat_id)+'</td><td>'+esc(s.turns||'')+'</td><td>'+esc(s.updated_at||'')+'</td></tr>').join('')+'</table><p class=muted>clique numa sessão p/ ver o transcript</p>':'<span class=muted>sem sessões</span>')+'</div>';document.querySelectorAll('.srow').forEach(tr=>tr.onclick=()=>showSession(tr.dataset.sid));}
 else if(tab==='config'){app.innerHTML='<div class="card">'+kv(d)+'<p class=muted>nomes de env, nunca valores</p></div>'+cfgForm();}
 else{app.innerHTML='<div class="card"><pre>'+((d&&d.length)?d.map(esc).join('\\n'):'<span class=muted>sem logs</span>')+'</pre></div>';}
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));b.classList.add('active');tab=b.dataset.t;load();});
load();setInterval(()=>{if(tab==='status'||tab==='logs')load();},5000);
</script></body></html>"""


# Chaves de config EDITÁVEIS pela web (não-segredo, comportamento/exibição). Tudo fora disto é recusado;
# segredo NUNCA edita pela web (o dono usa `okami config set` / o YAML direto).
_CONFIG_ALLOWLIST = frozenset({
    "approvals.mode", "sandbox.profile", "sandbox.require_isolation",
    "display.global.tool_progress", "display.global.long_running_notifications",
    "harness.max_steps", "learning.review",
})
_SECRET_HINT = ("token", "key", "secret", "password", "credential", "auth")


def _json_resp(data, code: int = 200) -> tuple:
    return code, "application/json; charset=utf-8", _json.dumps(data, ensure_ascii=False, default=str)


def route(path: str, *, providers: dict | None = None, token: str | None = None, authorized: bool = True) -> tuple:
    """Roteamento puro GET: (code, content_type, body). `/` = app; `/api/<x>` = JSON do provider;
    `/api/session/<id>` = transcript. Se `token` setado e não-`authorized` → 401."""
    providers = providers or {}
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", _APP_HTML
    if path == "/healthz":
        return 200, "text/plain", "ok"
    if path.startswith("/api/"):
        if token and not authorized:
            return 401, "text/plain", "unauthorized"
        if path.startswith("/api/session/"):           # transcript de UMA sessão
            sid = path[len("/api/session/"):]
            prov = providers.get("session")
            try:
                data = prov(sid) if callable(prov) else []
            except Exception as e:  # noqa: BLE001
                data = {"error": str(e)[:120]}
            return _json_resp(data)
        key = path[len("/api/"):]
        prov = providers.get(key)
        try:
            data = prov() if callable(prov) else ([] if key in ("sessions", "logs") else {})
        except Exception as e:  # noqa: BLE001 — provider quebrado NÃO vira 500
            data = {"error": str(e)[:120]}
        return _json_resp(data)
    return 404, "text/plain", "not found"


def _apply_config_set(key: str, value) -> dict:
    """Grava `key=value` em okami.local.yaml via secure_write (atômico+backup). Só chaves do allowlist."""
    from pathlib import Path
    from okami.core.safe_io import read_yaml_resilient, secure_write_yaml
    p = Path("okami.local.yaml")
    data = read_yaml_resilient(p, default={}) or {}
    node = data
    parts = key.split(".")
    for k in parts[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            return {"ok": False, "error": "caminho de config inválido"}
    node[parts[-1]] = value
    secure_write_yaml(p, data)
    return {"ok": True, "key": key}


def route_post(path: str, body: str, *, providers: dict | None = None, token: str | None = None,
               authorized: bool = True) -> tuple:
    """Roteamento POST: hoje só `/api/config` (set guardado por allowlist + anti-segredo)."""
    if token and not authorized:
        return 401, "text/plain", "unauthorized"
    if path != "/api/config":
        return 404, "text/plain", "not found"
    try:
        payload = _json.loads(body or "{}")
    except _json.JSONDecodeError:
        return _json_resp({"ok": False, "error": "json inválido"}, 400)
    key = str(payload.get("key", ""))
    value = payload.get("value")
    if any(h in key.lower() for h in _SECRET_HINT):
        return _json_resp({"ok": False, "error": "chave parece segredo — edite via `okami config set` (nunca pela web)"}, 400)
    if key not in _CONFIG_ALLOWLIST:
        return _json_resp({"ok": False, "error": f"chave '{key}' não é editável pela web (allowlist)"}, 400)
    try:
        res = _apply_config_set(key, value)
    except Exception as e:  # noqa: BLE001
        return _json_resp({"ok": False, "error": str(e)[:120]}, 400)
    return _json_resp(res, 200 if res.get("ok") else 400)


def default_providers(workspace: str = ".", agent: str = "okami") -> dict:
    """Providers reais (read-only) p/ `okami gui`: status, sessões (TranscriptStore), config (sanitizada,
    só nomes de env), logs (tail do gateway.log)."""
    def _status():
        return {"agent": agent, "status": "online"}

    def _sessions():
        try:
            from okami.gateway.sessions import TranscriptStore
            store = TranscriptStore(workspace).load_store()
            return [{"chat_id": k, "turns": (v.get("turns") if isinstance(v, dict) else ""),
                     "updated_at": (v.get("updated_at") if isinstance(v, dict) else "")} for k, v in store.items()]
        except Exception:  # noqa: BLE001
            return []

    def _config():
        import os
        try:
            from okami.config import load_config
            cfg = load_config()
            provs = list((getattr(cfg, "providers", None) or {}).keys()) if not isinstance(cfg, dict) else []
        except Exception:  # noqa: BLE001
            provs = []
        env_present = [k for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                                   "AWS_ACCESS_KEY_ID", "ELEVENLABS_API_KEY") if os.environ.get(k)]
        return {"providers": provs, "env_present": env_present}   # NUNCA os valores

    def _logs():
        from pathlib import Path
        for p in (Path(".okami") / "gateway.log",):
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
                except OSError:
                    return []
        return []

    def _session(sid: str):
        try:
            from okami.gateway.sessions import TranscriptStore
            hist = TranscriptStore(workspace).history(sid, limit=100)
            return [{"role": r, "text": t} for r, t in hist]   # tuplas → dicts p/ o JS
        except Exception:  # noqa: BLE001
            return []

    return {"status": _status, "sessions": _sessions, "config": _config, "logs": _logs, "session": _session}


_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", ""})


def public_bind_needs_token(host: str, token: str | None) -> bool:
    """True se está bindando num host PÚBLICO (não-loopback) SEM token — combinação recusada (self-host
    exposto exige autenticação)."""
    return (host or "") not in _LOOPBACK and not token


def serve_dashboard(port: int = 9119, *, host: str = "127.0.0.1", status_provider=None,
                    providers: dict | None = None, token: str | None = None,
                    certfile: str | None = None, keyfile: str | None = None):
    """Sobe o dashboard (bloqueante). `providers` = {status,sessions,config,logs,session}; `token` (opc)
    exige `Authorization: Bearer <token>` ou `?token=` nas rotas /api. Bind PÚBLICO (não-localhost) EXIGE
    token (recusa senão). `certfile`/`keyfile` → serve sob HTTPS (self-hosting com TLS)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse
    if public_bind_needs_token(host, token):
        raise ValueError(f"bind público em {host} SEM token é recusado — passe --token (ou bind em localhost).")
    if bool(certfile) != bool(keyfile):                 # meia-config de TLS serviria HTTP em silêncio (footgun)
        raise ValueError("TLS exige certfile E keyfile juntos (passe ambos --tls-cert e --tls-key, ou nenhum).")
    provs = dict(providers or {})
    if status_provider and "status" not in provs:
        provs["status"] = status_provider

    class _H(BaseHTTPRequestHandler):
        def _authorized(self, parsed) -> bool:
            if not token:
                return True
            hdr = self.headers.get("Authorization", "")
            if hdr == f"Bearer {token}":
                return True
            return (parse_qs(parsed.query).get("token") or [None])[0] == token

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            self._send(*route(parsed.path, providers=provs, token=token, authorized=self._authorized(parsed)))

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            self._send(*route_post(parsed.path, body, providers=provs, token=token,
                                   authorized=self._authorized(parsed)))

        def log_message(self, *a):
            return

    httpd = HTTPServer((host, port), _H)
    if certfile and keyfile:                            # self-hosting com TLS
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()


__all__ = ["render_status_html", "render_dashboard_html", "route", "default_providers", "serve_dashboard"]


def render_dashboard_html() -> str:
    """O app single-file (HTML+JS) — exposto p/ embed/teste."""
    return _APP_HTML
