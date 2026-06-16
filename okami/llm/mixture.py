"""Mixture-of-Agents (#17, port do Hermes tools/mixture_of_agents_tool.py).

Roteia um problema difícil por VÁRIOS modelos e sintetiza a melhor resposta — amplificação de raciocínio.
Diferença-chave do Hermes: ele usa OpenRouter (pool de chaves de N vendors). O Okami é **assinatura-only**
(sem pool de chaves), então a camada de referência usa os PROVIDERS QUE O DONO JÁ TEM configurados
(codex/claude/minimax/gemini/…), em paralelo, e sintetiza com o mais forte (o aggregator).

Algoritmo (2 camadas, igual ao Hermes):
  1. fan-out: o MESMO prompt vai pra cada provider de referência em paralelo (tolera falha de alguns);
  2. agregação: o provider aggregator recebe um system com TODAS as respostas + o prompt original e
     sintetiza UMA resposta refinada.

As peças puras (prompt de agregação, escolha de providers, shaping do resultado) são testáveis sem rede;
a chamada ao modelo é injetável (`_complete`) p/ teste offline.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

# Prompt de agregação — port verbatim do Hermes (AGGREGATOR_SYSTEM_PROMPT).
AGGREGATOR_SYSTEM_PROMPT = (
    "Você recebeu um conjunto de respostas de vários modelos para a consulta do usuário. Sua tarefa é "
    "sintetizá-las numa única resposta de alta qualidade. Avalie criticamente: parte do conteúdo pode "
    "estar enviesado ou incorreto. NÃO apenas replique as respostas — ofereça uma réplica refinada, "
    "precisa e abrangente, bem estruturada e coerente, com o mais alto padrão de exatidão e confiabilidade.\n\n"
    "Respostas dos modelos:"
)

_MIN_SUCCESSFUL = 1          # mínimo de referências bem-sucedidas p/ seguir (igual ao Hermes)
_MAX_REFERENCES = 4         # teto de providers de referência (custo/latência)


def construct_aggregator_prompt(system_prompt: str, responses: list[str]) -> str:
    """System final do aggregator: o prompt-base + as respostas enumeradas, cada uma EMBRULHADA como DADO
    não-confiável (um provider comprometido/jailbroken não injeta instrução no system do aggregator). Pura."""
    from okami.core.tools.base import untrusted_wrap
    body = "\n".join(f"{i + 1}.\n{untrusted_wrap('mixture-ref', r)}" for i, r in enumerate(responses))
    return f"{system_prompt}\n\n{body}"


def reference_providers_for(cfg) -> list[str]:
    """Providers de REFERÊNCIA: a lista `mixture.reference_providers` do config, ou todos os configurados
    (até _MAX_REFERENCES). Assinatura-only — só o que o dono já tem; sem inventar vendor."""
    mix = (getattr(cfg, "mixture", None) or {}) if not isinstance(cfg, dict) else (cfg.get("mixture") or {})
    chosen = list(mix.get("reference_providers") or [])
    configured = list((getattr(cfg, "providers", None) or {}).keys())
    if chosen:
        refs = [p for p in chosen if p in configured]      # ignora provider inexistente (fail-open)
    else:
        refs = configured
    return refs[:_MAX_REFERENCES]


def aggregator_for(cfg) -> str:
    """Provider AGGREGATOR (o sintetizador mais forte): `mixture.aggregator` ou o default_provider."""
    mix = (getattr(cfg, "mixture", None) or {}) if not isinstance(cfg, dict) else (cfg.get("mixture") or {})
    configured = (getattr(cfg, "providers", None) or {})
    agg = mix.get("aggregator")
    if agg and agg in configured:
        return agg
    return getattr(cfg, "default_provider", "") or (next(iter(configured), "") if configured else "")


def run_mixture(cfg, prompt: str, *, reference_providers: list[str] | None = None,
                aggregator: str | None = None, _complete=None, max_workers: int = 4) -> dict:
    """Roda a mistura: fan-out → agregação. Devolve {success, response, models_used, errors}.
    `_complete(provider, messages) -> str` injetável (teste offline). Sem rede aqui além do `_complete`."""
    refs = list(reference_providers if reference_providers is not None else reference_providers_for(cfg))
    agg = aggregator or aggregator_for(cfg)

    def _default_complete(provider, messages):
        from okami.llm import providers as prov
        return prov.complete_messages(cfg, messages, provider=provider)

    complete = _complete or _default_complete
    used = {"reference_providers": refs, "aggregator": agg, "total_calls": len(refs) + 1}
    if not refs:
        return {"success": False, "response": "Mixture indisponível: nenhum provider de referência configurado.",
                "models_used": used, "errors": ["sem providers"]}

    user_msg = [{"role": "user", "content": prompt}]

    def _one(provider):
        try:
            return (provider, str(complete(provider, user_msg) or ""), True)
        except Exception as e:  # noqa: BLE001 — falha de UM provider não derruba a mistura
            return (provider, str(e)[:200], False)

    responses, errors = [], []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(refs)))) as ex:
        for provider, content, ok in ex.map(_one, refs):
            if ok and content.strip():
                responses.append(content)
            else:
                errors.append(provider)

    if len(responses) < _MIN_SUCCESSFUL:
        return {"success": False,
                "response": "Mixture falhou: nenhuma referência respondeu. Use um modelo só.",
                "models_used": used, "errors": errors}

    agg_system = construct_aggregator_prompt(AGGREGATOR_SYSTEM_PROMPT, responses)
    try:
        final = str(complete(agg, [{"role": "system", "content": agg_system},
                                   {"role": "user", "content": prompt}]) or "")
    except Exception as e:  # noqa: BLE001 — aggregator caiu: devolve a melhor referência crua
        final = responses[0]
        errors.append(f"aggregator:{str(e)[:120]}")
    if not final.strip():                                  # aggregator vazio → cai na 1ª referência
        final = responses[0]
    return {"success": True, "response": final, "models_used": used,
            "errors": errors, "n_references": len(responses)}


def mixture_summary_json(result: dict) -> str:
    """Serializa o resultado (p/ o retorno da tool) — JSON estável, não-ASCII preservado."""
    return json.dumps(result, indent=2, ensure_ascii=False)
