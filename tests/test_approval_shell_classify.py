"""Classificação de shell destrutivo (go/no-go): NÃO pode pedir aprovação por palavra perigosa que
aparece como PADRÃO de grep / argumento entre aspas (falso-positivo de auditoria). Hermes _CMDPOS +
strip de aspas. E TEM que continuar pegando comando destrutivo de verdade."""
from okami.core import approval as A


def _cat(cmd):
    s = A.classify("run_shell", {"cmd": cmd})
    return s.category if s else None


def test_grep_for_dangerous_patterns_is_not_destructive():
    # O CASO REAL do print: auditando o repo por padrões perigosos — grep read-only NÃO é destrutivo.
    for cmd in (
        "cd /x && grep -A 3 -B 1 'kill -1\\|mkfs' app.ts",
        "grep 'mkfs\\|fork.?bomb' app.ts",
        "grep -nE 'mkfs|kill.*-1|fork.?bomb|/dev/sd' f.ts",
        "grep -c 'mkfs' app.ts",
        "grep -l 'mkfs\\|fork' src/",
        'grep "rm -rf /" file',
        "echo 'rm -rf /' >> notes.txt",          # echo de texto perigoso ≠ executar
        "find . -name '*.ts' -not -path './node_modules/*'",
    ):
        assert _cat(cmd) is None, f"falso-positivo: {cmd!r} → {_cat(cmd)}"


def test_real_destructive_commands_still_flagged():
    for cmd, cat in (
        ("rm -rf x", "destructive_shell"),
        ("rm -rf /", "destructive_shell"),
        ("rm -rf /home", "destructive_shell"),
        ("mkfs.ext4 /dev/sda", "destructive_shell"),
        ("dd if=/dev/zero of=/dev/sda", "destructive_shell"),
        ("shutdown -h now", "destructive_shell"),
        ("kill -1 -1", "destructive_shell"),
        (":(){ :|:& };:", "destructive_shell"),          # fork bomb
        ("find . | xargs rm -rf", "destructive_shell"),  # xargs como wrapper
        ("bash -c 'rm -rf /'", "destructive_shell"),     # sh -c '…' → aspas escondem COMANDO
        ("sudo reboot", "destructive_shell"),
        ("sudo apt update", "sudo"),
        ("git push origin main", "git_push"),
        ("npm publish", "publish"),
        ("chmod 777 x", "system_change"),
    ):
        assert _cat(cmd) == cat, f"{cmd!r} → {_cat(cmd)} (esperado {cat})"


def test_readonly_audit_does_not_need_approval():
    for cmd in ("ls -la", "cat file.txt", "grep -rn 'sudo' .", "git log --oneline", "wc -l *.py"):
        assert _cat(cmd) is None
