"""Catálogo de DESCOBERTA de skills (porta do skills_hub do Hermes — item que faltava: busca).

Incidente real: o agente só INSTALA uma skill se já souber o `owner/repo` exato — não há como
DESCOBRIR o que existe. Quando a tarefa pedia uma skill que o agente não tinha (ex.: acesso
Google/Gmail), ele ou inventava uma fonte ou improvisava um workaround inseguro (o incidente
"gog" — vasculhar credencial no disco). `okami/skills/hub.py` documentava isso: "NÃO há servidor
de catálogo remoto". Aqui está a camada que faltava — SEM servidor próprio, sem exec de código:
lista repositórios/pastas com SKILL.md nos taps GitHub CONFIÁVEIS (mesmos tiers de
`okami.skills.sources` — importa, não duplica) via Contents API, com a guarda anti-SSRF
(`okami.core.net_guard.guarded_urlopen`). `search()`/`browse()` devolvem candidatos prontos p/
irem direto no install existente (`install_skill`/`okami learn`) — a instalação em si (quarentena
+ scan + matriz confiança×verdict + lockfile) não muda uma linha.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from okami.core.net_guard import BROWSER_HEADERS, guarded_urlopen
from okami.skills.sources import _BUILTIN_GITHUB_TAPS, _github_trust, list_taps

INDEX_CACHE_TTL = 3600.0        # 1h — mesma ordem de grandeza do INDEX_CACHE_TTL do Hermes
_CACHE_NAME = "skill_index_cache.json"

# org (tap) -> [(repo, path)] — onde procurar SKILL.md dentro de cada org confiável. Convenção
# observada nos repos reais (anthropics/skills, huggingface/skills): pasta `skills/` na raiz de
# `<org>/skills`. Org sem repo conhecido nesta forma simplesmente não entra no índice (fail-open:
# busca sai vazia p/ ela, não quebra as demais). O dono pode ampliar via `okami skill tap`.
_DEFAULT_REPO_PATHS: dict[str, list[tuple[str, str]]] = {
    "anthropics": [("anthropics/skills", "skills")],
    "openai": [("openai/skills", "skills")],
    "huggingface": [("huggingface/skills", "skills")],
    "nousresearch": [("NousResearch/skills", "skills")],
    "okamiops": [("okamiops/skills", "skills")],
}


@dataclass(frozen=True)
class SkillCandidate:
    """Um resultado de busca/browse — já pronto p/ `install_skill(source=.., name=only)`."""
    name: str
    description: str
    source: str                      # owner/repo — o `source` que install_skill/okami-learn espera
    only: str                        # nome exato da pasta p/ o `only=` (repo-biblioteca com várias skills)
    trust: str                       # builtin | trusted | community | unverified (mesmos tiers do sources.py)
    tags: tuple = field(default_factory=tuple)


class SkillSource(ABC):
    """Interface de UMA fonte de catálogo p/ descoberta. `GitHubSource` é a única real por ora —
    nada no chamador (CLI/tool) muda se outra fonte (ex.: well-known) entrar depois."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SkillCandidate]: ...

    @abstractmethod
    def browse(self, limit: int = 20) -> list[SkillCandidate]: ...


def _cache_path() -> Path:
    from okami.home import okami_home
    return okami_home() / _CACHE_NAME


def _load_cache() -> dict:
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_cache(cache: dict) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _http_get_json(url: str, timeout: float = 15.0):
    """GET JSON com a guarda anti-SSRF. Injetável (`http=`) p/ teste offline."""
    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "application/vnd.github.v3+json"
    with guarded_urlopen(url, timeout=timeout, headers=headers) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _http_get_text(url: str, timeout: float = 15.0) -> str:
    with guarded_urlopen(url, timeout=timeout, headers=dict(BROWSER_HEADERS)) as r:
        return r.read().decode("utf-8", "ignore")


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    m = _FRONTMATTER_RE.match(text or "")
    if not m:
        return {}
    try:
        import yaml
        data = yaml.safe_load(m.group(1))
    except Exception:  # noqa: BLE001 — SKILL.md malformada não pode derrubar a busca
        return {}
    return data if isinstance(data, dict) else {}


_TRUST_RANK = {"builtin": 3, "trusted": 2, "community": 1, "unverified": 0}


def _rank_dedup(cands: list[SkillCandidate]) -> list[SkillCandidate]:
    """Dedup por (source, only) preferindo o de MAIOR confiança; ordena trusted-primeiro, depois nome
    (paridade com o dedup de `GitHubSource.search` do Hermes)."""
    seen: dict[tuple, SkillCandidate] = {}
    for c in cands:
        k = (c.source, c.only)
        if k not in seen or _TRUST_RANK.get(c.trust, 0) > _TRUST_RANK.get(seen[k].trust, 0):
            seen[k] = c
    return sorted(seen.values(), key=lambda c: (-_TRUST_RANK.get(c.trust, 0), c.name.lower()))


class GitHubSource(SkillSource):
    """Lista skills (dirs com SKILL.md) nos repos/paths dos taps GitHub confiáveis (embutidos +
    `add_tap()`) via Contents API — SEM `git clone`, SEM executar nada. Cache em disco (TTL) evita
    martelar a API do GitHub a cada busca; `http=`/`http_text=` injetáveis p/ teste offline."""

    def __init__(self, repo_paths: dict | None = None, *, http=None, http_text=None,
                cache_ttl: float = INDEX_CACHE_TTL, cache: dict | None = None):
        self._repo_paths = repo_paths if repo_paths is not None else self._resolve_taps()
        self._http = http or _http_get_json
        self._http_text = http_text or _http_get_text
        self._cache_ttl = cache_ttl
        self._external_cache = cache        # injeção de teste: bypassa disco

    @staticmethod
    def _resolve_taps() -> dict:
        orgs = set(_BUILTIN_GITHUB_TAPS) | {o.lower() for o in list_taps().get("github", [])}
        out: dict[str, list[tuple[str, str]]] = {}
        for org in orgs:
            pairs = _DEFAULT_REPO_PATHS.get(org.lower())
            if pairs:
                out[org] = pairs
        return out

    def _index(self) -> list[SkillCandidate]:
        cache = self._external_cache if self._external_cache is not None else _load_cache()
        now = time.time()
        out: list[SkillCandidate] = []
        dirty = False
        for org, pairs in self._repo_paths.items():
            for repo, path in pairs:
                key = f"{repo}:{path}"
                entry = cache.get(key)
                if entry and (now - float(entry.get("ts", 0))) < self._cache_ttl:
                    items = entry.get("items", [])
                else:
                    items = self._fetch_repo(repo, path)
                    cache[key] = {"ts": now, "items": items}
                    dirty = True
                for it in items:
                    out.append(SkillCandidate(
                        name=it.get("name") or it.get("only", ""), description=it.get("description", ""),
                        source=repo, only=it.get("only", ""), trust=_github_trust(repo.split("/", 1)[0]),
                        tags=tuple(it.get("tags") or [])))
        if dirty and self._external_cache is None:
            _save_cache(cache)
        return out

    def _fetch_repo(self, repo: str, path: str) -> list[dict]:
        """Lista subpastas de `path` no `repo` e, p/ cada uma, checa se tem SKILL.md. FAIL-OPEN: erro
        de rede/rate-limit não derruba a busca inteira (só essa fonte fica sem resultado)."""
        url = f"https://api.github.com/repos/{repo}/contents/{path.strip('/')}"
        try:
            entries = self._http(url)
        except Exception:  # noqa: BLE001 — descoberta nunca quebra por causa de UM repo
            return []
        if not isinstance(entries, list):
            return []
        out = []
        for e in entries:
            if not isinstance(e, dict) or e.get("type") != "dir":
                continue
            dname = e.get("name", "")
            if not dname or dname.startswith((".", "_")):
                continue
            meta = self._inspect(repo, f"{path.strip('/')}/{dname}".strip("/"))
            if meta is None:
                continue
            out.append({"name": meta.get("name") or dname, "description": meta.get("description", ""),
                        "only": dname, "tags": meta.get("tags", [])})
        return out

    def _inspect(self, repo: str, skill_path: str) -> dict | None:
        """Busca só o frontmatter do SKILL.md (raw, sem clonar) — None se não existir/não parsear."""
        url = f"https://raw.githubusercontent.com/{repo}/HEAD/{skill_path}/SKILL.md"
        try:
            text = self._http_text(url)
        except Exception:  # noqa: BLE001 — dir sem SKILL.md (ou 404) não é skill; segue adiante
            return None
        fm = _parse_frontmatter(text)
        if not fm:
            return None
        tags = fm.get("triggers") or fm.get("tags") or []
        return {"name": str(fm.get("name", "")), "description": str(fm.get("description", "")),
                "tags": tags if isinstance(tags, list) else []}

    def search(self, query: str, limit: int = 10) -> list[SkillCandidate]:
        q = (query or "").strip().lower()
        cands = self._index()
        if q:
            cands = [c for c in cands if q in f"{c.name} {c.description} {' '.join(c.tags)}".lower()]
        return _rank_dedup(cands)[:max(1, limit)]

    def browse(self, limit: int = 20) -> list[SkillCandidate]:
        return _rank_dedup(self._index())[:max(1, limit)]


def default_source() -> GitHubSource:
    return GitHubSource()
