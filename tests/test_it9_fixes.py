"""Caça it.9 (find→verify adversarial): bootstrap VPS. import_private_key valida antes de manter (e grava
0600 atômico via write_atomic); terminate_pid no Windows reporta falha do taskkill em vez de mentir."""
from __future__ import annotations

import pytest

from okami.integrations import provision as pr


# ---------------------------------------------------------------- #5 chave inválida não fica no disco
def test_import_private_key_rejects_invalid_material(tmp_path):
    with pytest.raises(ValueError, match="inválida"):
        pr.import_private_key("isto-nao-e-uma-chave\n", home=tmp_path)   # ssh-keygen -y real falha
    assert not (tmp_path / ".ssh" / "id_ed25519").exists()              # não deixa chave quebrada no disco


# ---------------------------------------------------------------- #3 chave válida ainda fica 0600
def test_import_private_key_valid_is_0600(tmp_path_factory):
    src = tmp_path_factory.mktemp("src")
    pr.generate_ssh_key(home=src)
    material = (src / ".ssh" / "id_ed25519").read_text(encoding="utf-8")
    dst = tmp_path_factory.mktemp("dst")
    pr.import_private_key(material, home=dst)
    assert oct((dst / ".ssh" / "id_ed25519").stat().st_mode)[-3:] == "600"   # write_atomic(0600), sem janela 0644


# ---------------------------------------------------------------- #13 taskkill no Windows reporta falha
def test_terminate_pid_windows_reports_taskkill_result(monkeypatch):
    import okami.core.platform_compat as pc

    class _R:
        def __init__(self, rc):
            self.returncode = rc

    monkeypatch.setattr(pc, "IS_WINDOWS", True)
    monkeypatch.setattr(pc, "IS_POSIX", False)            # força o caminho Windows (pula killpg)

    monkeypatch.setattr(pc.subprocess, "run", lambda *a, **k: _R(1))    # taskkill FALHA (PID/permissão)
    assert pc.terminate_pid(2 ** 30) is False             # não mente que matou
    monkeypatch.setattr(pc.subprocess, "run", lambda *a, **k: _R(0))    # taskkill OK
    assert pc.terminate_pid(2 ** 30) is True
