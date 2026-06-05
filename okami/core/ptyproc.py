"""Supervisor de processo INTERATIVO com PTY (#1/#8 — stdin/write/submit).

Um processo de background normal (`sh -c cmd > log`) não tem como receber input depois: o pipe morre
com o lançador, e o lançador some no fim do turno. Para processos interativos (REPL, ssh, prompts),
este supervisor — lançado DETACHED — segura o lado mestre de um PTY e faz a ponte entre turnos:

    [comando] <—slave PTY—> [supervisor]  ──escreve──> <id>.log
                                  ▲
                                  └── lê de <id>.in (FIFO) ── qualquer turno escreve aqui

`ProcessManager.write(id, "texto")` só anexa no FIFO `<id>.in`; o supervisor injeta no mestre do PTY.
Só stdlib (os/pty/select), p/ subir leve via `python -m okami.core.ptyproc`. Ao sair, grava o exit
code em `<id>.exit` e remove o FIFO. Mata o filho junto (mesma sessão) quando recebe SIGTERM.
"""

from __future__ import annotations

import os
import pty
import select
import sys


def supervise(cmd: str, logpath: str, exitpath: str, ctrlpath: str) -> int:
    pid, master_fd = pty.fork()
    if pid == 0:                                    # filho: stdio já é o slave do PTY → exec o comando
        os.execvp("sh", ["sh", "-c", cmd])
        os._exit(127)                              # só chega aqui se o exec falhar

    logf = open(logpath, "wb", buffering=0)        # noqa: SIM115 — fd de longa vida (loop do supervisor)
    # O_RDWR mantém o FIFO "vivo" (o supervisor é tb um escritor) → read não vê EOF quando ninguém escreve.
    ctrl_fd = os.open(ctrlpath, os.O_RDWR | os.O_NONBLOCK)
    code = 1
    try:
        while True:
            try:
                r, _, _ = select.select([master_fd, ctrl_fd], [], [], 0.5)
            except OSError:
                break
            if ctrl_fd in r:                       # input vindo do FIFO → injeta no PTY
                try:
                    data = os.read(ctrl_fd, 65536)
                    if data:
                        os.write(master_fd, data)
                except OSError:
                    pass
            eof = False
            if master_fd in r:                     # saída do comando → log
                try:
                    out = os.read(master_fd, 65536)
                except OSError:                    # EIO no Linux quando o slave fecha
                    out = b""
                if out:
                    logf.write(out)
                else:
                    eof = True
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                code = os.waitstatus_to_exitcode(status)
                break
            if eof:                                # PTY fechou mas pode faltar reap
                _, status = os.waitpid(pid, 0)
                code = os.waitstatus_to_exitcode(status)
                break
    finally:
        try:
            logf.close()
        except OSError:
            pass
        try:
            os.close(ctrl_fd)
        except OSError:
            pass
        with open(exitpath, "w", encoding="utf-8") as f:
            f.write(str(code))
        try:
            os.unlink(ctrlpath)                    # FIFO sumiu → write() futuro sabe que acabou
        except OSError:
            pass
    return code


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        return 2
    cmd, logpath, exitpath, ctrlpath = argv[0], argv[1], argv[2], argv[3]
    return supervise(cmd, logpath, exitpath, ctrlpath)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
