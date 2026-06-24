"""Ecossistema de plugins (#12, port do Hermes hermes_cli/plugins.py).

Descobre plugins de 3 fontes (combináveis): pasta bundled/user/project (`<root>/plugins/<nome>/
plugin.yaml`) e entry-point pip (grupo `okami.plugins`). Cada plugin declara `hooks` (pre_llm_call,
post_tool_call, before_skill_install…) que o HookManager já roda. Estende `automation/hooks.py` com a
camada de DESCOBERTA — antes só config + pasta `hooks/`; agora também plugin instalável.

Fail-safe: plugin.yaml quebrado/ilegível é IGNORADO (não derruba o boot).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from okami.log import warn


@dataclass
class Plugin:
    name: str
    source: str                    # "folder" | "entry_point"
    hooks: list[str] = field(default_factory=list)
    path: str = ""
    value: str = ""                # p/ entry_point: "modulo:objeto"


def _from_folder(root) -> list[Plugin]:
    out: list[Plugin] = []
    base = Path(root) / "plugins"
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        manifest = d / "plugin.yaml"
        if not manifest.is_file():
            continue
        try:
            meta = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            if not isinstance(meta, dict):
                continue
        except (yaml.YAMLError, OSError):
            continue                # plugin quebrado → ignora
        name = str(meta.get("name") or d.name)
        hooks = [str(h) for h in (meta.get("hooks") or [])]
        out.append(Plugin(name=name, source="folder", hooks=hooks, path=str(d)))
    return out


def discover_plugins(roots, *, entry_points=None) -> list[Plugin]:
    """Plugins descobertos nas `roots` (pasta `<root>/plugins/`) + entry-points pip (grupo okami.plugins).
    `entry_points`: iterável com .name/.value (default: lê do ambiente). Dedup por nome (pasta vence)."""
    found: dict[str, Plugin] = {}
    for root in (roots or []):
        for p in _from_folder(root):
            found.setdefault(p.name, p)
    eps = entry_points
    if eps is None:
        try:
            from importlib import metadata
            eps = metadata.entry_points(group="okami.plugins")
        except Exception:  # noqa: BLE001 — degrada mas AVISA (plugin pip quebrado não some calado)
            warn("falha ao ler entry-points de plugins (okami.plugins)", exc_info=True)
            eps = ()
    for ep in (eps or ()):
        name = getattr(ep, "name", "")
        if name and name not in found:
            found[name] = Plugin(name=name, source="entry_point", value=getattr(ep, "value", ""))
    return list(found.values())


@dataclass(frozen=True)
class PluginContext:
    """Capacidade que um plugin recebe p/ pedir uma chamada ao modelo, GATED por confiança (port do Hermes
    plugin_llm). Regra: trocar de provider só é permitido se o plugin é `trusted` E `allow_provider_override`
    E o provider está em `allowed_providers`. Plugin `untrusted` fica preso ao `default_provider` — um
    plugin de pasta/terceiro NÃO pode redirecionar o tráfego (e o gasto) p/ um vendor à revelia do dono."""
    plugin: str
    trust: str = "untrusted"                 # untrusted | trusted
    default_provider: str = ""
    allowed_providers: tuple = ()
    allow_provider_override: bool = False

    def can_override(self) -> bool:
        return self.trust == "trusted" and self.allow_provider_override

    def resolve_provider(self, requested: str | None = None) -> str:
        """Provider efetivo p/ a chamada do plugin. Pedir o default (ou nada) sempre passa; pedir OUTRO
        exige override permitido + estar na allowlist, senão PermissionError."""
        if not requested or requested == self.default_provider:
            return self.default_provider
        if not self.can_override():
            raise PermissionError(
                f"plugin {self.plugin!r} ({self.trust}) não pode trocar de provider "
                f"(allow_provider_override desligado p/ não-confiáveis)")
        if self.allowed_providers and requested not in self.allowed_providers:
            raise PermissionError(
                f"plugin {self.plugin!r} pediu provider {requested!r} fora da allowlist {self.allowed_providers}")
        return requested


def _cfg_get(cfg, key, default=None):
    """Lê `key` de um cfg que pode ser dict OU OkamiConfig (objeto). Sem isto, passar o OkamiConfig real dava
    AttributeError (.get) e a config de plugins era DROPADA silenciosamente (config-drop trap)."""
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def plugin_context(plugin: str, *, trust: str = "untrusted", cfg=None) -> PluginContext:
    """Monta o PluginContext a partir do config (`default_provider` + `plugins.allowed_providers/
    allow_provider_override`). Aceita dict OU OkamiConfig. Trust vem da fonte do plugin (pasta=untrusted;
    entry-point assinado=trusted)."""
    pl = _cfg_get(cfg or {}, "plugins") or {}
    return PluginContext(
        plugin=plugin,
        trust=trust,
        default_provider=str(_cfg_get(cfg or {}, "default_provider") or ""),
        allowed_providers=tuple(pl.get("allowed_providers") or ()),
        allow_provider_override=bool(pl.get("allow_provider_override", False)),
    )


class PluginRegistrar:
    """Contexto que um plugin recebe em `register(ctx)` p/ CONTRIBUIR capacidades (port do ctx.register_* do
    Hermes). Hoje: register_tool. O PluginContext (trust-gating de provider) viaja junto p/ futuras chamadas
    LLM gated. Antes disso o register/PluginContext era código MORTO — ninguém chamava em runtime."""

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx
        self.tools: dict = {}

    def register_tool(self, tool) -> None:
        name = getattr(tool, "name", None)
        if not name:
            raise ValueError("register_tool: tool precisa de um atributo .name não-vazio")
        self.tools[str(name)] = tool


def _resolve_register(plugin: "Plugin"):
    """Acha o callable `register(ctx)` do plugin. entry_point: importa 'modulo:objeto' e usa .register (ou o
    próprio objeto se for callable). folder: importa `<path>/register.py` e usa `register`. None se não houver
    — plugin que só tem hooks de shell (sem register) segue funcionando como antes."""
    try:
        if plugin.source == "entry_point" and plugin.value:
            import importlib
            mod_name, _, attr = plugin.value.partition(":")
            obj = importlib.import_module(mod_name)
            for part in (attr.split(".") if attr else []):
                obj = getattr(obj, part)
            reg = getattr(obj, "register", obj)
            return reg if callable(reg) else None
        if plugin.source == "folder" and plugin.path:
            reg_file = Path(plugin.path) / "register.py"
            if not reg_file.is_file():
                return None
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"okami_plugin_{plugin.name}", reg_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            reg = getattr(mod, "register", None)
            return reg if callable(reg) else None
    except Exception:  # noqa: BLE001 — plugin que não importa não derruba o boot; AVISA e segue
        warn(f"plugin {plugin.name!r}: falha ao carregar register()", exc_info=True)
    return None


def load_plugin_tools(plugins, *, cfg=None, emit=lambda m: None, _resolve=None) -> dict:
    """Roda `register(ctx)` de cada plugin e COLETA as tools registradas (foundation do sistema de plugins,
    paridade Hermes). Isolado por plugin: um `register` que explode NÃO derruba os outros. Trust:
    folder=untrusted, entry_point=trusted. Quem chama (runner) reaplica a tool-policy por superfície e impede
    sombrear tool nativa."""
    resolve = _resolve or _resolve_register
    out: dict = {}
    for plugin in plugins or []:
        reg = resolve(plugin)
        if reg is None:
            continue
        trust = "trusted" if plugin.source == "entry_point" else "untrusted"
        registrar = PluginRegistrar(plugin_context(plugin.name, trust=trust, cfg=cfg))
        try:
            reg(registrar)
        except Exception as e:  # noqa: BLE001 — register que explode não derruba os outros plugins
            emit(f"[plugin {plugin.name}] register() falhou: {e}")
            continue
        for name, tool in registrar.tools.items():
            out[name] = tool
            emit(f"[plugin {plugin.name}] +tool {name}")
    return out


def plugin_roots() -> list[Path]:
    """Raízes: projeto (.) + home do Okami + NATIVOS do pacote (viajam no pip install). O projeto vem 1º →
    vence o nativo de mesmo nome (discover_plugins dedup por nome, 1ª raiz ganha)."""
    roots = [Path(".")]
    try:
        from okami.home import okami_home
        roots.append(okami_home())
    except Exception:  # noqa: BLE001 — degrada (só usa '.') mas AVISA (era silencioso)
        warn("falha ao resolver okami_home p/ raízes de plugins", exc_info=True)
    try:
        from okami.builtin import builtin_root
        roots.append(builtin_root())               # plugins NATIVOS embarcados (independe do CWD)
    except Exception:  # noqa: BLE001
        warn("falha ao resolver builtin_root p/ plugins nativos", exc_info=True)
    return roots


__all__ = ["Plugin", "PluginContext", "PluginRegistrar", "discover_plugins", "load_plugin_tools",
           "plugin_context", "plugin_roots"]
