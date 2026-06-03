"""Testes do turn-taking multi-agente (GroupRoom) — moderador/responder mockados."""

from __future__ import annotations

from okami.agents.group import GroupRoom, Member, parse_mentions


def test_user_scenario_cto_then_uiux_reacts_then_quiet():
    members = [Member("cto", "CTO"), Member("ui", "Manager UI/UX, defende ShadCN/HeroUI"),
               Member("backend", "Backend"), Member("qa", "QA")]

    def moderator(history, candidates, mentioned):
        cids = {c.id for c in candidates}
        who, txt = history[-1]
        if who == "USER" and "bootstrap" in txt.lower() and "cto" in cids:
            return "cto"
        if who == "cto" and "ui" in cids:        # UI/UX reage ao CTO
            return "ui"
        return None                              # ninguém mais → silêncio

    def responder(m, history):
        return {"cto": "Bora de Bootstrap então.",
                "ui": "Melhor ShadCN/HeroUI que Bootstrap (tokens, a11y, manutenção)."}.get(m.id, "PASS")

    room = GroupRoom(members, moderator, responder, cooldown=2)
    r1 = room.dispatch("USER", "CTO, quero usar Bootstrap no frontend")
    assert [a for a, _ in r1] == ["cto", "ui"]   # CTO fala, UI/UX intervém UMA vez (não os 4)

    room.select_speaker = lambda h, c, m: None   # nada relevante depois
    r2 = room.dispatch("USER", "beleza, obrigado")
    assert r2 == []                              # silêncio — ninguém spamma


def test_no_stampede_only_relevant_speaks():
    members = [Member(x) for x in ("a", "b", "c", "d", "e")]
    room = GroupRoom(members, select_speaker=lambda h, c, m: "c", respond=lambda m, h: f"{m.id} responde",
                     cooldown=2)
    # moderador escolhe 'c'; 'c' fala; depois 'c' em cooldown e moderador devolve... 'c' (inelegível) → None
    r = room.dispatch("USER", "alguém aí?")
    assert [a for a, _ in r] == ["c"]            # 1 resposta, não 5


def test_cooldown_caps_one_message_per_member_per_burst():
    members = [Member("a"), Member("b")]
    room = GroupRoom(members, select_speaker=lambda h, c, m: c[0].id if c else None,
                     respond=lambda m, h: f"{m.id}", cooldown=2, max_bot_streak=10)
    r = room.dispatch("USER", "vai")
    assert [a for a, _ in r] == ["a", "b"]        # cada um 1x; cooldown impede repetir no mesmo burst


def test_mention_forces_even_when_moderator_would_be_silent():
    members = [Member("a"), Member("b")]
    room = GroupRoom(members, select_speaker=lambda h, c, m: (c[0].id if m else None),
                     respond=lambda m, h: f"{m.id}!")
    r = room.dispatch("USER", "@b o que acha?", mentioned={"b"})
    assert [a for a, _ in r] == ["b"]


def test_agent_pass_is_silence_but_still_cooldown():
    members = [Member("a")]
    room = GroupRoom(members, select_speaker=lambda h, c, m: "a", respond=lambda m, h: "PASS")
    r = room.dispatch("USER", "oi")
    assert r == [] and members[0].cooldown_until > 0


def test_bot_streak_cap_stops_loop():
    members = [Member(f"m{i}") for i in range(8)]
    room = GroupRoom(members, select_speaker=lambda h, c, m: c[0].id if c else None,
                     respond=lambda m, h: m.id, cooldown=0, max_bot_streak=3)
    r = room.dispatch("USER", "vai")
    assert len(r) == 3                            # parou no cap, não percorreu os 8


def test_human_message_resets_bot_streak():
    members = [Member("a")]
    room = GroupRoom(members, select_speaker=lambda h, c, m: "a", respond=lambda m, h: "ok",
                     cooldown=0, max_bot_streak=2)
    room.dispatch("USER", "1")
    room.bot_streak = 99
    room.dispatch("USER", "2")                    # humano zera o streak
    assert room.bot_streak <= 2


def test_pass_then_next_eligible_speaks():
    # o moderador prefere 'a'; 'a' dá PASS → NÃO mata a rodada: 'b' ainda fala
    members = [Member("a"), Member("b")]

    def moderator(history, candidates, mentioned):
        cids = {c.id for c in candidates}
        return "a" if "a" in cids else ("b" if "b" in cids else None)

    def responder(m, history):
        return "PASS" if m.id == "a" else "oi do b"

    room = GroupRoom(members, moderator, responder, cooldown=2, max_bot_streak=5)
    r = room.dispatch("USER", "alguém?")
    assert [a for a, _ in r] == ["b"]                 # 'a' declinou, 'b' assumiu (não ficou mudo)


def test_agent_responder_uses_each_agents_own_model(tmp_path, monkeypatch):
    """Cada agente roda o SEU modelo (effective_config), credenciais globais, chamadas ISOLADAS."""
    import okami.llm.providers as prov_mod
    from okami.agents import AgentSpec
    from okami.agents.group import agent_responder

    global_raw = {
        "default_provider": "modp",                   # modelo barato do moderador (global)
        "providers": {                                # CREDENCIAIS/providers = GLOBAIS
            "modp": {"model": "m-mod", "context_window": 8000},
            "strong": {"model": "gpt-5.4", "context_window": 256000},
            "mini": {"model": "MiniMax-M3", "context_window": 1000000},
        },
    }
    (tmp_path / "cto").mkdir()
    (tmp_path / "ui").mkdir()
    agents = {  # cada agent.yaml escolhe SÓ o seu default_provider (modelo próprio)
        "cto": AgentSpec("cto", tmp_path / "cto", {"default_provider": "strong"}),
        "ui": AgentSpec("ui", tmp_path / "ui", {"default_provider": "mini"}),
    }

    seen: list[dict] = []

    def fake_complete(cfg, messages, provider=None, model=None, response_schema=None, **kw):
        key = provider or cfg.default_provider
        pc = cfg.provider(key)
        seen.append({"provider": key, "model": pc.model, "window": pc.context_window,
                     "providers_visiveis": sorted(cfg.providers)})
        return f"fala-{key}"

    monkeypatch.setattr(prov_mod, "complete_messages", fake_complete)

    respond = agent_responder(global_raw, agents)
    hist = [("USER", "qual stack?")]
    out_cto = respond(Member("cto", "CTO"), hist)
    out_ui = respond(Member("ui", "UI/UX"), hist)

    assert out_cto == "fala-strong" and out_ui == "fala-mini"     # cada um falou com SEU provider
    assert seen[0]["provider"] == "strong" and seen[0]["model"] == "gpt-5.4"
    assert seen[1]["provider"] == "mini" and seen[1]["model"] == "MiniMax-M3"
    assert seen[0]["window"] != seen[1]["window"]                 # JANELAS separadas (sessões isoladas)
    # CREDENCIAIS globais: ambos enxergam o mesmo bloco de providers; só o default_provider muda
    assert seen[0]["providers_visiveis"] == seen[1]["providers_visiveis"] == ["mini", "modp", "strong"]


def test_bot_corrects_bot_within_burst_hearing_colleague():
    # CTO decide algo; o moderador então elege a UI p/ CORRIGIR; a UI VÊ a fala do CTO no histórico
    members = [Member("cto", "CTO"), Member("ui", "UI/UX defende ShadCN")]

    def moderator(history, candidates, mentioned):
        cids = {c.id for c in candidates}
        who, _ = history[-1]
        if who == "USER" and "cto" in cids:
            return "cto"
        if who == "cto" and "ui" in cids:        # reage à fala do COLEGA (correção)
            return "ui"
        return None

    def responder(m, history):
        if m.id == "ui":
            assert any(s == "cto" for s, _ in history)   # ouviu o colega antes de corrigir
            return "na real, ShadCN é melhor que Bootstrap aqui"
        return "vamos de Bootstrap"

    room = GroupRoom(members, moderator, responder, cooldown=2, lead="cto")
    r = room.dispatch("USER", "qual lib de frontend?")
    assert [a for a, _ in r] == ["cto", "ui"]            # CTO fala, UI corrige (1x)


def test_lead_stop_ends_the_whole_burst():
    members = [Member("cto", "CTO"), Member("ui", "UI"), Member("be", "Backend")]
    room = GroupRoom(members, select_speaker=lambda h, c, m: (c[0].id if c else None),
                     respond=lambda m, h: "decidido, seguimos. STOP" if m.id == "cto" else "quero falar!",
                     cooldown=0, max_bot_streak=10, lead="cto")
    r = room.dispatch("USER", "pessoal?")
    assert [a for a, _ in r] == ["cto"]                  # CTO encerrou → ninguém mais fala
    assert r[0][1] == "decidido, seguimos."              # token STOP removido do texto


def test_nonlead_stop_only_silences_itself():
    members = [Member("cto", "CTO"), Member("ui", "UI")]
    # lead = 'ui'; o CTO dá STOP mas NÃO é o lead → só ele se cala, a UI ainda fala
    room = GroupRoom(members, select_speaker=lambda h, c, m: (c[0].id if c else None),
                     respond=lambda m, h: "STOP" if m.id == "cto" else "eu ainda falo",
                     cooldown=2, max_bot_streak=10, lead="ui")
    r = room.dispatch("USER", "oi")
    assert [a for a, _ in r] == ["ui"]                   # STOP de não-lead = silêncio só dele


def test_one_opinion_per_agent_per_burst():
    members = [Member("a"), Member("b")]
    # o moderador SEMPRE quer 'a', mas 'a' só fala uma vez por burst (deu opinião → escuta)
    room = GroupRoom(members, select_speaker=lambda h, c, m: ("a" if "a" in {x.id for x in c} else None),
                     respond=lambda m, h: f"{m.id} fala", cooldown=0, max_bot_streak=10)
    r = room.dispatch("USER", "vai")
    assert [a for a, _ in r] == ["a"]                    # não fala 2x nem com cooldown=0


def test_parse_mentions():
    assert parse_mentions("oi @ui-manager e @cto, blz?", {"ui-manager", "cto", "qa"}) == {"ui-manager", "cto"}
