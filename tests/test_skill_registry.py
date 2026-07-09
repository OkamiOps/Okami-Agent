"""Catálogo de DESCOBERTA de skills (okami/skills/registry.py) — porta do skills_hub do Hermes:
o gap que faltava era BUSCA (o agente só instalava com owner/repo já em mãos). GitHubSource lista
SKILL.md nos taps confiáveis via Contents API (http/http_text INJETÁVEIS → sem rede real nos testes).
"""
from __future__ import annotations

from okami.skills.registry import GitHubSource, SkillCandidate, _rank_dedup


def _skillmd(name, description="uma skill", tags=None):
    tags = tags or []
    fm = f"---\nname: {name}\ndescription: {description}\n"
    if tags:
        fm += "triggers: [" + ", ".join(tags) + "]\n"
    return fm + "---\n## Como\nfaça x.\n"


def _fake_http_pair(repo_dirs: dict, repo_skillmds: dict):
    """repo_dirs: {(repo, path): [dirnames]}; repo_skillmds: {(repo, dirname): skillmd_text}."""
    def http(url):
        for (repo, path), dirs in repo_dirs.items():
            if url == f"https://api.github.com/repos/{repo}/contents/{path}":
                return [{"type": "dir", "name": d} for d in dirs]
        return []

    def http_text(url):
        for (repo, dirname), text in repo_skillmds.items():
            if url == f"https://raw.githubusercontent.com/{repo}/HEAD/skills/{dirname}/SKILL.md":
                return text
        raise RuntimeError("404")
    return http, http_text


def _mk_source(repo_paths, repo_dirs, repo_skillmds, **kw):
    http, http_text = _fake_http_pair(repo_dirs, repo_skillmds)
    return GitHubSource(repo_paths=repo_paths, http=http, http_text=http_text, cache={}, **kw)


# ------------------------------------------------------------------ search / browse básicos
def test_browse_lists_skills_from_taps():
    src = _mk_source(
        {"anthropics": [("anthropics/skills", "skills")]},
        {("anthropics/skills", "skills"): ["deploy-flow", "lint-check"]},
        {("anthropics/skills", "deploy-flow"): _skillmd("deploy-flow", "Faz deploy"),
         ("anthropics/skills", "lint-check"): _skillmd("lint-check", "Roda lint")},
    )
    out = src.browse(20)
    assert {c.name for c in out} == {"deploy-flow", "lint-check"}
    assert all(c.trust == "trusted" for c in out)          # anthropics é tap embutido


def test_search_filters_by_query_in_name_and_description():
    src = _mk_source(
        {"anthropics": [("anthropics/skills", "skills")]},
        {("anthropics/skills", "skills"): ["deploy-flow", "gmail-access"]},
        {("anthropics/skills", "deploy-flow"): _skillmd("deploy-flow", "Faz deploy de app"),
         ("anthropics/skills", "gmail-access"): _skillmd("gmail-access", "Acessa Gmail via OAuth")},
    )
    out = src.search("gmail", 10)
    assert len(out) == 1 and out[0].name == "gmail-access"
    assert out[0].source == "anthropics/skills" and out[0].only == "gmail-access"


def test_search_empty_query_behaves_like_browse():
    src = _mk_source(
        {"anthropics": [("anthropics/skills", "skills")]},
        {("anthropics/skills", "skills"): ["a"]},
        {("anthropics/skills", "a"): _skillmd("a")},
    )
    assert len(src.search("", 10)) == 1


def test_dirs_without_skillmd_are_skipped():
    src = _mk_source(
        {"anthropics": [("anthropics/skills", "skills")]},
        {("anthropics/skills", "skills"): ["real-skill", "not-a-skill"]},
        {("anthropics/skills", "real-skill"): _skillmd("real-skill")},   # not-a-skill sem SKILL.md → 404
    )
    out = src.browse(20)
    assert [c.name for c in out] == ["real-skill"]


def test_hidden_and_underscore_dirs_skipped():
    src = _mk_source(
        {"anthropics": [("anthropics/skills", "skills")]},
        {("anthropics/skills", "skills"): [".hidden", "_private", "visible"]},
        {("anthropics/skills", "visible"): _skillmd("visible")},
    )
    out = src.browse(20)
    assert [c.name for c in out] == ["visible"]


# ------------------------------------------------------------------ ranking + dedup
def test_rank_dedup_prefers_higher_trust_and_sorts_by_name():
    cands = [
        SkillCandidate(name="zzz", description="", source="a/a", only="zzz", trust="community"),
        SkillCandidate(name="aaa", description="", source="a/a", only="aaa", trust="trusted"),
        SkillCandidate(name="mmm", description="", source="a/a", only="mmm", trust="unverified"),
    ]
    out = _rank_dedup(cands)
    # trusted primeiro; empate de rank vai por nome — community(zzz) > unverified(mmm)
    assert [c.name for c in out] == ["aaa", "zzz", "mmm"]


def test_rank_dedup_collapses_same_source_and_only_keeping_best_trust():
    cands = [
        SkillCandidate(name="dup", description="v1", source="a/a", only="dup", trust="community"),
        SkillCandidate(name="dup", description="v2", source="a/a", only="dup", trust="trusted"),
    ]
    out = _rank_dedup(cands)
    assert len(out) == 1 and out[0].trust == "trusted" and out[0].description == "v2"


def test_search_dedups_across_taps_when_limit_applied():
    # dois taps, cada um com 2 skills batendo a query → resultado respeita o limit
    src = _mk_source(
        {"anthropics": [("anthropics/skills", "skills")], "openai": [("openai/skills", "skills")]},
        {("anthropics/skills", "skills"): ["mail-a", "mail-b"],
         ("openai/skills", "skills"): ["mail-c"]},
        {("anthropics/skills", "mail-a"): _skillmd("mail-a", "mail tool"),
         ("anthropics/skills", "mail-b"): _skillmd("mail-b", "mail tool"),
         ("openai/skills", "mail-c"): _skillmd("mail-c", "mail tool")},
    )
    out = src.search("mail", 2)
    assert len(out) == 2


# ------------------------------------------------------------------ cache (offline / TTL)
def test_second_call_uses_cache_not_http():
    calls = []
    repo_dirs = {("anthropics/skills", "skills"): ["a"]}
    repo_skillmds = {("anthropics/skills", "a"): _skillmd("a")}

    def http(url):
        calls.append(url)
        for (repo, path), dirs in repo_dirs.items():
            if url == f"https://api.github.com/repos/{repo}/contents/{path}":
                return [{"type": "dir", "name": d} for d in dirs]
        return []

    def http_text(url):
        for (repo, dirname), text in repo_skillmds.items():
            if url == f"https://raw.githubusercontent.com/{repo}/HEAD/skills/{dirname}/SKILL.md":
                return text
        raise RuntimeError("404")

    cache: dict = {}
    src = GitHubSource(repo_paths={"anthropics": [("anthropics/skills", "skills")]},
                       http=http, http_text=http_text, cache=cache)
    src.browse(10)
    first_calls = len(calls)
    src2 = GitHubSource(repo_paths={"anthropics": [("anthropics/skills", "skills")]},
                        http=http, http_text=http_text, cache=cache)   # mesmo cache dict = "disco" compartilhado
    src2.browse(10)
    assert len(calls) == first_calls                       # nada novo: veio do cache (TTL não expirou)


def test_expired_cache_refetches():
    import time
    repo_dirs = {("anthropics/skills", "skills"): ["a"]}
    repo_skillmds = {("anthropics/skills", "a"): _skillmd("a")}
    http, http_text = _fake_http_pair(repo_dirs, repo_skillmds)
    cache = {"anthropics/skills:skills": {"ts": time.time() - 999999, "items": []}}
    src = GitHubSource(repo_paths={"anthropics": [("anthropics/skills", "skills")]},
                       http=http, http_text=http_text, cache=cache, cache_ttl=3600.0)
    out = src.browse(10)
    assert len(out) == 1                                    # cache velho descartado → busca de novo


def test_fetch_repo_fail_open_on_http_error():
    def boom(url):
        raise RuntimeError("rede fora")
    src = GitHubSource(repo_paths={"anthropics": [("anthropics/skills", "skills")]},
                       http=boom, http_text=lambda u: "", cache={})
    assert src.browse(10) == []                             # descoberta nunca quebra


def test_default_source_uses_builtin_taps():
    from okami.skills.registry import default_source
    src = default_source()
    assert "anthropics" in src._repo_paths                   # tap embutido resolvido de sources.py


# ------------------------------------------------------------------ SSRF guard aplicado nas buscas reais
def test_real_http_helpers_validate_public_url(monkeypatch):
    from okami.skills import registry as reg
    from okami.core.net_guard import BlockedURL

    calls = []

    def fake_guarded_urlopen(url, **kw):
        calls.append(url)
        raise BlockedURL("bloqueado no teste")

    monkeypatch.setattr(reg, "guarded_urlopen", fake_guarded_urlopen)
    try:
        reg._http_get_json("http://169.254.169.254/latest/meta-data/")
    except BlockedURL:
        pass
    else:
        raise AssertionError("deveria ter levantado BlockedURL")
    assert calls                                              # passou pela guarda (não pulou o SSRF check)


def test_inspect_swallows_ssrf_block_as_missing_skill():
    """Se a guarda anti-SSRF recusar a URL (ex.: redirect malicioso), o repo simplesmente não entra
    no índice — descoberta é fail-open, não propaga BlockedURL pro chamador."""
    from okami.core.net_guard import BlockedURL

    def http(url):
        return [{"type": "dir", "name": "x"}]

    def http_text(url):
        raise BlockedURL("bloqueado")

    src = GitHubSource(repo_paths={"anthropics": [("anthropics/skills", "skills")]},
                       http=http, http_text=http_text, cache={})
    assert src.browse(10) == []
