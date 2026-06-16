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
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){
 app.innerHTML='<div class="card muted">carregando…</div>';
 try{const r=await fetch('/api/'+tab);const d=await r.json();render(d);}catch(e){app.innerHTML='<div class="card">erro: '+esc(e)+'</div>';}
}
function kv(o){return '<table>'+Object.entries(o||{}).map(([k,v])=>'<tr><th>'+esc(k)+'</th><td>'+(Array.isArray(v)?v.map(x=>'<span class=tag>'+esc(x)+'</span>').join(''):esc(v))+'</td></tr>').join('')+'</table>';}
function render(d){
 if(tab==='status'){app.innerHTML='<div class="card">'+kv(d)+'</div>';}
 else if(tab==='sessions'){app.innerHTML='<div class="card">'+((d&&d.length)?'<table><tr><th>chat</th><th>turnos</th><th>atualizado</th></tr>'+d.map(s=>'<tr><td>'+esc(s.chat_id)+'</td><td>'+esc(s.turns||'')+'</td><td>'+esc(s.updated_at||'')+'</td></tr>').join('')+'</table>':'<span class=muted>sem sessões</span>')+'</div>';}
 else if(tab==='config'){app.innerHTML='<div class="card">'+kv(d)+'<p class=muted>read-only · nomes de env, nunca valores</p></div>';}
 else{app.innerHTML='<div class="card"><pre>'+((d&&d.length)?d.map(esc).join('\\n'):'<span class=muted>sem logs</span>')+'</pre></div>';}
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));b.classList.add('active');tab=b.dataset.t;load();});
load();setInterval(()=>{if(tab==='status'||tab==='logs')load();},5000);
</script></body></html>"""


def route(path: str, *, providers: dict | None = None) -> tuple:
    """Roteamento puro: (code, content_type, body). `/` = app; `/api/<x>` = JSON do provider `<x>`."""
    providers = providers or {}
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", _APP_HTML
    if path == "/healthz":
        return 200, "text/plain", "ok"
    if path.startswith("/api/"):
        key = path[len("/api/"):]
        prov = providers.get(key)
        try:
            data = prov() if callable(prov) else ([] if key in ("sessions", "logs") else {})
        except Exception as e:  # noqa: BLE001 — provider quebrado NÃO vira 500
            data = {"error": str(e)[:120]}
        return 200, "application/json; charset=utf-8", _json.dumps(data, ensure_ascii=False, default=str)
    return 404, "text/plain", "not found"


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

    return {"status": _status, "sessions": _sessions, "config": _config, "logs": _logs}


def serve_dashboard(port: int = 9119, *, host: str = "127.0.0.1", status_provider=None, providers: dict | None = None):
    """Sobe o dashboard (bloqueante). `providers` = dict {status,sessions,config,logs}; `status_provider`
    é compat (vira providers['status'])."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    provs = dict(providers or {})
    if status_provider and "status" not in provs:
        provs["status"] = status_provider

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            code, ctype, body = route(self.path, providers=provs)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *a):
            return

    HTTPServer((host, port), _H).serve_forever()


__all__ = ["render_status_html", "render_dashboard_html", "route", "default_providers", "serve_dashboard"]


def render_dashboard_html() -> str:
    """O app single-file (HTML+JS) — exposto p/ embed/teste."""
    return _APP_HTML
