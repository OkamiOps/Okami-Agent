# Harness and Providers Modernization Design

## Context

This design compares and adapts the current Okami Agent `59090f8` against the
current Hermes `3b2ef78`. It intentionally ports contracts and verified
behaviour instead of copying Hermes monoliths.

The implementation is backward-compatible. Existing `okami.yaml` provider
blocks, aliases, transport names, LiteLLM-prefixed model IDs, OAuth stores and
`fallback: [provider_name]` lists remain valid.

## Problems addressed in this tranche

1. The runner abandons an in-flight generation in a daemon thread when its
   deadline expires. `/stop` reaches retry backoff but not the active request.
2. Token streaming drops native `tool_calls` deltas and is therefore disabled
   whenever native tools are active.
3. Provider, model, endpoint, API mode, credential identity, capability and
   billing route are not represented by one immutable runtime value.
4. LiteLLM calls and process-global settings are spread across provider,
   transport, streaming and capability-probe modules.
5. Fallback is only `list[str]`, so it cannot preserve an explicit destination
   model, endpoint or API mode.
6. Multiple native tool calls are not stored as one atomic assistant/tool
   message group throughout execution, compaction and resume.

## Non-negotiable invariants

- `TaskState` and the verified terminal tools remain the source of completion.
- Approval stays fail-closed, single-use and bound to the exact tool arguments.
- Truncated native tool arguments are never repaired or executed.
- Mutating tools remain serial. Existing conservative read parallelism stays.
- Partial text already delivered to a user is never automatically replayed.
- Rate guard, credential pool, OAuth refresh and current native transports keep
  their behaviour.
- Runtime values never contain raw API keys or OAuth tokens.

## Target architecture

### Request lifecycle

Every LLM attempt receives one `RequestContext`. It owns a request ID,
request-scoped timestamps, cancellation state and idempotent abort callbacks.
Its watchdog distinguishes total, time-to-first-byte and idle timeouts.

The runner polls the context and never presents a deadline as proof that the
underlying call was killed. Transports register a request-local aborter when
they can close an HTTP stream, response or subprocess. Abort callbacks are
idempotent and execute outside the context lock. A provider without a physical
abort handle remains bounded by its configured transport timeout and is
reported as such; it must not retry or fall back after user cancellation.

### Runtime target

`TargetResolver` converts legacy selection inputs into an immutable
`RuntimeTarget`:

```text
provider + model + base_url + api_mode + transport
         + credential_ref + capabilities + billing_route
```

`credential_ref` names an environment variable, OAuth store or provider pool;
it never contains the credential itself. `RuntimeTarget` is the value carried
through primary and fallback execution.

### Transport boundary

`TransportRegistry` owns transport dispatch. Existing native functions are
registered through small adapters. All LiteLLM calls live behind
`LiteLLMCompatTransport`; importing a provider module no longer mutates
LiteLLM process globals.

Compatibility parameter dropping is explicit per request. The adapter emits a
diagnostic containing the candidate parameter names before asking LiteLLM to
drop unsupported values. Strict mode rejects them.

### Structured fallback

Fallback entries accept either the old provider string or a structured target
reference. Every entry is resolved before use, deduplicated by effective
destination and protected against cycles. The exact fallback model and
endpoint are preserved, and `Completion.provider/model` reports what served the
turn.

### Native streaming

The streaming layer yields structured events for text, reasoning, tool-call
deltas and finish state. Tool calls are accumulated by index. Names and IDs are
assigned, while argument fragments are concatenated. Calls become executable
only after the stream closes and their arguments parse as a complete JSON
object. Tool arguments never go to the display callback.

### Native history groups

One assistant message contains every tool call produced by a native turn.
Every success, rejection or error is followed by a matching consecutive
`role=tool` result. Compaction and resume treat this assistant-plus-results
group as an indivisible unit and never re-execute an interrupted call.

## Delivery scope

This tranche delivers:

1. request context and watchdog;
2. runtime targets and resolver;
3. transport registry and LiteLLM compatibility adapter;
4. structured backward-compatible fallback;
5. native structured streaming;
6. atomic native history/compaction groups;
7. focused and full-suite verification plus migration documentation.

## Deferred work

- Provider/model onboarding UI and remote model-catalog redesign.
- Transactional Telegram/CLI model picker and persistence.
- Removing LiteLLM or replacing every vendor with a native SDK.
- Full provider pricing and models.dev ingestion.
- Native streaming implementations specialised for every vendor SDK.
- Parallel execution of mutating native tool calls.
- Semantic resume of an interrupted side-effecting tool.

## Acceptance criteria

- Existing configuration and transport tests remain green.
- Cancellation returns promptly, invokes a registered aborter once and never
  enters retry/fallback afterwards.
- Watchdog tests independently prove total, TTFB and idle timeout behaviour.
- Native streaming returns complete `Completion.tool_calls` and never executes
  incomplete JSON.
- Legacy and structured fallback reach the exact resolved destination.
- No provider import changes LiteLLM process globals.
- Native multi-call history remains valid through execution, compaction and
  resume.
- Full pytest and Ruff gates pass from a clean feature worktree.
