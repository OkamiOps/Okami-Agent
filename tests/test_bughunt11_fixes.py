"""Caça a bugs #11 (workflow adversarial, 13 confirmados c/ repro). Um teste por bug — RED antes do fix.

Cada teste reproduz o defeito EXATO que o verificador adversarial confirmou. Não são features; são
correções de comportamento errado em código real (vários em código novo desta sessão: speak, remote,
sessions).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# ─────────────────────────────────────────────────────────── 1. format_tokens '1.0B' → '1B' (usage.py)
def test_format_tokens_strips_zero_from_billion():
    from okami.llm.usage import format_tokens
    assert format_tokens(1_000_000_000) == "1B"        # era '1.0B'
    assert format_tokens(2_000_000_000) == "2B"
    assert format_tokens(1_200_000_000) == "1.2B"      # decimal real preservado
    assert format_tokens(1_000) == "1K" and format_tokens(1_000_000) == "1M"  # regressão K/M


# ─────────────────────────────────────────────────── 2. RemoteTarget timeout=0 honrado (remote.py)
def test_remote_timeout_zero_is_honored():
    from okami.integrations.remote import RemoteTarget
    seen = {}

    def rec(argv, **kw):
        seen.update(kw)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    rt = RemoteTarget(alias="t", host="h", via="ssh", runner=rec, timeout=120)
    rt.run("echo hi", timeout=0)
    assert seen["timeout"] == 0          # era 120 (0 caía no 'or self.timeout')


# ─────────────────────────────────────── 3+4. text_to_speech: path ABSOLUTO + nome ÚNICO (speak.py)
@pytest.fixture
def _fake_tts(monkeypatch):
    import okami.voice
    import okami.core.tools.speak as speak

    class FakeTTS:
        def synthesize(self, text, out):
            Path(out).write_bytes(b"fake-audio")

    monkeypatch.setattr(okami.voice, "make_tts", lambda cfg: FakeTTS())
    monkeypatch.setattr(speak, "_to_voice_ogg", lambda p: None)   # sem ffmpeg → fica no mp3
    return speak


def test_tts_media_path_is_absolute_with_relative_workspace(monkeypatch, tmp_path, _fake_tts):
    from okami.channels.media import extract_media
    from okami.core.tools import ToolContext
    monkeypatch.chdir(tmp_path)
    (tmp_path / "work").mkdir()
    ctx = ToolContext(workspace=Path("work"), cfg=SimpleNamespace(voice={"tts": {"enabled": True}}))
    r = _fake_tts.TextToSpeech().run({"text": "olá"}, ctx)
    assert r.ok
    _clean, media = extract_media(r.output)
    assert len(media) == 1               # path relativo → regex de MEDIA não casava → 0 itens (bug)


def test_tts_filenames_unique_even_within_same_millisecond(monkeypatch, tmp_path, _fake_tts):
    from okami.core.tools import ToolContext
    monkeypatch.setattr("time.time", lambda: 1_700_000_000.0)     # congela o ms → força colisão no código bugado
    ctx = ToolContext(workspace=tmp_path, cfg=SimpleNamespace(voice={"tts": {"enabled": True}}))
    out1 = _fake_tts.TextToSpeech().run({"text": "a"}, ctx).output
    out2 = _fake_tts.TextToSpeech().run({"text": "b"}, ctx).output
    p1 = out1.split("MEDIA:", 1)[1].splitlines()[0]
    p2 = out2.split("MEDIA:", 1)[1].splitlines()[0]
    assert p1 != p2                      # mesmo ms → nomes idênticos no bug (2º sobrescreve o 1º)


# ─────────────────────────────────────────── 5. PII: id longo colado a '_' é mascarado (pii.py)
def test_pii_masks_long_id_adjacent_to_underscore():
    from okami.gateway.pii import redact_pii
    out = redact_pii("user_123456789 e chat_987654321_", "telegram")
    assert "123456789" not in out and "987654321" not in out   # \b não casava com '_' em volta (bug)


def test_pii_keeps_digits_embedded_in_alnum_token():
    from okami.gateway.pii import redact_pii
    # dígitos DENTRO de um token alfanumérico (hash/hex) NÃO devem ser mascarados (sem regressão de over-mask)
    assert "abc123456789def" in redact_pii("ref abc123456789def", "telegram")
    assert "9999999" not in redact_pii("id 9999999 aqui", "telegram")   # standalone continua mascarando


# ─────────────────────── 6. _SENSITIVE_PATH: libera .env.example/.env.js, barra .env real (base.py)
def test_sensitive_path_allows_templates_and_code_blocks_real_env():
    from okami.core.tools.base import _SENSITIVE_PATH
    s = _SENSITIVE_PATH.search
    # NÃO são segredo → devem ser LIBERADOS (não casam)
    for ok in ("cat .env.example", "read .env.sample", ".env.template", "src/.env.js", "test.env.ts", ".env.dist"):
        assert not s(ok), f"falso-positivo: {ok!r} foi barrado"
    # SÃO segredo → devem CONTINUAR barrados
    for bad in ("cat .env", "/proj/.env", ".env.local", ".env.production", ".env.development", "id_rsa"):
        assert s(bad), f"falso-negativo: {bad!r} deixou de ser barrado"


# ─────────────────── 7+8. TranscriptStore: tmp único por save + prune sob _FileLock (sessions.py)
def test_save_store_uses_unique_temp_per_call(tmp_path, monkeypatch):
    from okami.gateway import sessions as S
    store = S.TranscriptStore(tmp_path)
    seen, real = [], S.os.replace

    def rec(src, dst):
        seen.append(str(src))
        real(src, dst)

    monkeypatch.setattr(S.os, "replace", rec)
    store._save_store({"a": {"updated_at": 1}})
    store._save_store({"b": {"updated_at": 2}})
    assert len(set(seen)) == 2           # tmp fixo 'sessions.json.tmp' colidia entre processos → race no os.replace


def test_prune_serializes_under_filelock(tmp_path, monkeypatch):
    from okami.gateway import sessions as S
    entered = []

    class RecLock:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            entered.append(1)
            return self

        def __exit__(self, *a):
            return False

    store = S.TranscriptStore(tmp_path)
    store.update_entry("c1", x=1)        # cria o store
    monkeypatch.setattr(S, "_FileLock", RecLock)
    entered.clear()
    store.prune(max_sessions=0)          # remove tudo → grava; deve estar sob lock
    assert entered                       # prune não pegava o _FileLock (lost-update vs update_entry concorrente)


# ─────────────────────────────────── 9+10. policy: conjugações faltando (policy.py)
def test_temp_classification_catches_past_tense_esqueci():
    from okami.memory.policy import TEMP, classify
    assert classify("esqueci depois") == TEMP        # 'esquec[ae]?' não pegava 'esqueci'


def test_negative_tool_catches_ser_quebrada():
    from okami.memory.policy import do_not_capture
    assert do_not_capture("a ferramenta é quebrada") is True   # só pegava 'está quebrada' (ESTAR), não 'é' (SER)
    assert do_not_capture("a ferramenta está quebrada") is True  # regressão ESTAR


# ─────────────────────────── 11. session_recap tolera itens dict no history (session_recap.py)
def test_recap_helpers_tolerate_dict_items():
    from okami.core.session_recap import _count_turns, _last
    hist = [{"role": "USER", "text": "x"}, ("USER", "oi"), ("AGENT", "olá")]  # dict torto + tuplas válidas
    assert _count_turns(hist) == 1              # KeyError no item[0] do dict derrubava a contagem
    assert _last(hist, "AGENT") == "olá"


# ─────────────────────── 12. set_env_secret faz UPSERT com espaçamento variável (config.py)
def test_set_env_secret_upsert_with_variable_spacing(tmp_path):
    from okami.config import set_env_secret
    env = tmp_path / ".env"
    env.write_text("KEY_A   =   old\nKEY_B=keep\n", encoding="utf-8")
    set_env_secret("KEY_A", "new", path=str(env))
    body = env.read_text(encoding="utf-8")
    assert body.count("KEY_A") == 1 and "KEY_A=new" in body   # antes: criava duplicata (não casava o espaçamento)
    assert "KEY_B=keep" in body


# ─────────────────────── 13. parse_skill não crasha com frontmatter YAML malformado (skills/__init__.py)
def test_parse_skill_tolerates_malformed_yaml(tmp_path):
    from okami.skills import parse_skill
    p = tmp_path / "SKILL.md"
    p.write_text("---\nname: [unclosed\ntriggers: , ,\n---\n## corpo\nconteúdo útil\n", encoding="utf-8")
    sk = parse_skill(p)                  # antes: yaml.ParserError derrubava load_skills inteiro
    assert sk.name == tmp_path.name      # fallback p/ nome do diretório
    assert "conteúdo útil" in sk.body
