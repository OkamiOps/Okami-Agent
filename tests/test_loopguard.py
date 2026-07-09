"""Detector de NÃO-PROGRESSO por OUTPUT (paridade OpenClaw tool-loop-detection): repetir uma tool e
receber o MESMO resultado é I/O desperdiçado — o anti-loop por args iguais dá budget generoso e não
olha o output. Aqui: tool read-only/poll que devolve a MESMA saída N vezes seguidas é cortada cedo."""

from __future__ import annotations

from okami.core.harness.loopguard import IdempotentCache, ProgressTracker, output_signature
from okami.core.tools import ToolResult


# ----------------------------------------------------------------- assinatura (pura)
def test_signature_ignores_whitespace_noise():
    assert output_signature("a   b\n\n") == output_signature("a b")


def test_signature_distinguishes_content():
    assert output_signature("estado: rodando") != output_signature("estado: concluído")


def test_signature_caps_huge_output():
    # saída gigante não estoura memória nem custa hash do arquivo inteiro
    a = output_signature("x" * 1_000_000)
    b = output_signature("x" * 1_000_000 + "diferente no fim")
    assert a == b                                          # cap no início → fim ignorado (ok p/ poll)


# ----------------------------------------------------------------- ProgressTracker
def test_first_call_is_progress():
    t = ProgressTracker()
    assert t.stalled_count("process_poll", "estado: rodando") == 0


def test_same_output_increments_stall():
    t = ProgressTracker()
    t.stalled_count("process_poll", "rodando")             # 1ª vez → 0
    assert t.stalled_count("process_poll", "rodando") == 1
    assert t.stalled_count("process_poll", "rodando") == 2


def test_changed_output_resets_stall():
    t = ProgressTracker()
    t.stalled_count("process_poll", "rodando")
    t.stalled_count("process_poll", "rodando")
    assert t.stalled_count("process_poll", "concluído") == 0   # output mudou → progresso, zera


def test_per_tool_independent():
    t = ProgressTracker()
    t.stalled_count("read_file", "conteúdo")
    assert t.stalled_count("process_poll", "conteúdo") == 0    # tool diferente não conta junto


# ----------------------------------------------------------------- IdempotentCache
def test_idempotent_cache_miss_then_hit():
    cache = IdempotentCache()
    assert cache.get("read_file", {"path": "a.txt"}) is None
    res = ToolResult(True, "conteúdo de a.txt", False)
    cache.put("read_file", {"path": "a.txt"}, res)
    hit = cache.get("read_file", {"path": "a.txt"})
    assert hit is res


def test_idempotent_cache_args_order_independent():
    cache = IdempotentCache()
    res = ToolResult(True, "resultado", False)
    cache.put("search_files", {"query": "foo", "target": "content"}, res)
    hit = cache.get("search_files", {"target": "content", "query": "foo"})
    assert hit is res


def test_idempotent_cache_different_args_miss():
    cache = IdempotentCache()
    res = ToolResult(True, "conteúdo de a.txt", False)
    cache.put("read_file", {"path": "a.txt"}, res)
    assert cache.get("read_file", {"path": "b.txt"}) is None


def test_idempotent_cache_never_caches_mutating_tool():
    cache = IdempotentCache()
    res = ToolResult(True, "escrito!", True)
    cache.put("write_file", {"path": "a.txt", "content": "x"}, res)
    assert cache.get("write_file", {"path": "a.txt", "content": "x"}) is None


def test_idempotent_cache_never_caches_error_result():
    cache = IdempotentCache()
    err = ToolResult(False, "erro: arquivo não existe", False)
    cache.put("read_file", {"path": "missing.txt"}, err)
    assert cache.get("read_file", {"path": "missing.txt"}) is None


def test_idempotent_cache_served_adds_note_without_mutating_original():
    cache = IdempotentCache()
    res = ToolResult(True, "conteúdo original", False)
    cache.put("list_dir", {"path": "."}, res)
    served = cache.served("list_dir", {"path": "."})
    assert served is not res
    assert served.output.startswith("conteúdo original")
    assert "cache" in served.output.lower()
    assert res.output == "conteúdo original"          # original intacto p/ próximo hit


def test_idempotent_cache_bounded_lru_evicts_oldest():
    cache = IdempotentCache(maxsize=2)
    cache.put("read_file", {"path": "a.txt"}, ToolResult(True, "a", False))
    cache.put("read_file", {"path": "b.txt"}, ToolResult(True, "b", False))
    cache.put("read_file", {"path": "c.txt"}, ToolResult(True, "c", False))  # estoura → evict "a"
    assert cache.get("read_file", {"path": "a.txt"}) is None
    assert cache.get("read_file", {"path": "b.txt"}) is not None
    assert cache.get("read_file", {"path": "c.txt"}) is not None


def test_idempotent_cache_is_cacheable_tool_allowlist():
    assert IdempotentCache.is_cacheable_tool("read_file") is True
    assert IdempotentCache.is_cacheable_tool("list_dir") is True
    assert IdempotentCache.is_cacheable_tool("find_files") is True
    assert IdempotentCache.is_cacheable_tool("search_files") is True
    for mutating in ("write_file", "edit_file", "move_path", "delete_path", "run_shell", "process_start"):
        assert IdempotentCache.is_cacheable_tool(mutating) is False


# ----------------------------------------------------------------- integração no harness
def test_harness_breaks_on_unchanging_output_even_with_varying_args():
    """O caso que o anti-loop por ARGS NÃO pega: a tool é chamada com args DIFERENTES a cada vez (logo
    fingerprint diferente, sem disparar o loop velho), mas devolve SEMPRE a mesma saída. O detector por
    OUTPUT avisa que não há progresso."""
    from okami.core import Task
    from okami.core.harness.loop import Harness
    from okami.core.tools.base import Tool, ToolResult

    class Poll(Tool):
        name = "process_poll"
        description = "espia um processo"
        args_schema = {"id": "id", "n": "contador"}

        def run(self, args, ctx):
            return ToolResult(True, "ainda rodando…")      # SEMPRE o mesmo output (args variam)

    nudges: list[str] = []
    calls = {"n": 0}

    def generate(messages, schema):
        for m in messages:
            if m["role"] == "user" and "mesma sa" in m["content"].lower():
                nudges.append(m["content"])
        calls["n"] += 1
        if calls["n"] > 12 or nudges:                       # parou ao ver o nudge (ou rede de segurança)
            return '{"tool":"respond","args":{"message":"ok, paro"}}'
        return '{"tool":"process_poll","args":{"id":"1","n":%d}}' % calls["n"]   # args VARIAM

    import tempfile
    reg = {"process_poll": Poll()}
    from okami.core.tools.registry import default_registry
    reg.update({k: v for k, v in default_registry().items() if k in ("respond", "task_complete")})
    h = Harness(generate, Task(goal="acompanhe o processo"), tempfile.mkdtemp(), registry=reg)
    h.run()
    assert nudges, "o harness deveria avisar que o output não muda (não-progresso por OUTPUT)"
