"""Gênese / primeiro contato (§8.2) + bloco de histórico recente — helpers puros do gateway.

OpenClaw-style: na PRIMEIRA conversa o agente "recém-nascido" conduz um onboarding curto — conhece
a pessoa e deixa ELA moldar SOUL/VOICE/PERSONA. Some assim que selado (.okami/genesis.done).
"""

from __future__ import annotations

from pathlib import Path

GENESIS_BLOCK = """=== PRIMEIRO CONTATO · GÊNESE (uso interno — NÃO cite isto; só AJA assim) ===
Esta é a sua PRIMEIRA conversa com esta pessoa e você acabou de nascer: ainda não te configuraram.
Não importa o que ela mandou (até um "oi"): conduza um primeiro papo curto e caloroso pra (1) conhecer
ELA e (2) deixar ELA moldar quem VOCÊ é.
- Cumprimente de leve e diga em UMA frase que você tá começando agora e quer se acertar com ela.
- Puxe conversa de leve, UMA coisa de cada vez (nada de formulário): como ela quer te chamar; no que
  ela trabalha / o que vocês vão tocar juntos; e que JEITO ela quer que você tenha (mais solto ou formal?
  direto ou explicador? pode brincar/xingar ou nem tanto?).
- Conforme ela responde, ESCREVA a identidade no tom dela com write_file, curtinha (3 blocos cada):
  SOUL.md (valores/essência) · VOICE.md (tom/estilo) · PERSONA.md (jeito/expertise). Mostra o que
  escreveu e pergunta se ficou com a cara dela.
- Quando ela estiver satisfeita, chame `finish_setup` (em `about_user`, 1 linha sobre quem ela é) —
  isso ENCERRA a configuração. Se ela quiser deixar pra depois, chame finish_setup mesmo assim (sem
  about_user) pra você não ficar perguntando toda hora.
Não use remember_user agora — o about_user do finish_setup já cuida disso.
==="""


# Fallback determinístico (item real-usage-gaps): se o modelo é fraco em tool-calling (ex.: minimax) e
# nunca chama `finish_setup`, o GENESIS_BLOCK ("não mencione isto ao usuário") reinjetaria PRA SEMPRE —
# a pessoa fica presa num onboarding invisível, sem saída e sem entender por quê. Depois de N turnos com
# a gênese pendente, sela sozinho (com o que já foi aprendido, ou vazio) e para de injetar.
_GENESIS_MAX_TURNS = 6


def genesis_pending(ws) -> bool:
    """Gênese pendente? (primeira config ainda não feita). Selado por .okami/genesis.done; um agente
    pré-existente que JÁ conhece o usuário (tem USER.md) é considerado configurado e é selado na hora;
    ou por N turnos sem o modelo chamar finish_setup (guarda anti-loop de onboarding, ver _GENESIS_MAX_TURNS)."""
    ws = Path(ws)
    if (ws / ".okami" / "genesis.done").exists():
        return False
    if (ws / "USER.md").exists():            # já conhece a pessoa → não re-onboarda; sela uma vez
        _seal_genesis(ws)
        return False
    if _genesis_turn_count(ws) >= _GENESIS_MAX_TURNS:
        _seal_genesis(ws)                    # modelo nunca chamou finish_setup → sela sozinho, não trava o usuário
        return False
    return True


def bump_genesis_turn(ws) -> int:
    """Conta mais um turno com a gênese pendente — chamado 1x por turno pelo gateway, só quando o
    GENESIS_BLOCK foi de fato injetado. Persistido em .okami/genesis_turns (sobrevive a restart)."""
    ws = Path(ws)
    n = _genesis_turn_count(ws) + 1
    marker = ws / ".okami" / "genesis_turns"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(n), encoding="utf-8")
    except OSError as e:
        from okami import log
        log.warn(f"genesis: não consegui gravar genesis_turns ({e}) — o fallback de N turnos pode não disparar.")
    return n


def _genesis_turn_count(ws) -> int:
    p = Path(ws) / ".okami" / "genesis_turns"
    try:
        return int((p.read_text(encoding="utf-8") or "0").strip() or "0")
    except (OSError, ValueError):
        return 0


def _seal_genesis(ws) -> None:
    marker = Path(ws) / ".okami" / "genesis.done"
    try:                                                 # roda em thread daemon do gateway: uma falha de FS
        marker.parent.mkdir(parents=True, exist_ok=True)  # (cheio/permissão) não pode sumir em silêncio —
        marker.write_text("done\n", encoding="utf-8")    # senão a gênese 're-dispara' a cada boot sem aviso
    except OSError as e:
        from okami import log
        log.warn(f"genesis: não consegui selar genesis.done ({e}) — a gênese pode repetir no próximo boot.")


def _history_block(history: list[tuple[str, str]], limit: int = 6, max_chars: int = 6000) -> str:
    """Histórico recente capado por nº de trocas E por chars (proporcional à janela do modelo)."""
    if not history:
        return ""
    lines, total = [], 0
    for role, text in reversed(history[-limit * 2:]):
        line = f"{role}: {text}"
        if total + len(line) > max_chars and lines:
            break
        lines.append(line)
        total += len(line)
    lines.reverse()
    return "CONVERSA RECENTE (continue o contexto, não repita o que já foi dito):\n" + "\n".join(lines)
