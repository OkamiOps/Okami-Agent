"""#11 Onda 5: borderline/cosmético/fora-de-escopo — implementados por completude."""
from __future__ import annotations


# ── audio-input em ModelInfo ──
def test_model_info_audio_input_flag():
    from okami.llm.model_catalog import ModelInfo, model_info
    mi = ModelInfo(200_000, vision=True, audio=True)
    assert mi.supports_audio_input() is True
    assert ModelInfo(200_000).supports_audio_input() is False
    info = model_info("gpt-5.4")               # lookup não quebra com o campo novo
    assert info is None or hasattr(info, "supports_audio_input")


# ── TTS streaming ABC + voice_compatible ──
def test_tts_stream_optional_and_voice_compatible():
    from okami.voice.tts import EdgeTTS
    t = EdgeTTS()
    assert hasattr(t, "voice_compatible") and t.voice_compatible is True   # opus → bolha de voz
    assert hasattr(t, "stream")                # método de streaming existe (opcional)


# ── tabela markdown wcwidth-aware (CJK/emoji) ──
def test_display_width_counts_cjk_as_two():
    from okami.core.markdown_tables import display_width
    assert display_width("ab") == 2
    assert display_width("中文") == 4          # cada CJK ocupa 2 colunas
    assert display_width("a中") == 3


def test_realign_markdown_table_keeps_pipes():
    from okami.core.markdown_tables import realign_markdown_tables
    src = "| nome | v |\n| --- | --- |\n| 中文 | 1 |\n| ab | 2 |"
    out = realign_markdown_tables(src)
    lines = [line for line in out.splitlines() if line.strip().startswith("|")]
    # todas as linhas da tabela têm a MESMA largura de exibição (alinhadas por coluna)
    from okami.core.markdown_tables import display_width
    widths = {display_width(line) for line in lines}
    assert len(widths) == 1 and out.count("|") == src.count("|")


# ── is_genuine_rate_limit (transient 5xx ≠ quota) ──
def test_is_genuine_rate_limit_classifies():
    from okami.llm.rate_guard import is_genuine_rate_limit
    assert is_genuine_rate_limit(429) is True                  # quota real
    assert is_genuine_rate_limit(503) is False                 # transiente (overloaded)
    assert is_genuine_rate_limit(529) is False
    assert is_genuine_rate_limit(200) is False


# ── TurnRetryState (guards explícitos de recuperação) ──
def test_turn_retry_state_one_shot_guards():
    from okami.llm.turn_retry_state import TurnRetryState
    st = TurnRetryState()
    assert st.try_once("oauth_refresh") is True                # 1ª vez → pode
    assert st.try_once("oauth_refresh") is False               # 2ª vez → já tentou
    assert st.try_once("image_shrink") is True                 # outro guard, independente


# ── cred borrowed-vs-owned sanitization ──
def test_borrowed_credential_payload_is_sanitized():
    from okami.llm.cred_pool import is_owned_source, sanitize_borrowed_credential_payload
    owned = {"access_token": "AT", "fingerprint": "fp", "status": "ok"}
    # source OWNED (oauth do dono) → mantém o valor
    assert sanitize_borrowed_credential_payload(owned, "oauth_pkce")["access_token"] == "AT"
    # source BORROWED (terceiro) → tira o valor cru, mantém metadata
    san = sanitize_borrowed_credential_payload(owned, "vendor_x")
    assert "access_token" not in san and san["fingerprint"] == "fp" and san["status"] == "ok"
    assert is_owned_source("oauth_pkce") is True and is_owned_source("vendor_x") is False


# ── active-session concurrency limit ──
def test_session_limit_check():
    from okami.gateway.session_limit import within_session_limit
    assert within_session_limit(current=2, limit=5) is True
    assert within_session_limit(current=5, limit=5) is False        # cheio → recusa nova
    assert within_session_limit(current=99, limit=0) is True        # limit=0 = ilimitado


# ── tool_guardrails config-driven (→ Budget) ──
def test_guardrail_budget_overrides():
    from types import SimpleNamespace
    from okami.core.harness.loopguard_config import guardrail_budget_overrides
    cfg = SimpleNamespace(tools={"loop_guardrails": {"max_repeat": 5, "stall_limit": 8}})
    ov = guardrail_budget_overrides(cfg)
    assert ov == {"max_repeat": 5, "stall_limit": 8}
    assert guardrail_budget_overrides(SimpleNamespace(tools={})) == {}    # sem config → vazio


# ── TurnFinalizer helper (sumário do turno) ──
def test_turn_summary_dict():
    from okami.core import Task, TaskState
    from okami.core.harness.turn_finalizer import summarize_result
    t = Task(goal="x")
    t.state, t.result = TaskState.COMPLETE, "feito"
    s = summarize_result(t, api_calls=3)
    assert s["completed"] is True and s["api_calls"] == 3 and s["state"] == "complete"
