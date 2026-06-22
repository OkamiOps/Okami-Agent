"""Registro DECLARATIVO de tools (P2 #14 — a mesma jogada do command registry, agora p/ as tools).

Uma linha de metadata por tool: categoria, tier (disclosure progressivo) e perigo (sensibilidade,
alinhado com a classificação de aprovação). Dela saem `okami tools`, o /tools do gateway e a base p/
disclosure/policy por tier. A IMPLEMENTAÇÃO da tool segue em core/tools.py — aqui é só o CATÁLOGO.

Um teste garante que TODA tool de default_registry() tem metadata aqui (sem drift silencioso) e que
o flag `terminal` bate com a tool real — então adicionar uma tool obriga a registrá-la aqui.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str            # conversa | arquivo | shell | memória | skill | web | mídia | subagente | controle
    tier: str = "standard"   # essential | standard | power
    danger: str = "safe"     # safe | sensitive | dangerous
    terminal: bool = False


TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec("respond", "conversa", tier="essential", terminal=True),
    ToolSpec("read_file", "arquivo", tier="essential"),
    ToolSpec("write_file", "arquivo", tier="essential", danger="sensitive"),
    ToolSpec("edit_file", "arquivo", danger="sensitive"),
    ToolSpec("apply_patch", "arquivo", danger="sensitive"),
    ToolSpec("list_dir", "arquivo", tier="essential"),
    ToolSpec("find_files", "arquivo"),
    ToolSpec("search_files", "arquivo"),
    ToolSpec("make_dir", "arquivo", danger="sensitive"),
    ToolSpec("move_path", "arquivo", danger="sensitive"),
    ToolSpec("copy_path", "arquivo", danger="sensitive"),
    ToolSpec("delete_path", "arquivo", danger="sensitive"),
    ToolSpec("schedule_job", "automação", danger="sensitive"),
    ToolSpec("run_shell", "shell", tier="essential", danger="dangerous"),
    ToolSpec("execute_code", "shell", tier="power", danger="dangerous"),
    ToolSpec("process_start", "processo", tier="power", danger="dangerous"),
    ToolSpec("process_poll", "processo"),
    ToolSpec("process_wait", "processo"),
    ToolSpec("process_log", "processo"),
    ToolSpec("process_list", "processo"),
    ToolSpec("process_write", "processo", danger="sensitive"),
    ToolSpec("process_signal", "processo", danger="sensitive"),
    ToolSpec("process_kill", "processo", danger="sensitive"),
    ToolSpec("remember", "memória"),
    ToolSpec("recall_memory", "memória"),
    ToolSpec("remember_user", "memória"),
    ToolSpec("session_search", "memória"),
    ToolSpec("use_skill", "skill"),
    ToolSpec("manage_skill", "skill", tier="power", danger="sensitive"),
    ToolSpec("install_skill", "skill", tier="power", danger="dangerous"),
    ToolSpec("spawn", "subagente", tier="power", danger="sensitive"),
    ToolSpec("mixture_of_agents", "raciocínio", tier="power"),
    ToolSpec("computer_use", "desktop", tier="power", danger="dangerous"),
    ToolSpec("browse", "web", tier="power", danger="sensitive"),
    ToolSpec("web_search", "web"),
    ToolSpec("x_search", "web"),
    ToolSpec("homeassistant", "integração", tier="power", danger="sensitive"),
    ToolSpec("feishu_doc_read", "integração"),
    ToolSpec("web_extract", "web"),
    ToolSpec("generate_image", "mídia", tier="power"),
    ToolSpec("generate_video", "mídia", tier="power"),
    ToolSpec("vision_analyze", "mídia"),
    ToolSpec("audio_analyze", "mídia"),                       # #7: transcreve áudio (whisper local)
    ToolSpec("text_to_speech", "mídia"),                      # #10: responde em voz (MEDIA: → bolha de voz)
    ToolSpec("notify", "controle"),                           # #7: mensagem ao dono fora do turno
    ToolSpec("send_message", "controle", danger="sensitive"),  # entrega direta a um canal/target (sem LLM)
    ToolSpec("clarify", "controle"),                          # #8: pergunta ao dono antes de agir (ambiguidade)
    ToolSpec("suggest_automation", "automação"),              # #8: propõe automação consent-first (dono aceita)
    ToolSpec("todo_write", "controle"),                       # #7: checklist operacional (sobrevive compactação)
    ToolSpec("store_secret", "controle", danger="sensitive"),  # guarda credencial no cofre (.env 0600)
    ToolSpec("remote_connect", "shell", tier="power", danger="sensitive"),   # entra numa máquina remota (SSH/Tailscale)
    ToolSpec("remote_disconnect", "shell"),                    # volta ao ambiente local
    ToolSpec("tool_search", "controle"),
    ToolSpec("finish_setup", "controle"),
    ToolSpec("task_complete", "controle", tier="essential", terminal=True),
    ToolSpec("task_blocked", "controle", terminal=True),
    ToolSpec("need_input", "controle", terminal=True),
)

_BY_NAME: dict[str, ToolSpec] = {s.name: s for s in TOOL_REGISTRY}
_CAT_ORDER = ("conversa", "arquivo", "shell", "processo", "memória", "skill", "web", "mídia", "subagente", "controle")


def spec(name: str) -> ToolSpec | None:
    return _BY_NAME.get(name)


def by_category(names=None) -> dict[str, list[ToolSpec]]:
    """{categoria: [specs]} na ordem canônica. `names` filtra (ex.: só as tools registradas)."""
    keep = set(names) if names is not None else None
    cats: dict[str, list[ToolSpec]] = {}
    for s in TOOL_REGISTRY:
        if keep is None or s.name in keep:
            cats.setdefault(s.category, []).append(s)
    ordered: dict[str, list[ToolSpec]] = {c: cats[c] for c in _CAT_ORDER if c in cats}
    for c in sorted(cats):                       # categorias fora da ordem canônica (futuras)
        ordered.setdefault(c, cats[c])
    return ordered


def missing(names) -> list[str]:
    """Tools registradas em runtime SEM metadata aqui (drift a corrigir)."""
    return [n for n in names if n not in _BY_NAME]
