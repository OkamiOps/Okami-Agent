# Harness and Providers Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Okami's LLM request pipeline cancellable, structurally stream native tool calls, and resolve providers/fallbacks through immutable runtime targets while preserving every existing configuration.

**Architecture:** A request-scoped watchdog and immutable runtime target become the shared boundary between runner, provider retries, transports and streaming. A transport registry demotes LiteLLM to an explicit compatibility adapter; structured fallback and atomic native-history groups build on those contracts.

**Tech Stack:** Python 3.11+, Pydantic v2, LiteLLM compatibility adapter, pytest, Ruff.

## Global Constraints

- Preserve existing `okami.yaml`, aliases, transport names, OAuth stores and LiteLLM-prefixed model IDs.
- Accept both legacy `fallback: [provider]` and structured fallback entries.
- Never place raw API keys or OAuth tokens in `RuntimeTarget`, logs, events or persisted session metadata.
- Never execute or repair structurally truncated native tool arguments.
- Keep approval fail-closed, single-use and bound to the exact argument hash.
- Keep mutating tools serial and preserve existing conservative read parallelism.
- Never retry a partial stream after visible output has been delivered.
- Use TDD: each production behaviour requires a test observed failing for the expected reason first.
- Every implementation and review worker must use `gpt-5.6-luna` with `model_reasoning_effort=xhigh`.

---

### Task 1: Request-scoped watchdog and cancellation contract

**Files:**
- Create: `okami/llm/request.py`
- Modify: `okami/runner.py`
- Modify: `okami/llm/providers.py`
- Test: `tests/test_request_watchdog.py`
- Test: `tests/test_request_cancellation.py`
- Test: `tests/test_overall_timeout.py`

**Interfaces:**
- Produces: `RequestTimeouts`, `RequestContext`, `RequestCancelled`, `RequestWatchdogTimeout`.
- Produces: `RequestContext.run(fn)`, `observe()`, `register_abort()`, `cancel()`, `remaining()` and `check()`.
- Consumed later by: transport adapters and structured streaming.

- [ ] **Step 1: Write the pure watchdog tests**

```python
class FakeClock:
    def __init__(self):
        self.now = 100.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds

@pytest.fixture
def fake_clock():
    return FakeClock()

def test_ttfb_expires_before_first_event(fake_clock):
    ctx = RequestContext(RequestTimeouts(total_s=30, ttfb_s=2, idle_s=5), clock=fake_clock)
    fake_clock.advance(2.1)
    with pytest.raises(RequestWatchdogTimeout, match="ttfb"):
        ctx.check()

def test_idle_expires_after_first_event(fake_clock):
    ctx = RequestContext(RequestTimeouts(total_s=30, ttfb_s=2, idle_s=5), clock=fake_clock)
    ctx.observe()
    fake_clock.advance(5.1)
    with pytest.raises(RequestWatchdogTimeout, match="idle"):
        ctx.check()

def test_cancel_invokes_aborter_once():
    calls = []
    ctx = RequestContext(RequestTimeouts(total_s=30, ttfb_s=None, idle_s=None))
    ctx.register_abort(lambda reason: calls.append(reason))
    ctx.cancel("user")
    ctx.cancel("user")
    assert calls == ["user"]
```

- [ ] **Step 2: Run the watchdog tests and verify RED**

Run: `uv run pytest -q tests/test_request_watchdog.py`

Expected: collection/import failure because `okami.llm.request` does not exist.

- [ ] **Step 3: Implement the minimal request contract**

```python
class RequestCancelled(RuntimeError):
    pass

class RequestWatchdogTimeout(TimeoutError):
    pass

@dataclass(frozen=True, slots=True)
class RequestTimeouts:
    total_s: float | None = None
    ttfb_s: float | None = None
    idle_s: float | None = None

class RequestContext:
    def __init__(self, limits, *, clock=time.monotonic, poll_s=0.05, abort_grace_s=0.25):
        self.request_id = uuid.uuid4().hex
        self.limits, self.clock, self.poll_s = limits, clock, poll_s
        self.abort_grace_s = abort_grace_s
        self.started_at = clock()
        self.first_event_at = self.last_event_at = None
        self._cancelled = threading.Event()
        self._reason = ""
        self._aborters, self._abort_lock, self._aborted = [], threading.Lock(), False

    def observe(self) -> None:
        now = self.clock()
        if self.first_event_at is None:
            self.first_event_at = now
        self.last_event_at = now

    def remaining(self) -> float | None:
        if self.limits.total_s is None:
            return None
        return max(0.0, self.limits.total_s - (self.clock() - self.started_at))

    def register_abort(self, callback) -> None:
        invoke_now = False
        with self._abort_lock:
            if self._aborted:
                invoke_now = True
            else:
                self._aborters.append(callback)
        if invoke_now:
            callback(self._reason)

    def cancel(self, reason="user") -> None:
        self._reason = self._reason or reason
        self._cancelled.set()
        with self._abort_lock:
            if self._aborted:
                return
            self._aborted = True
            aborters = tuple(self._aborters)
            self._aborters.clear()
        for abort in aborters:
            try:
                abort(self._reason)
            except Exception:
                log.warning("request abort callback failed", exc_info=True)

    def check(self) -> None:
        now = self.clock()
        if self._cancelled.is_set():
            raise RequestCancelled(self._reason)
        if self.limits.total_s is not None and now - self.started_at >= self.limits.total_s:
            self.cancel("total")
            raise RequestWatchdogTimeout("total")
        if self.first_event_at is None and self.limits.ttfb_s is not None and now - self.started_at >= self.limits.ttfb_s:
            self.cancel("ttfb")
            raise RequestWatchdogTimeout("ttfb")
        if self.last_event_at is not None and self.limits.idle_s is not None and now - self.last_event_at >= self.limits.idle_s:
            self.cancel("idle")
            raise RequestWatchdogTimeout("idle")

    def run(self, fn):
        box, done = {}, threading.Event()
        def worker():
            try:
                box["result"] = fn()
            except BaseException as exc:
                box["error"] = exc
            finally:
                done.set()
        threading.Thread(target=worker, daemon=True).start()
        try:
            while not done.wait(self.poll_s):
                self.check()
        except (RequestCancelled, RequestWatchdogTimeout):
            done.wait(self.abort_grace_s)
            raise
        self.check()
        if "error" in box:
            raise box["error"]
        return box["result"]
```

`run()` must poll the request state, propagate worker exceptions, call the
request-local aborter before returning on cancellation/timeout, and never
start retry/fallback work after cancellation. Abort callbacks execute outside
the context lock and are idempotent. If a transport exposes no physical abort
handle, the context reports that limitation, waits only the bounded abort
grace, and relies on the transport's own finite timeout; it must never claim
the underlying request was killed.

- [ ] **Step 4: Write integration tests before replacing the runner deadline**

```python
def test_cancel_aborts_inflight_request_and_does_not_fallback():
    released = threading.Event()
    aborts = []
    ctx = RequestContext(RequestTimeouts(total_s=10))
    ctx.register_abort(lambda reason: (aborts.append(reason), released.set()))
    ctx.cancel("user")
    assert released.wait(0.2)
    assert aborts == ["user"]
    with pytest.raises(RequestCancelled):
        ctx.check()

def test_total_deadline_is_shared_by_retry_and_fallback(fake_clock):
    ctx = RequestContext(RequestTimeouts(total_s=3), clock=fake_clock)
    fake_clock.advance(2)
    assert ctx.remaining() == pytest.approx(1)
    fake_clock.advance(1.1)
    with pytest.raises(RequestWatchdogTimeout, match="total"):
        ctx.check()

def test_legacy_generate_callable_without_request_still_works(tmp_path):
    task = Harness(lambda messages, schema: '{"tool":"respond","args":{"message":"ok"}}',
                   Task(goal="oi"), tmp_path).run()
    assert task.result == "ok"
```

The first test uses events instead of long sleeps and asserts one abort call,
prompt return, and no fallback provider call.

- [ ] **Step 5: Verify integration RED**

Run: `uv run pytest -q tests/test_request_cancellation.py tests/test_overall_timeout.py`

Expected: the old `_run_with_deadline()` cannot abort or share a request
deadline across retries/fallbacks.

- [ ] **Step 6: Wire request context through runner and providers**

Add explicit `request: RequestContext | None = None` parameters. Keep
`_run_with_deadline()` as a compatibility wrapper delegating to a context so
existing imports and tests do not break. `RequestCancelled` must bypass error
classification, retries and fallback.

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest -q tests/test_request_watchdog.py tests/test_request_cancellation.py tests/test_overall_timeout.py tests/test_provider_retry_timeout.py tests/test_interruptible_backoff.py`

Commit: `feat(harness): add request-scoped cancellation watchdog`

---

### Task 2: Immutable runtime targets and single resolver

**Files:**
- Create: `okami/llm/runtime.py`
- Create: `okami/llm/target_resolver.py`
- Modify: `okami/config.py`
- Modify: `okami/llm/model_aliases.py`
- Test: `tests/test_runtime_target.py`
- Test: `tests/test_target_resolver.py`
- Test: `tests/test_provider_config_params.py`

**Interfaces:**
- Produces: frozen `BillingRoute`, `TargetRef`, `RuntimeTarget`.
- Produces: `TargetResolver.resolve()` and `TargetResolver.fallback_targets()`.
- Consumes: existing alias resolution and `ProviderConfig`.

- [ ] **Step 1: Write failing target-contract tests**

```python
def test_runtime_target_is_hashable_and_immutable():
    target = RuntimeTarget("openrouter", "anthropic/claude", "https://openrouter.ai/api/v1",
                           "chat_completions", "litellm", "env:OPENROUTER_API_KEY",
                           frozenset({"tools"}), BillingRoute("openrouter", "anthropic/claude", "metered"))
    assert hash(target)
    with pytest.raises(FrozenInstanceError):
        target.model = "other"

def test_runtime_target_never_contains_resolved_secret(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    cfg = build_config({"default_provider": "openrouter", "providers": {"openrouter": {
        "model": "openrouter/auto", "api_key_env": "OPENROUTER_API_KEY"}}})
    target = TargetResolver().resolve(cfg)
    assert target.credential_ref == "env:OPENROUTER_API_KEY"
    assert "secret-value" not in repr(target)

def test_legacy_litellm_model_id_resolves_without_rewrite():
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "openai/gpt-4o"}}})
    assert TargetResolver().resolve(cfg).model == "openai/gpt-4o"

def test_api_mode_is_derived_from_transport():
    cfg = build_config({"default_provider": "codex", "providers": {"codex": {
        "model": "gpt-5.6", "transport": "codex_oauth"}}})
    assert TargetResolver().resolve(cfg).api_mode == "responses"

def test_provider_typo_fails_with_available_provider_names():
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}})
    with pytest.raises(TargetResolutionError, match="p"):
        TargetResolver().resolve(cfg, provider="typo")
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_runtime_target.py tests/test_target_resolver.py`

Expected: imports fail because the target modules do not exist.

- [ ] **Step 3: Implement target values**

```python
@dataclass(frozen=True, slots=True)
class BillingRoute:
    provider: str
    model: str
    mode: str
    base_url: str | None = None

@dataclass(frozen=True, slots=True)
class TargetRef:
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_mode: str | None = None
    credential_ref: str | None = None

@dataclass(frozen=True, slots=True)
class RuntimeTarget:
    provider: str
    model: str
    base_url: str | None
    api_mode: str
    transport: str
    credential_ref: str | None
    capabilities: frozenset[str]
    billing_route: BillingRoute
```

- [ ] **Step 4: Implement resolver compatibility**

`TargetResolver.resolve()` must accept provider/model arguments already used by
`complete_messages_ex`, preserve qualified LiteLLM IDs, derive API mode and
credential identity without resolving the secret, and reuse existing aliases.

- [ ] **Step 5: Make provider extras observable**

Write a failing test proving an unknown provider key is not silently lost.
Preserve it under `params` with one warning in compatibility mode; conflicting
known fields raise a clear validation error.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest -q tests/test_runtime_target.py tests/test_target_resolver.py tests/test_provider_config_params.py tests/test_model_aliases.py tests/test_provider_catalog.py`

Commit: `feat(providers): add immutable runtime target resolver`

---

### Task 3: Transport registry and LiteLLM compatibility adapter

**Files:**
- Create: `okami/llm/transport_registry.py`
- Create: `okami/llm/litellm_compat.py`
- Modify: `okami/llm/transports.py`
- Modify: `okami/llm/providers.py`
- Modify: `okami/llm/streaming.py`
- Modify: `okami/llm/native_capability.py`
- Test: `tests/test_transport_registry.py`
- Test: `tests/test_litellm_compat.py`
- Test: `tests/test_transports.py`

**Interfaces:**
- Consumes: `RuntimeTarget`, `RequestContext`, existing native transport functions.
- Produces: `CompletionRequest`, `LLMTransport`, `TransportRegistry`, `default_transport_registry()`.
- Produces: `LiteLLMCompatTransport.complete()` and `.stream()`.

- [ ] **Step 1: Write registry RED tests**

```python
@pytest.fixture
def runtime_target():
    return RuntimeTarget("p", "openai/gpt-4o", None, "chat_completions", "litellm",
                         "env:P_KEY", frozenset({"tools"}),
                         BillingRoute("p", "openai/gpt-4o", "metered"))

@pytest.fixture
def provider_config():
    return ProviderConfig(name="p", model="openai/gpt-4o", api_key_env="P_KEY")

class FakeTransport:
    def complete(self, target, provider_config, request):
        return Completion(text=target.model, provider=target.provider, model=target.model)

def test_registry_selects_transport_by_runtime_target(runtime_target, provider_config):
    registry = TransportRegistry()
    registry.register("litellm", FakeTransport())
    result = registry.complete(runtime_target, provider_config, CompletionRequest(messages=[]))
    assert result.model == runtime_target.model

def test_unknown_transport_fails_with_registered_names(runtime_target, provider_config):
    registry = TransportRegistry()
    registry.register("known", FakeTransport())
    unknown = replace(runtime_target, transport="missing")
    with pytest.raises(UnknownTransportError, match="known"):
        registry.complete(unknown, provider_config, CompletionRequest(messages=[]))

def test_existing_native_transport_names_remain_registered():
    names = default_transport_registry().names()
    assert {"litellm", "claude_cli", "codex_oauth", "minimax_oauth",
            "gemini_native", "bedrock_native", "gemini_cloudcode", "copilot_cli"} <= names
```

- [ ] **Step 2: Write LiteLLM isolation RED tests**

```python
def fake_response(text):
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=None)

class FakeClosableStream:
    def __init__(self):
        self.closed = False
    def __iter__(self):
        return iter(())
    def close(self):
        self.closed = True

def test_importing_providers_does_not_mutate_litellm_globals(monkeypatch):
    monkeypatch.setattr(litellm, "drop_params", False)
    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    importlib.reload(providers)
    assert litellm.drop_params is False
    assert litellm.suppress_debug_info is False

def test_compat_drop_policy_warns_with_parameter_names(monkeypatch, runtime_target, provider_config, caplog):
    monkeypatch.setattr(litellm, "get_supported_openai_params", lambda **kwargs: ["max_tokens"])
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: fake_response("ok"))
    request = CompletionRequest(messages=[], overrides={"temperature": 0.2, "max_tokens": 10})
    LiteLLMCompatTransport(drop_policy="warn").complete(runtime_target, provider_config, request)
    assert "temperature" in caplog.text

def test_strict_drop_policy_rejects_unsupported_parameters(monkeypatch, runtime_target, provider_config):
    monkeypatch.setattr(litellm, "get_supported_openai_params", lambda **kwargs: ["max_tokens"])
    request = CompletionRequest(messages=[], overrides={"temperature": 0.2})
    with pytest.raises(UnsupportedProviderParameter, match="temperature"):
        LiteLLMCompatTransport(drop_policy="error").complete(runtime_target, provider_config, request)

def test_stream_registers_request_local_close_aborter(monkeypatch, runtime_target, provider_config):
    stream = FakeClosableStream()
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: stream)
    ctx = RequestContext(RequestTimeouts(total_s=10))
    list(LiteLLMCompatTransport().stream(runtime_target, provider_config,
                                         CompletionRequest(messages=[], request=ctx)))
    ctx.cancel("user")
    assert stream.closed is True
```

- [ ] **Step 3: Verify RED**

Run: `uv run pytest -q tests/test_transport_registry.py tests/test_litellm_compat.py`

Expected: missing modules and the current import-global mutation assertion fail.

- [ ] **Step 4: Implement the registry and adapters**

```python
@dataclass(slots=True)
class CompletionRequest:
    messages: list[dict]
    response_schema: dict | None = None
    overrides: dict = field(default_factory=dict)
    raw_messages: list[dict] | None = None
    request: RequestContext | None = None

class LLMTransport(Protocol):
    def complete(self, target, provider_config, request) -> Completion:
        raise NotImplementedError
    def stream(self, target, provider_config, request):
        raise NotImplementedError
```

Register shims for existing native transports. Keep `transports.dispatch()` as
a compatibility wrapper during migration.

- [ ] **Step 5: Move direct LiteLLM calls**

Remove import-time `litellm.drop_params` and `litellm.suppress_debug_info`
assignments. Route completion, streaming and native capability probes through
the adapter. Per-request compatibility policy is `warn`; strict mode is
explicit. A request-local stream/client close callback is registered whenever
the underlying object exposes `close()`.

- [ ] **Step 6: Enforce the source gate**

Run: `rg -n '(^|[[:space:]])import litellm|litellm\.' okami`

Expected: executable references occur only in `okami/llm/litellm_compat.py`.

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest -q tests/test_transport_registry.py tests/test_litellm_compat.py tests/test_transports.py tests/test_native_capability.py tests/test_native_tools_e2e.py tests/test_provider_local.py`

Commit: `refactor(providers): isolate LiteLLM behind transport registry`

---

### Task 4: Backward-compatible structured fallback

**Files:**
- Create: `okami/llm/fallback.py`
- Modify: `okami/config.py`
- Modify: `okami/llm/target_resolver.py`
- Modify: `okami/llm/providers.py`
- Test: `tests/test_structured_fallback.py`
- Test: `tests/test_reliability.py`

**Interfaces:**
- Consumes: `TargetRef`, `RuntimeTarget`, `TargetResolver` and transport registry.
- Produces: a normalized, ordered immutable tuple of `RuntimeTarget` values.

- [ ] **Step 1: Write legacy and structured fallback RED tests**

```python
def fallback_cfg(entries):
    return build_config({
        "default_provider": "primary",
        "providers": {
            "primary": {"model": "primary/default", "max_retries": 1, "fallback": entries},
            "backup": {"model": "backup/default", "max_retries": 1},
        },
    })

def run_primary_failure_then_backup(monkeypatch):
    def fake_one(pc, messages, model, response_schema, overrides, raw_messages=None):
        if pc.name == "primary":
            raise RuntimeError("provider overloaded")
        return Completion(text="ok", provider=pc.name, model=model or pc.model)
    monkeypatch.setattr(providers, "_complete_one", fake_one)
    return providers.complete_messages_ex(fallback_cfg(["backup"]), [], _sleep=lambda seconds: None)

def test_legacy_provider_string_uses_destination_default_model():
    cfg = fallback_cfg(["backup"])
    chain = TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))
    assert [(t.provider, t.model) for t in chain] == [("backup", "backup/default")]

def test_structured_fallback_preserves_exact_model_base_and_api_mode():
    cfg = fallback_cfg([{"provider": "backup", "model": "vendor/exact",
                         "base_url": "https://fallback.example/v1",
                         "api_mode": "chat_completions"}])
    target = TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))[0]
    assert (target.model, target.base_url, target.api_mode) == (
        "vendor/exact", "https://fallback.example/v1", "chat_completions")

def test_fallback_deduplicates_effective_destination():
    cfg = fallback_cfg(["backup", {"provider": "backup", "model": "backup/default"}])
    assert len(TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))) == 1

def test_fallback_cycle_is_skipped_without_recursion():
    cfg = fallback_cfg(["primary", "backup"])
    chain = TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))
    assert [t.provider for t in chain] == ["backup"]

def test_cancelled_primary_never_enters_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "_complete_target", lambda target, *a, **k: calls.append(target.provider))
    ctx = RequestContext(RequestTimeouts(total_s=10))
    ctx.cancel("user")
    with pytest.raises(RequestCancelled):
        providers.complete_messages_ex(fallback_cfg(["backup"]), [], request=ctx)
    assert calls == []

def test_completion_reports_actual_fallback_provider_and_model(monkeypatch):
    result = run_primary_failure_then_backup(monkeypatch)
    assert (result.provider, result.model) == ("backup", "backup/default")
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_structured_fallback.py`

Expected: structured entries fail Pydantic parsing or lose their exact model.

- [ ] **Step 3: Add the compatible config union**

`ProviderConfig.fallback` accepts `list[str | FallbackTargetConfig]`.
`FallbackTargetConfig` mirrors `TargetRef` and contains no secret field.

- [ ] **Step 4: Replace recursive provider-name fallback**

Resolve the ordered chain once per turn, track effective target identities in
a set, skip unavailable/experimental destinations, and invoke the exact model
and endpoint. Retry state is target-scoped. Cancellation exits immediately.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest -q tests/test_structured_fallback.py tests/test_reliability.py tests/test_rate_guard.py tests/test_provider_retry_timeout.py tests/test_ctx_pct_served_provider.py`

Commit: `feat(providers): add structured runtime fallback chain`

---

### Task 5: Structured native tool-call streaming

**Files:**
- Modify: `okami/llm/streaming.py`
- Modify: `okami/runner.py`
- Modify: `okami/llm/providers.py`
- Test: `tests/test_streaming_native_tools.py`
- Test: `tests/test_streaming.py`
- Test: `tests/test_native_tools_e2e.py`

**Interfaces:**
- Consumes: request context, transport registry and existing `Completion`.
- Produces: `StreamEvent`, `ToolCallDelta`, `NativeToolCallAccumulator`.

- [ ] **Step 1: Write accumulator RED tests**

```python
def test_accumulator_concatenates_arguments_by_index():
    acc = NativeToolCallAccumulator()
    acc.feed(ToolCallDelta(0, id="c1", name="read_file", arguments='{"path":'))
    acc.feed(ToolCallDelta(0, arguments='"a.txt"}'))
    assert acc.completed() == [{"id": "c1", "name": "read_file", "arguments": '{"path":"a.txt"}'}]

def test_repeated_name_delta_does_not_duplicate_name():
    acc = NativeToolCallAccumulator()
    acc.feed(ToolCallDelta(0, name="read_file", arguments="{}"))
    acc.feed(ToolCallDelta(0, name="read_file"))
    assert acc.completed()[0]["name"] == "read_file"

def test_incomplete_arguments_are_not_returned():
    acc = NativeToolCallAccumulator()
    acc.feed(ToolCallDelta(0, id="c1", name="write_file", arguments='{"path":"a"'))
    assert acc.completed() == []

def test_tool_argument_deltas_never_reach_on_token():
    visible = []
    result = streaming_generate(None, [], on_token=visible.append,
        _events=iter([StreamEvent(tool_call=ToolCallDelta(0, id="c1", name="read_file",
                                                          arguments='{"path":"secret"}')),
                      StreamEvent(finish_reason="tool_calls")]))
    assert visible == []
    assert result.tool_calls[0]["name"] == "read_file"
```

- [ ] **Step 2: Write integration RED tests**

```python
def complete_read_file_events():
    return iter([
        StreamEvent(tool_call=ToolCallDelta(0, id="c1", name="read_file", arguments='{"path":')),
        StreamEvent(tool_call=ToolCallDelta(0, arguments='"a.txt"}')),
        StreamEvent(finish_reason="tool_calls"),
    ])

def truncated_write_events():
    return iter([
        StreamEvent(tool_call=ToolCallDelta(0, id="c1", name="write_file",
                                            arguments='{"path":"a.txt","content":"cut')),
        StreamEvent(finish_reason="length"),
    ])

def partial_then_error_events():
    yield StreamEvent(text="partial")
    raise RuntimeError("socket closed")

def fake_cfg():
    pc = SimpleNamespace(name="p", model="openai/gpt-4o")
    return SimpleNamespace(provider=lambda name=None: pc)

def test_native_stream_returns_complete_tool_calls():
    comp = streaming_generate(None, [], _events=complete_read_file_events())
    assert comp.finish_reason == "tool_calls"
    assert json.loads(comp.tool_calls[0]["arguments"]) == {"path": "a.txt"}

def test_native_stream_passes_filtered_tools_and_tool_choice(monkeypatch):
    captured = {}
    monkeypatch.setattr(streaming, "stream_messages_events",
                        lambda *a, **kw: (captured.update(kw) or iter([StreamEvent(text="ok")])))
    streaming_generate(fake_cfg(), [], tools=[{"type": "function", "function": {"name": "read_file"}}],
                       tool_choice="required")
    assert captured["tools"][0]["function"]["name"] == "read_file"
    assert captured["tool_choice"] == "required"

def test_native_stream_truncated_args_never_execute_tool(tmp_path):
    comp = streaming_generate(None, [], _events=truncated_write_events())
    task = Harness(lambda messages, schema: comp, Task(goal="write"), tmp_path).run()
    assert not (tmp_path / "a.txt").exists()
    assert task.state is not TaskState.COMPLETE

def test_partial_visible_text_is_not_retried():
    fallback_calls = []
    comp = streaming_generate(None, [], on_token=lambda text: None,
                              _events=partial_then_error_events(),
                              _fallback=lambda: fallback_calls.append(True))
    assert comp.text == "partial"
    assert fallback_calls == []
```

- [ ] **Step 3: Verify RED**

Run: `uv run pytest -q tests/test_streaming_native_tools.py tests/test_streaming.py tests/test_native_tools_e2e.py`

Expected: current text-only stream drops tool deltas and native streaming stays disabled.

- [ ] **Step 4: Implement structured events and accumulator**

```python
@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""

@dataclass(frozen=True, slots=True)
class StreamEvent:
    text: str = ""
    reasoning: str = ""
    tool_call: ToolCallDelta | None = None
    finish_reason: str | None = None
```

The accumulator concatenates only argument fragments. It emits a call only
when `json.loads(arguments)` succeeds with a dictionary. Incomplete arguments
are discarded and reported; they never enter the existing repair path.

- [ ] **Step 5: Enable native streaming in the runner**

Pass filtered `tools`, `tool_choice`, `RequestContext` and `on_token` into the
structured path. Display callbacks receive visible assistant text only.
Non-streaming and forced JSON-text rails remain compatible.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest -q tests/test_streaming_native_tools.py tests/test_streaming.py tests/test_native_tools_e2e.py tests/test_native_message_protocol.py tests/test_malformed_action.py tests/test_json_repair.py`

Commit: `feat(harness): stream native tool calls structurally`

---

### Task 6: Atomic native history, compaction and resume

**Files:**
- Create: `okami/core/harness/native_history.py`
- Modify: `okami/core/harness/loop.py`
- Modify: `okami/memory/compaction.py`
- Modify: `okami/core/harness/resume.py`
- Test: `tests/test_native_message_protocol.py`
- Test: `tests/test_compaction_tool_pairs.py`
- Test: `tests/test_resume_checkpoint.py`

**Interfaces:**
- Produces: `append_native_assistant()`, `append_native_tool_result()`, `native_history_groups()` and `repair_native_history()`.
- Consumes: exact native call IDs and argument strings from `Completion.tool_calls`.

- [ ] **Step 1: Write multi-call protocol RED tests**

```python
def test_multiple_native_results_are_consecutive_role_tool_messages():
    messages = []
    calls = [{"id": "c1", "name": "read_file", "arguments": '{"path":"a"}'},
             {"id": "c2", "name": "list_dir", "arguments": '{}'}]
    append_native_assistant(messages, calls)
    append_native_tool_result(messages, "c1", "A")
    append_native_tool_result(messages, "c2", "B")
    assert [m["role"] for m in messages] == ["assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in messages[1:]] == ["c1", "c2"]

def test_rejected_second_call_gets_matching_tool_result():
    messages = []
    append_native_assistant(messages, [{"id": "c1", "name": "read_file", "arguments": "{}"},
                                       {"id": "c2", "name": "run_shell", "arguments": "{}"}])
    append_native_tool_result(messages, "c1", "ok")
    append_native_tool_result(messages, "c2", "REJECTED: approval denied", ok=False)
    assert messages[-1]["tool_call_id"] == "c2"
    assert "REJECTED" in messages[-1]["content"]

def test_terminal_call_leaves_no_orphan_history():
    messages = []
    append_native_assistant(messages, [{"id": "done", "name": "task_complete",
                                        "arguments": '{"summary":"ok"}'}])
    append_native_tool_result(messages, "done", "ok")
    assert repair_native_history(messages) == messages
```

- [ ] **Step 2: Write compaction/resume RED tests**

```python
@pytest.fixture
def native_group():
    return [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "A"},
        {"role": "tool", "tool_call_id": "c2", "content": "B"},
    ]

@pytest.fixture
def incomplete_native_group(native_group):
    return native_group[:-1]

def test_compact_keeps_complete_assistant_tool_group(native_group):
    compacted, saved = prune_observations([{"role": "system", "content": "s"}, *native_group])
    assert compacted[-3:] == native_group
    assert saved >= 0

def test_compact_drops_whole_incomplete_group(incomplete_native_group):
    repaired = repair_native_history(incomplete_native_group)
    ids = {tc["id"] for m in repaired if m.get("role") == "assistant"
           for tc in m.get("tool_calls", [])}
    results = {m["tool_call_id"] for m in repaired if m.get("role") == "tool"}
    assert ids == results

def test_resume_marks_inflight_call_without_reexecuting_it(tmp_path, incomplete_native_group):
    write_checkpoint(tmp_path, [{"role": "system", "content": "s"},
                                {"role": "user", "content": "u"}, *incomplete_native_group], 100.0)
    messages = load_checkpoint(tmp_path, max_age_s=60, now=101.0)
    assert messages is not None
    assert "interrupted" in messages[-1]["content"].lower()
    assert messages[-1]["role"] == "tool"

def test_low_gain_compaction_guard_remains_bounded(tmp_path):
    harness = Harness(lambda messages, schema: '{"tool":"task_blocked","args":{"reason":"x"}}',
                      Task(goal="x"), tmp_path)
    assert harness._note_compact_gain(100, 95) is False
    assert harness._note_compact_gain(100, 95) is True
```

- [ ] **Step 3: Verify RED**

Run: `uv run pytest -q tests/test_native_message_protocol.py tests/test_compaction_tool_pairs.py tests/test_resume_checkpoint.py`

Expected: the second result in a multi-call native turn is not represented as a matching consecutive `role=tool` group.

- [ ] **Step 4: Implement atomic native groups**

Stage one assistant message with every native call before dispatch. Append one
matching `role=tool` result for success, rejection or error. Compaction treats
the assistant and all results as one unit. Resume marks an incomplete unit as
interrupted and never invokes it automatically.

- [ ] **Step 5: Re-run security invariants**

Run: `uv run pytest -q tests/test_approval_binding.py tests/test_approval_store.py tests/test_malformed_action.py tests/test_json_repair.py tests/test_parallel_tools.py`

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest -q tests/test_native_message_protocol.py tests/test_compaction_tool_pairs.py tests/test_resume_checkpoint.py tests/test_compact_thrash.py`

Commit: `fix(harness): keep native tool history groups atomic`

---

### Task 7: Integration verification and migration report

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Create: `docs/reports/2026-07-11-harness-providers-modernization.md`
- Test: full suite and static gates.

**Interfaces:**
- Consumes all previous task contracts.
- Produces user-facing migration and remaining-work report.

- [ ] **Step 1: Run the focused integration matrix**

Run:

```bash
uv run pytest -q \
  tests/test_request_watchdog.py tests/test_request_cancellation.py \
  tests/test_runtime_target.py tests/test_target_resolver.py \
  tests/test_transport_registry.py tests/test_litellm_compat.py \
  tests/test_structured_fallback.py tests/test_streaming_native_tools.py \
  tests/test_native_message_protocol.py tests/test_compaction_tool_pairs.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check okami tests`

Expected: zero errors.

- [ ] **Step 3: Run the complete suite**

Run: `uv run pytest -q`

Expected: zero failures; baseline skips may remain.

- [ ] **Step 4: Document architecture and migration**

The report must list exact delivered behaviours, compatibility guarantees,
test counts, known transport limitations, deferred gateway/model-picker work,
and the remaining path to remove LiteLLM as a required dependency.

- [ ] **Step 5: Review the complete branch and fix findings**

Create a review package from base `59090f8` through branch HEAD. A fresh
Luna/xhigh reviewer returns both spec-compliance and code-quality verdicts.
Fix every Critical or Important finding and re-run covering tests.

- [ ] **Step 6: Commit**

Commit: `docs: report harness and provider modernization`
