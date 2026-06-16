"""#11 Onda 3: UX do gateway/Telegram — silêncio multi-marcador, display-config por plataforma,
auto-extração de imagem do texto, merge de álbum + dedup de legenda, heartbeat, panic-hook."""
from __future__ import annotations


# ── silêncio multi-marcador (port response_filters) ──
def test_silence_recognizes_canonical_markers():
    from okami.gateway.silence import is_intentional_silence
    for m in ("NO_REPLY", "SILENT", "[SILENT]", "NO REPLY", "  no_reply  ", "[silent]"):
        assert is_intentional_silence(m), m


def test_silence_rejects_long_or_substantive_text():
    from okami.gateway.silence import is_intentional_silence
    assert not is_intentional_silence("SILENT but actually here is a long real answer about the topic " * 2)
    assert not is_intentional_silence("aqui vai a resposta de verdade")
    assert not is_intentional_silence("")


def test_silence_scheduler_uses_marker_set():
    from okami.automation.scheduler import delivery_decision
    assert delivery_decision("NO_REPLY")[0] is False       # novo marcador também corta entrega
    assert delivery_decision("[SILENT] nada novo")[0] is False
    assert delivery_decision("relatório real")[0] is True


# ── display-config em tiers por plataforma ──
def test_display_config_platform_precedence():
    from okami.gateway.display_config import resolve_display_setting
    cfg = {"display": {"global": {"tool_progress": True}, "slack": {"tool_progress": False}}}
    assert resolve_display_setting(cfg, "slack", "tool_progress") is False   # per-plataforma vence global
    assert resolve_display_setting(cfg, "telegram", "tool_progress") is True  # cai no global do usuário


def test_display_config_platform_defaults():
    from okami.gateway.display_config import resolve_display_setting
    # sem config do usuário → default por plataforma (Slack não edita → sem tool_progress)
    assert resolve_display_setting({}, "slack", "tool_progress") is False
    assert resolve_display_setting({}, "telegram", "tool_progress") is True
    assert resolve_display_setting({}, "telegram", "long_running_notifications") is True


# ── auto-extração de imagem do texto (paths + URLs) ──
def test_extract_image_refs_paths_and_urls():
    from okami.gateway.image_refs import extract_image_refs
    paths, urls = extract_image_refs("olha ~/shot.png e https://x.com/a.jpg por favor")
    assert any("shot.png" in p for p in paths)
    assert "https://x.com/a.jpg" in urls


def test_extract_image_refs_skips_code_blocks():
    from okami.gateway.image_refs import extract_image_refs
    paths, urls = extract_image_refs("texto\n```\nveja /tmp/x.png aqui\n```\nfora /tmp/y.png")
    assert any("y.png" in p for p in paths) and not any("x.png" in p for p in paths)


# ── panic-hook (crash log do gateway/TUI) ──
def test_panic_hook_writes_crash_log(tmp_path):
    from okami.gateway.panic_hook import format_crash, write_crash
    try:
        raise ValueError("boom interno")
    except ValueError as e:
        line = format_crash(type(e), e, e.__traceback__)
        log = tmp_path / "crash.log"
        write_crash(log, type(e), e, e.__traceback__)
    assert "ValueError" in line and "boom interno" in line       # 1-linha p/ stderr
    body = log.read_text(encoding="utf-8")
    assert "ValueError: boom interno" in body and "Traceback" in body   # traceback completo no arquivo


# ── heartbeat de turno longo ──
def test_heartbeat_due_after_interval():
    from okami.gateway.heartbeat import heartbeat_due
    # primeiro tick: due após `interval` desde o start; depois, a cada `interval` desde o last
    assert heartbeat_due(start=0.0, now=12.0, interval=10.0, last=0.0) is True
    assert heartbeat_due(start=0.0, now=8.0, interval=10.0, last=0.0) is False
    assert heartbeat_due(start=0.0, now=25.0, interval=10.0, last=12.0) is True   # >10s desde o last


def test_heartbeat_message_has_elapsed_minutes():
    from okami.gateway.heartbeat import heartbeat_message
    msg = heartbeat_message(elapsed_s=185.0)
    assert "3" in msg and ("min" in msg.lower())                 # "ainda trabalhando, ~3 min"


# ── merge de álbum de fotos + dedup de legenda (coalesce) ──
def test_caption_merge_dedups_by_line():
    from okami.gateway.coalesce import merge_caption
    assert merge_caption("Reunião", "Reunião") == "Reunião"      # idêntica → não duplica
    out = merge_caption("Reunião", "pauta da reunião")
    assert "Reunião" in out and "pauta da reunião" in out         # distinta → concatena


def test_coalesce_merges_photo_burst_same_chat():
    from okami.channels.base import Inbound
    from okami.gateway.coalesce import coalesce_inbound
    burst = [
        Inbound(channel="telegram", chat_id="c1", image="/tmp/a.png", text="primeira", msg_id="1"),
        Inbound(channel="telegram", chat_id="c1", image="/tmp/b.png", text="segunda", msg_id="2"),
        Inbound(channel="telegram", chat_id="c1", image="/tmp/c.png", msg_id="3"),
    ]
    out = coalesce_inbound(burst)
    assert len(out) == 1                                          # 3 fotos do mesmo chat → 1 turno
    assert out[0].images == ["/tmp/a.png", "/tmp/b.png", "/tmp/c.png"]
    assert "primeira" in out[0].text and "segunda" in out[0].text  # legendas mescladas


def test_coalesce_does_not_merge_photos_across_chats():
    from okami.channels.base import Inbound
    from okami.gateway.coalesce import coalesce_inbound
    out = coalesce_inbound([
        Inbound(channel="telegram", chat_id="c1", image="/tmp/a.png", msg_id="1"),
        Inbound(channel="telegram", chat_id="c2", image="/tmp/b.png", msg_id="2"),
    ])
    assert len(out) == 2                                          # chats diferentes não mesclam
