"""Tier 1 (#9): scan de segurança no código que o AGENTE escreve (write-time, modo WARN).

O Okami escaneia skills de terceiros; faltava avisar quando ELE MESMO grava um padrão perigoso
(pickle.loads, yaml.load, eval, shell=True, verify=False, torch.load sem weights_only, innerHTML…).
Anexa um aviso ao resultado do write/edit — o agente vê e se corrige (não bloqueia: regex tem FP)."""
from __future__ import annotations


def test_scan_flags_pickle(tmp_path):
    from okami.core.code_security import scan_code
    assert any("pickle" in m.lower() for m in scan_code("x.py", "import pickle\npickle.loads(data)\n"))


def test_scan_flags_yaml_load_without_safeloader():
    from okami.core.code_security import scan_code
    assert scan_code("x.py", "yaml.load(open('f'))")                      # inseguro → avisa
    assert scan_code("x.py", "yaml.load(s, Loader=yaml.SafeLoader)") == []  # seguro → não avisa


def test_scan_flags_shell_true_and_verify_false():
    from okami.core.code_security import scan_code
    assert any("shell" in m.lower() for m in scan_code("x.py", "subprocess.run(c, shell=True)"))
    assert any("tls" in m.lower() or "verify" in m.lower() for m in scan_code("x.py", "requests.get(u, verify=False)"))


def test_scan_flags_torch_load_without_weights_only():
    from okami.core.code_security import scan_code
    assert scan_code("x.py", "torch.load('m.pt')")
    assert scan_code("x.py", "torch.load('m.pt', weights_only=True)") == []


def test_scan_flags_js_innerhtml():
    from okami.core.code_security import scan_code
    assert any("innerhtml" in m.lower() or "xss" in m.lower()
               for m in scan_code("a.jsx", "el.innerHTML = userInput"))


def test_scan_clean_code_no_warning():
    from okami.core.code_security import scan_code
    assert scan_code("x.py", "def f(x):\n    return x + 1\n") == []


def test_scan_only_code_files():
    from okami.core.code_security import scan_code
    assert scan_code("notes.txt", "pickle.loads(x)") == []                # texto não é escaneado


def test_write_file_appends_security_warning(tmp_path):
    from okami.core.tools import ToolContext, WriteFile
    r = WriteFile().run({"path": "danger.py", "content": "import pickle\npickle.loads(open('x','rb').read())\n"},
                        ToolContext(workspace=tmp_path))
    assert r.ok and ("⚠" in r.output or "segurança" in r.output.lower())   # avisou (mas escreveu)
