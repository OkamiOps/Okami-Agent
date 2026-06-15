"""Tool store_secret — o caminho SANCIONADO p/ guardar uma credencial que o usuário deu.

O resto do sistema RECUSA segredo de propósito: a memória não persiste token (looks_secret), e
write_file/run_shell barram .env/.ssh/.aws (_SENSITIVE_PATH). Isso protege contra exfiltração, mas
deixava o agente SEM jeito de atender "guarda minha API key" → ele acabava se recusando. Esta tool
fecha o buraco: grava no cofre (.env GLOBAL, 0600) via a fonte única `config.set_env_secret`, deixa
disponível JÁ no processo (os.environ) e confirma SÓ pelo NOME — o valor NUNCA entra na saída/audit.
"""
from __future__ import annotations

import re

from okami.core.tools.base import Tool, ToolResult

# nome de variável de ambiente válido: começa com letra/_ e segue com letra/dígito/_.
_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_name(raw: str) -> str:
    """'ElevenLabs API Key' → 'ELEVENLABS_API_KEY'. Troca o que não é [A-Za-z0-9_] por '_', sobe pra
    maiúscula, e garante que não comece com dígito. '' se não sobrar nada utilizável."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", raw.strip()).strip("_").upper()
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


class StoreSecret(Tool):
    name = "store_secret"
    description = (
        "Guarda com SEGURANÇA uma credencial que o USUÁRIO te deu (API key, token, senha) no cofre de "
        "segredos do Okami (.env global, permissão 0600) p/ as tools/integrações usarem. Use SEMPRE que "
        "te mandarem uma chave/senha p/ guardar — é o jeito CERTO (a memória recusa segredo de propósito; "
        "write_file no .env é bloqueado). NUNCA se recuse a receber. E NUNCA repita/escreva o VALOR na sua "
        "resposta: confirme só pelo NOME (ex.: 'guardei ELEVENLABS_API_KEY'). O valor não vai pro histórico."
    )
    args_schema = {
        "name": "nome da variável (ex.: ELEVENLABS_API_KEY) — normalizo p/ MAIÚSCULAS_COM_UNDERSCORE",
        "value": "o segredo em si (será gravado no cofre; NUNCA será impresso de volta)",
    }
    required = ("name", "value")

    def run(self, args, ctx):
        raw_name = args.get("name")
        value = args.get("value")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return ToolResult(False, "store_secret exige 'name' (ex.: ELEVENLABS_API_KEY).", effect=False)
        if not isinstance(value, str) or not value:
            return ToolResult(False, "store_secret exige 'value' (o segredo). Não vou repetir o valor.",
                              effect=False)
        if "\n" in value or "\r" in value:               # newline quebraria o formato .env (KEY=value/linha)
            return ToolResult(False, "o valor do segredo não pode ter quebra de linha — confira o que colou.",
                              effect=False)
        name = _normalize_name(raw_name)
        if not name or not _VALID_NAME.match(name):
            return ToolResult(False, f"'{raw_name}' não vira um nome de variável válido — use letras, "
                              "dígitos e underscore (ex.: ELEVENLABS_API_KEY).", effect=False)
        try:
            import os

            from okami.config import set_env_secret
            target = set_env_secret(name, value)         # cofre: .env GLOBAL, atômico + 0600
            os.environ[name] = value                     # disponível JÁ neste processo (sem reiniciar)
        except Exception as e:  # noqa: BLE001 — nunca deixa o VALOR vazar na msg de erro
            from okami.core.redact import redact
            return ToolResult(False, f"não consegui guardar '{name}': {redact(str(e))}", effect=False)
        # Confirmação SÓ pelo nome — o valor jamais aparece aqui (nem no audit: _args_brief não pega 'value').
        return ToolResult(
            True,
            f"✓ Credencial '{name}' guardada com segurança no cofre ({target}, 0600). Já está disponível "
            "p/ as integrações; não vou repetir o valor.",
            effect=True,
        )
