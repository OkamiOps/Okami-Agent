"""Biblioteca compartilhada de threat-patterns p/ varredura de janela de contexto (#11, port do
Hermes tools/threat_patterns.py).

Fonte ÚNICA de padrões de prompt-injection / promptware / exfiltração usados pelos scanners de
montagem de contexto: arquivo de convenção (AGENTS.md/CLAUDE.md/.cursorrules via subdir_hints), e —
como camada adicional — escrita de memória/skill. Complementa (não substitui) o skill_security.py.

Filosofia: padrões por CLASSE DE ATAQUE, cada um com um `scope` que controla onde se aplica:
- "all"     — em todo lugar (injeção clássica, exfil) — falso-positivo mínimo, serve p/ qualquer texto.
- "context" — +promptware/C2/role-hijack — arquivo de contexto + memória + tool-result (detecção ampla).
- "strict"  — +SSH/persistência/exfil-URL — escrita mediada pelo usuário (memória/skill), onde um
              falso-positivo dá pra resolver na hora.

Anti-bypass por filler: `(?:\\w+\\s+)*` entre tokens-chave impede "ignore all PRIOR instructions"
escapar de "ignore all instructions". Âncora em VOCABULÁRIO de ataque (C2, anti-forense), não em inglês
mandão ("you must" sozinho é comum em AGENTS.md legítimo → não dispara).
"""
from __future__ import annotations

import re

# (regex, pattern_id, scope) — scope ∈ {"all","context","strict"}
_PATTERNS: list[tuple[str, str, str]] = [
    # ── Injeção de prompt clássica (todo lugar) ──
    (r"ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+(?:\w+\s+)*instructions", "prompt_injection", "all"),
    (r"system\s+prompt\s+override", "sys_prompt_override", "all"),
    (r"disregard\s+(?:\w+\s+)*(your|all|any)\s+(?:\w+\s+)*(instructions|rules|guidelines)", "disregard_rules", "all"),
    (r"act\s+as\s+(if|though)\s+(?:\w+\s+)*you\s+(?:\w+\s+)*(have\s+no|don'?t\s+have)\s+(?:\w+\s+)*(restrictions|limits|rules)", "bypass_restrictions", "all"),
    (r"<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->", "html_comment_injection", "all"),
    (r"<\s*div\s+style\s*=\s*[\"'][\s\S]*?display\s*:\s*none", "hidden_div", "all"),
    (r"translate\s+.*\s+into\s+.*\s+and\s+(execute|run|eval)", "translate_execute", "all"),
    (r"do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user", "deception_hide", "all"),

    # ── Role-play / sequestro de identidade (context) ──
    (r"you\s+are\s+(?:\w+\s+)*now\s+(?:a|an|the)\s+", "role_hijack", "context"),
    (r"pretend\s+(?:\w+\s+)*(you\s+are|to\s+be)\s+", "role_pretend", "context"),
    (r"output\s+(?:\w+\s+)*(system|initial)\s+prompt", "leak_system_prompt", "context"),
    (r"(respond|answer|reply)\s+without\s+(?:\w+\s+)*(restrictions|limitations|filters|safety)", "remove_filters", "context"),
    (r"you\s+have\s+been\s+(?:\w+\s+)*(updated|upgraded|patched)\s+to", "fake_update", "context"),
    (r"\bname\s+yourself\s+\w+", "identity_override", "context"),

    # ── C2 / promptware estilo Brainworm (context) — vocabulário C2-específico; WARN, não block ──
    (r"register\s+(as\s+)?a?\s*node", "c2_node_registration", "context"),
    (r"(heartbeat|beacon|check[\s\-]?in)\s+(to|with)\s+", "c2_heartbeat", "context"),
    (r"pull\s+(down\s+)?(?:new\s+)?task(?:ing|s)?\b", "c2_task_pull", "context"),
    (r"connect\s+to\s+the\s+network\b", "c2_network_connect", "context"),
    (r"you\s+must\s+(?:\w+\s+){0,3}(register|connect|report|beacon)\b", "forced_action", "context"),
    (r"only\s+use\s+one[\s\-]?liners?\b", "anti_forensic_oneliner", "context"),
    (r"never\s+(?:\w+\s+)*(?:create|write)\s+(?:\w+\s+)*(?:script|file)\s+(?:\w+\s+)*disk", "anti_forensic_disk", "context"),
    # unset de var de runtime de agente (OKAMI/CODEX/CLAUDE/HERMES/OPENAI/ANTHROPIC) — puro ataque
    (r"unset\s+\w*(?:OKAMI|CLAUDE|CODEX|HERMES|AGENT|OPENAI|ANTHROPIC)\w*", "env_var_unset_agent", "context"),

    # ── Nomes de framework C2/red-team (≈zero falso-positivo fora de pesquisa de segurança) ──
    (r"\b(?:praxis|cobalt\s*strike|sliver|havoc|mythic|metasploit|brainworm)\b", "known_c2_framework", "context"),
    (r"\bc2\s+(?:server|channel|infrastructure|beacon)\b", "c2_explicit", "context"),
    (r"\bcommand\s+and\s+control\b", "c2_explicit_long", "context"),

    # ── Exfiltração via curl/wget/cat com segredo (todo lugar) ──
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_curl", "all"),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_wget", "all"),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets", "all"),
    (r"(send|post|upload|transmit)\s+.*\s+(to|at)\s+https?://", "send_to_url", "strict"),
    (r"(include|output|print|share)\s+(?:\w+\s+)*(conversation|chat\s+history|previous\s+messages|full\s+context|entire\s+context)", "context_exfil", "strict"),

    # ── Persistência / backdoor SSH (strict — memória + skills) ──
    (r"authorized_keys", "ssh_backdoor", "strict"),
    (r"\$HOME/\.ssh|~/\.ssh", "ssh_access", "strict"),
    (r"\$HOME/\.okami/\.env|~/\.okami/\.env", "okami_env", "strict"),
    (r"(update|modify|edit|write|change|append|add\s+to)\s+.*(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules)", "agent_config_mod", "strict"),
    (r"(update|modify|edit|write|change|append|add\s+to)\s+.*\.okami/(config\.yaml|SOUL\.md)", "okami_config_mod", "strict"),

    # ── Segredo hardcoded ──
    (r"(?:api[_-]?key|token|secret|password)\s*[=:]\s*[\"'][A-Za-z0-9+/=_-]{20,}", "hardcoded_secret", "strict"),
]

# Unicode invisível / bidirecional usado em ataque de injeção (Trojan Source). Alinhado ao skill_security.
# Construído por CODEPOINT de propósito — manter os caracteres literais aqui faria o PRÓPRIO arquivo
# conter bidi-control (bandit B613/trojansource). zero-width + word-joiner + invisible-math + RTL/LTR isolates.
INVISIBLE_CHARS = frozenset(chr(cp) for cp in (
    0x200B, 0x200C, 0x200D, 0x2060, 0x2062, 0x2063, 0x2064, 0xFEFF,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
))

_COMPILED: dict[str, list[tuple[re.Pattern, str]]] = {}


def _compile() -> None:
    """Compila os conjuntos por scope. 'all' entra em todos; 'context' em context+strict; 'strict' só strict."""
    if _COMPILED:
        return
    all_p: list[tuple[re.Pattern, str]] = []
    ctx_p: list[tuple[re.Pattern, str]] = []
    strict_p: list[tuple[re.Pattern, str]] = []
    for pattern, pid, scope in _PATTERNS:
        entry = (re.compile(pattern, re.IGNORECASE), pid)
        if scope == "all":
            all_p.append(entry)
            ctx_p.append(entry)
            strict_p.append(entry)
        elif scope == "context":
            ctx_p.append(entry)
            strict_p.append(entry)
        elif scope == "strict":
            strict_p.append(entry)
        else:
            raise ValueError(f"threat_patterns: scope desconhecido {scope!r} no padrão {pid!r}")
    _COMPILED.update(all=all_p, context=ctx_p, strict=strict_p)


_compile()


def scan_for_threats(content: str, scope: str = "context") -> list[str]:
    """IDs de padrão casados em `content` no `scope` dado (+ unicode invisível como
    'invisible_unicode_U+XXXX'). Lista vazia = limpo."""
    if not content:
        return []
    findings: list[str] = []
    for ch in set(content) & INVISIBLE_CHARS:
        findings.append(f"invisible_unicode_U+{ord(ch):04X}")
    patterns = _COMPILED.get(scope)
    if patterns is None:
        raise ValueError(f"scan_for_threats: scope desconhecido {scope!r}")
    # #11-fix: também varre uma cópia SEM ênfase markdown (* _ ~ `) — 'ignore **all** instructions'
    # escapava o filler \w+. Remover esses chars não cria match espúrio (só desofusca). Union dos IDs.
    import re as _re
    sources = [content]
    if any(c in content for c in "*_~`"):
        sources.append(_re.sub(r"[*_~`]+", "", content))
    seen: set[str] = set()
    for src in sources:
        for compiled, pid in patterns:
            if pid not in seen and compiled.search(src):
                seen.add(pid)
                findings.append(pid)
    return findings


def first_threat_message(content: str, scope: str = "strict") -> str | None:
    """String legível p/ a 1ª ameaça encontrada, ou None. Usado por caminhos que barram no 1º hit."""
    findings = scan_for_threats(content, scope=scope)
    if not findings:
        return None
    pid = findings[0]
    if pid.startswith("invisible_unicode_"):
        cp = pid.replace("invisible_unicode_", "")
        return f"Bloqueado: conteúdo tem caractere unicode invisível {cp} (possível injeção)."
    return (f"Bloqueado: conteúdo casa o padrão de ameaça '{pid}'. O conteúdo entraria no system prompt "
            "e não pode conter payload de injeção/exfiltração.")


__all__ = ["INVISIBLE_CHARS", "scan_for_threats", "first_threat_message"]
