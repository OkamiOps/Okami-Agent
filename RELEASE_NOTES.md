# 🐺 Okami Agent `v0.15-beta` — Native Tools, Provider Control & Telegram

> A reliability release for the part of an agent that matters most: **finishing the job without losing
> tool calls, ignoring cancellation, or silently switching the model you asked for.**

| | |
|---|---|
| **Release** | `v0.15-beta` |
| **Published** | 2026-07-11 |
| **Compared with** | `v0.14.3-beta` |
| **Scope** | 39 commits · 413 files |
| **Verification** | 4,075 passed · 13 skipped · Ruff clean |
| **Compatibility** | Existing YAML, aliases and CLI/OAuth transports remain valid |

🌐 [Website](https://okamiagent.com) · 📚 [Documentation](https://okamiagent.com/docs) ·
📋 [Full changelog](https://github.com/OkamiOps/Okami-Agent/blob/main/CHANGELOG.md)

---

## Why this release exists

Okami already had native tool calling, multiple providers and a Telegram gateway. The weak point was the
space **between** those features:

- a streamed native tool call could not be reconstructed as a first-class action;
- a crash could leave an assistant call without its tool result;
- retry and fallback could outlive the request that created them;
- provider, model and transport decisions were spread across multiple layers;
- Telegram exposed only a fraction of the provider/model controls available in the CLI.

`v0.15-beta` closes those gaps as one vertical path. A model can stream structured calls, the harness can
execute and checkpoint them atomically, cancellation can stop the recovery chain, and Telegram can select
the same runtime target as the CLI — without trusting arbitrary callback payloads.

## ✨ Highlights

| Area | What changed | What it means in practice |
|---|---|---|
| 🧠 **Native tool protocol** | Structured deltas, atomic assistant/tool history and interrupted-call repair | Fewer broken multi-turn sessions and no silent re-execution after a crash |
| ⏱️ **Cancellation** | Total, TTFB and idle deadlines with cooperative abort and interruptible retry | `/stop` and timeouts stop the recovery chain instead of merely changing the UI |
| 🔌 **Provider runtime** | Immutable targets, one resolver and a transport registry | Provider/model/endpoint decisions are inspectable and consistent |
| 💬 **Telegram** | Secure model picker, `/providers`, persistent selection and safer callbacks | Switching models on mobile no longer requires memorizing IDs |
| 🔐 **Authentication** | Six-provider OAuth/token-plan onboarding and real model discovery | Fewer manual `.env` edits and fewer fake “provider connected” states |
| 🧰 **Skills** | 30+ built-in skills plus Git context, Meet and Teams plugins | More useful workflows ship with the agent instead of being copied by hand |
| 🛡️ **Hardening** | Anti-hammer/floundering guards, credential-safe enumeration and clean Ruff gate | Less looping, less accidental secret exposure and a cleaner baseline |

---

## 🧠 Native tool calls are now a complete protocol

Streaming is no longer limited to text. Okami now accumulates structured tool-call deltas — ID, function
name and JSON arguments — and returns them to the harness as native calls.

The message history follows the provider protocol instead of approximating it:

```text
assistant(tool_calls=[call_1, call_2])
├─ tool(call_1) → result
└─ tool(call_2) → result
```

That group stays atomic during:

- session history persistence;
- context compaction;
- checkpoint/resume after a crash;
- terminal acceptance or rejection.

If a checkpoint contains a call without a result, resume records it as `INTERRUPTED`; it does **not**
quietly execute the action again. If a terminal action is rejected by verification, it receives one
`REJECTED` result. If a terminal is accepted before later calls in the same batch, those calls are closed
as `not executed` instead of being left orphaned.

## ⏱️ Cancellation and timeouts now belong to the request

Each generation owns a `RequestContext` with:

- total request deadline;
- time-to-first-byte deadline;
- stream idle deadline;
- cancellation reason and terminal state;
- cooperative abort handles when the transport exposes one.

Retries use the **remaining** budget, not a fresh full timeout. Backoff is interruptible. The harness
checks cancellation before worker admission, after generation and before compaction, escalation or
fallback. Once cancellation wins, no “helpful” recovery branch gets to restart the work behind the
user's back.

> A transport without a physical abort handle cannot unsend a remote HTTP request. Okami stops waiting
> and prevents subsequent work, but does not pretend it killed something the provider does not allow it
> to kill.

## 🔌 Provider/model routing has one source of truth

The new runtime boundary separates three concepts that were previously tangled:

| Concept | Responsibility |
|---|---|
| `RuntimeTarget` | Immutable effective provider, model, endpoint, API mode, capabilities and billing route |
| `TargetResolver` | Converts aliases, overrides and fallbacks into a concrete target |
| `TransportRegistry` | Executes the adapter selected by that target |

LiteLLM still works and remains important for compatibility. The difference is architectural:
`LiteLLMCompatTransport` is now **one adapter**, not the place where the entire provider model lives.

Other provider improvements in this release:

- structured fallbacks distinguish different models under the same provider;
- `Completion.provider/model` reports the target that actually served the answer;
- unknown provider knobs are preserved without silently colliding with core configuration;
- custom providers record their transport explicitly;
- endpoints and credential references can be shown without printing secret values;
- authentication menus cover OAuth and token-plan providers and discover real models.

## 💬 Telegram catches up with the CLI

Telegram now uses the same provider/model resolver and session persistence as the CLI.

```text
/providers     show configured providers without exposing credentials
/model         open the inline model picker
/model <id>    select an explicit provider/model
/thoughts off  hide live reasoning while keeping model reasoning enabled
```

The inline picker uses short callbacks such as `okmodel:3`. The number is resolved against an in-memory
catalog bound to that chat; Telegram cannot inject an arbitrary provider/model string through callback
data. Invalid or stale indexes are ignored safely.

Also included:

- heartbeat edits one status message instead of spamming the conversation;
- generated images/videos emit `MEDIA:` and are attached to the Telegram turn;
- slash-command descriptions include the new provider flow;
- custom provider setup confirms endpoint, transport and env reference without echoing the key.

## 🧯 The harness is harder to trap in stupid loops

Several production-shaped failure modes were closed alongside the protocol work:

- **anti-hammer** stops repeated calls to the same tool with the same ineffective input;
- **floundering detection** interrupts long sequences that make no measurable progress;
- the circuit breaker compares normalized failures instead of raw strings that never matched;
- working context has a practical ceiling even when the advertised model window is enormous;
- `/steer` is drained at the top of the loop, before the next generation;
- streamed reasoning is scrubbed from the user-facing answer;
- verification rules no longer punish documentation-only writes as if they were executable code;
- an explicitly requested model or tool cannot be silently substituted.

## 🧰 30+ skills and new built-in integrations

The release also ships a large skills wave from the Hermes comparison and skills.sh ecosystem:

- frontend design and implementation references;
- API debugging, Docker operations and codebase inspection;
- Google Workspace, Apple Notes and Reminders;
- OCR, PDF, diagrams, infographics and video workflows;
- Git context, Google Meet and Teams plugins;
- remote skills discovery and native-first tool guidance.

These are versioned defaults. Local skills and agent identity files still override the built-ins.

## 🛡️ Security and correctness

- credential files cannot be read even in permissive/yolo execution;
- file enumeration and search hide sensitive credential names;
- secret-plus-network scanning was recalibrated to avoid common design/web false positives;
- context usage includes provider cache data instead of under-reporting occupancy;
- provider reasoning stays out of normal user-visible responses;
- 75 existing Ruff findings were reduced to zero.

---

## 🚀 Install or upgrade

### Existing installation

```bash
okami upgrade --check
okami upgrade
okami version
okami doctor
```

### Fresh install — Linux, macOS or WSL

```bash
curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
```

### Fresh install — Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex
```

No mandatory configuration migration is required. Existing `okami.yaml`, provider aliases, fallback
names and CLI/OAuth transports remain supported.

## ✅ Verification

- [x] `4,075 passed, 13 skipped`
- [x] `uv run ruff check okami tests` — clean
- [x] `git diff --check` — clean
- [x] native tool-call rejection/terminal regressions covered
- [x] Telegram callback catalog isolation covered
- [x] provider target/transport/fallback matrices covered

The controlled full-suite run used the repository's complete agent identity fixture. The developer
checkout may contain gitignored `agents/okami/*` overrides; stale or incomplete local overrides can make
identity-content tests fail without changing the packaged defaults.

## 🚧 Deliberately not included

This release does **not** claim complete Hermes parity:

- LiteLLM is not yet optional for every provider;
- very large model catalogs still need a paginated/hierarchical Telegram picker;
- Discord did not receive the same UX pass;
- Okami did not copy Hermes' full asynchronous gateway architecture.

Those are explicit follow-ups, not hidden unfinished branches in this release.

<details>
<summary><strong>🇧🇷 Resumo em português</strong></summary>

O `v0.15-beta` fecha o caminho inteiro de tool call nativa: o modelo pode enviar deltas estruturados, o
harness remonta a chamada, grava assistant/tool como grupo atômico, retoma crash sem reexecutar ação e
respeita cancelamento durante retry/fallback.

Providers agora passam por target imutável, resolver único e registry de transports. LiteLLM continua
funcionando como compatibilidade, mas não concentra mais a arquitetura. No Telegram entraram
`/providers`, picker inline seguro de `/model`, seleção persistente, `/thoughts`, heartbeat sem spam e
entrega de mídia gerada.

A release também traz OAuth/token-plan de seis providers, mais de 30 skills builtin, bloqueio de
enumeração de credenciais, freios anti-loop e Ruff zerado. Não há migração obrigatória do YAML.

</details>

---

## Links

- 🌐 [okamiagent.com](https://okamiagent.com)
- 📚 [Documentation](https://okamiagent.com/docs)
- 💻 [Okami Agent repository](https://github.com/OkamiOps/Okami-Agent)
- 📋 [Complete changelog](https://github.com/OkamiOps/Okami-Agent/blob/main/CHANGELOG.md)
- 🏗️ [Architecture](https://github.com/OkamiOps/Okami-Agent/blob/main/docs/ARCHITECTURE.md)

**MIT License** © 2026 OkamiOps.
