"""Wrapper <persisted-output> (paridade Hermes tool_result_storage): saída de tool grande demais p/ o
contexto vira uma tag estruturada com preview + caminho + como recuperar o resto (read_file offset/
limit), em vez de um '[… truncado …]' solto que o modelo não sabe paginar."""

from __future__ import annotations


def persisted_output_wrapper(path: str, total_chars: int, preview: str) -> str:
    mb = total_chars / (1024 * 1024)
    size = f"{total_chars} chars" + (f" / {mb:.1f} MB" if mb >= 0.1 else "")
    return (
        "<persisted-output>\n"
        f"Saída grande demais p/ o contexto ({size}). Completa salva em: {path}\n"
        f"Para ver o resto, use read_file com offset/limit, ex.: "
        f'read_file(path="{path}", offset=200, limit=200).\n\n'
        "Preview (início):\n"
        f"{preview}\n"
        "</persisted-output>"
    )
