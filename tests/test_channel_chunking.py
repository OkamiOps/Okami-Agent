"""Paridade Hermes (#2 do sweep): canal não-Telegram não fatiava — resposta longa era truncada/recusada
(Discord recusa >2000). Agora cada canal com MAX_LEN manda a resposta INTEIRA em partes, na fronteira."""
from __future__ import annotations

from okami.channels.base import split_text


def test_split_prefers_boundary_and_respects_limit():
    text = "parágrafo um.\n\n" + ("frase longa. " * 300)
    parts = split_text(text, 500)
    assert len(parts) > 1 and all(len(p) <= 500 for p in parts)
    assert "".join(parts).replace(" ", "") .startswith("parágrafoum.")   # nada perdido (fora espaços)


def test_split_short_or_no_limit_single_part():
    assert split_text("curto", 2000) == ["curto"]
    assert split_text("qualquer", 0) == ["qualquer"]    # 0 = não fatia


def test_discord_send_chunks_over_2000(monkeypatch):
    from okami.channels.discord import DiscordChannel
    c = DiscordChannel.__new__(DiscordChannel)           # sem __init__ (sem token)
    posts = []
    monkeypatch.setattr(c, "_post", lambda path, body: posts.append(body["content"]))
    c.send("chan", "x" * 5000)
    assert len(posts) >= 3 and all(len(p) <= 2000 for p in posts)   # Discord recusaria 5000 numa msg só
