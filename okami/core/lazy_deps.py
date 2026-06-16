"""Instalador de dependência opcional em runtime (#12, port do Hermes tools/lazy_deps.py).

Backend opcional (TTS edge/piper, search ddgs, provider boto3/gemini…) chama `ensure('feature')` no topo
do seu 1º import. Se a dep falta, `ensure` checa `security.allow_lazy_installs` (default True) e instala
no venv. Resolve (1) fragilidade do extra `[all]` (uma dep podre quebrava o resolve inteiro) e (2) bloat
(quem usa 1 provider não paga import de todos).

Modelo de segurança:
- **venv-scoped**: instala em `sys.executable` (nunca o Python do sistema).
- **PyPI por NOME só**: spec tipo `pkg>=1.0,<2`. SEM `--index-url`, `git+`, `file:`, path — nada que um
  config malicioso possa sequestrar.
- **allowlist**: só spec que está em `LAZY_DEPS` instala. Typo no nome de feature NÃO vira install-qualquer.
- **opt-out**: `security.allow_lazy_installs: false` (ou env `OKAMI_DISABLE_LAZY_INSTALLS=1`) desliga.
- **offline**: falha de install → FeatureUnavailable com o stderr do pip (sem retry silencioso).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Allowlist: feature ("namespace.backend") → specs pip. SÓ specs daqui fluem pro comando de install.
LAZY_DEPS: dict[str, tuple[str, ...]] = {
    # voz / TTS
    "tts.edge": ("edge-tts>=7.0.0",),
    "tts.piper": ("piper-tts>=1.2.0",),
    # busca web
    "search.ddgs": ("ddgs>=9.0.0",),
    # provider multi-vendor (#12: prontidão p/ trocar de vendor)
    "provider.bedrock": ("boto3>=1.40.0",),
    "provider.gemini": ("google-genai>=1.0.0",),
    # documentos office (read_extract)
    "read.office": ("python-docx>=1.1.0", "openpyxl>=3.1.0"),
    # imagem (vision/resize)
    "image.pillow": ("Pillow>=10.0.0",),
    # janela nativa do dashboard (desktop) — webview do SO, sem Electron
    "desktop.webview": ("pywebview>=5.0",),
    # language server p/ diagnostics semânticos no write (pyright tem wrapper no PyPI)
    "lsp.pyright": ("pyright>=1.1.400",),
}

_SAFE_SPEC = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*"            # nome do pacote
    r"(?:\[[A-Za-z0-9_,\-]+\])?"                # [extras] opcional
    r"(?:[<>=!~]=?[A-Za-z0-9_.\-+,*<>=!~]+)?$"  # specifier de versão opcional
)


class FeatureUnavailable(RuntimeError):
    """Feature lazy-installável está ausente e não dá p/ disponibilizar (install off ou falhou)."""

    def __init__(self, feature: str, missing: tuple[str, ...], reason: str):
        self.feature = feature
        self.missing = missing
        self.reason = reason
        specs = " ".join(repr(s) for s in missing)
        super().__init__(f"Feature {feature!r} indisponível: {reason}. "
                         f"P/ habilitar manual: uv pip install {specs} (ou pip install {specs}).")


@dataclass(frozen=True)
class _InstallResult:
    success: bool
    stdout: str
    stderr: str


def _allow_lazy_installs() -> bool:
    """Flag `security.allow_lazy_installs` (default True). Fail-OPEN se config ilegível (recusar trancaria
    o dono fora dos próprios backends; bloquear é opt-in explícito)."""
    if os.environ.get("OKAMI_DISABLE_LAZY_INSTALLS") == "1":
        return False
    try:
        from okami.config import load_config
        cfg = load_config()
        sec = (getattr(cfg, "security", None) or {}) if not isinstance(cfg, dict) else (cfg.get("security") or {})
        return bool(sec.get("allow_lazy_installs", True))
    except Exception:  # noqa: BLE001
        return True


def _spec_is_safe(spec: str) -> bool:
    """Recusa spec com URL, path ou metachar de shell."""
    if not spec or len(spec) > 200:
        return False
    if any(ch in spec for ch in (";", "|", "&", "`", "$", "\n", "\r", "\t", "\\", " ")):
        return False
    if spec.startswith(("-", "/", ".")) or "://" in spec or "@" in spec:
        return False
    return bool(_SAFE_SPEC.match(spec))


def _pkg_name_from_spec(spec: str) -> str:
    m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*)", spec)
    return m.group(1) if m else spec


def _is_satisfied(spec: str) -> bool:
    """Pacote do spec já importável/instalado no env? (presença; versão best-effort via importlib.metadata)."""
    name = _pkg_name_from_spec(spec)
    try:
        from importlib import metadata
        metadata.version(name)
        return True
    except Exception:  # noqa: BLE001
        # fallback: tenta achar o módulo (nome do pacote ≈ nome do módulo na maioria)
        import importlib.util
        return importlib.util.find_spec(name.replace("-", "_")) is not None


def feature_specs(feature: str) -> tuple[str, ...]:
    if feature not in LAZY_DEPS:
        raise KeyError(f"feature lazy desconhecida: {feature!r}")
    return LAZY_DEPS[feature]


def feature_missing(feature: str) -> tuple[str, ...]:
    return tuple(s for s in feature_specs(feature) if not _is_satisfied(s))


def _venv_pip_install(specs: tuple[str, ...], *, timeout: int = 300) -> _InstallResult:
    """Instala `specs` no venv ativo (uv → pip). venv-scoped: alvo é sys.executable."""
    import shutil
    uv = shutil.which("uv")
    if uv:
        argv = [uv, "pip", "install", "--python", sys.executable, *specs]
    else:
        argv = [sys.executable, "-m", "pip", "install", *specs]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        return _InstallResult(r.returncode == 0, r.stdout or "", r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return _InstallResult(False, "", str(e))


def ensure(feature: str, *, prompt: bool = True) -> None:
    """Garante que os pacotes de `feature` estão importáveis; instala no venv se faltam. Levanta
    FeatureUnavailable se install desligado, spec inseguro, ou install falhou. `prompt` ignorado fora de TTY."""
    if feature not in LAZY_DEPS:
        raise FeatureUnavailable(feature, (), f"feature {feature!r} fora da allowlist LAZY_DEPS")
    missing = feature_missing(feature)
    if not missing:
        return
    for spec in missing:                                  # belt-and-braces: a allowlist já constrange
        if not _spec_is_safe(spec):
            raise FeatureUnavailable(feature, missing, f"recusando spec inseguro {spec!r}")
    if not _allow_lazy_installs():
        raise FeatureUnavailable(feature, missing, "lazy installs disabled (security.allow_lazy_installs=false)")
    logger.info("lazy install de %s: %s", feature, " ".join(missing))
    res = _venv_pip_install(missing)
    if not res.success:
        raise FeatureUnavailable(feature, missing, f"pip falhou: {(res.stderr or res.stdout)[:300]}")
    still = feature_missing(feature)
    if still:
        raise FeatureUnavailable(feature, still, "pacotes seguem ausentes após o install")


__all__ = ["LAZY_DEPS", "FeatureUnavailable", "ensure", "feature_missing", "feature_specs"]
