"""`okami memory prune` — remove a memória auto-aprendida de baixo valor (post-mortems ancorados na
frase do pedido), preservando fatos/preferências/decisões curados e o anti-padrão generalizado novo."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app
from okami.memory import open_store
from okami.memory.base import MemoryItem

runner = CliRunner()


def _seed(ws):
    store = open_store(ws / ".okami")
    store.write(MemoryItem(text="COMO: para 'achar a pasta' funcionou a sequência: list_dir → run_shell",
                           kind="lesson", source="reflection"))
    store.write(MemoryItem(text="ANTI-PADRÃO (haiku): 'fazer deploy' terminou BLOCKED — timeout.",
                           kind="anti_pattern", source="reflection"))
    store.write(MemoryItem(text="o usuário prefere ser chamado de Marcos", kind="preference", source="cli"))
    store.write(MemoryItem(text="ANTI-PADRÃO (haiku): tarefa falhou com 3 violações / 2 loops.",
                           kind="anti_pattern", source="reflection"))   # generalizado novo → fica
    store.close()


def test_memory_prune_removes_noise_keeps_curated(tmp_path):
    _seed(tmp_path)
    # dry-run: lista, não apaga
    res = runner.invoke(app, ["memory", "prune", "--workspace", str(tmp_path), "--dry-run"])
    assert res.exit_code == 0 and "2 item" in res.output and "nada removido" in res.output

    # real
    res = runner.invoke(app, ["memory", "prune", "--workspace", str(tmp_path), "--yes"])
    assert res.exit_code == 0 and "podados 2" in res.output

    store = open_store(tmp_path / ".okami")
    texts = [i.text for i in store.recent(50)]
    store.close()
    assert any("prefere ser chamado" in t for t in texts)        # preferência curada fica
    assert any("tarefa falhou com" in t for t in texts)          # anti-padrão generalizado novo fica
    assert not any(t.startswith("COMO: para") for t in texts)    # lesson lixo some
    assert not any("terminou" in t for t in texts)               # anti-padrão antigo (phrase-anchored) some


def test_memory_prune_nothing_when_clean(tmp_path):
    store = open_store(tmp_path / ".okami")
    store.write(MemoryItem(text="o projeto usa python 3.11", kind="fact", source="cli"))
    store.close()
    res = runner.invoke(app, ["memory", "prune", "--workspace", str(tmp_path), "--yes"])
    assert res.exit_code == 0 and "nada a podar" in res.output
