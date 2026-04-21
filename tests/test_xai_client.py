"""Tests for :mod:`grok_build_bridge.xai_client`.

The real xAI SDK is never imported or called. Instead, we monkeypatch the
module-level ``Client`` symbol with a ``FakeClient`` that records calls and
can be programmed to raise specific exceptions on demand. ``time.sleep`` is
patched too so the retry waits do not actually block the test run.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from grok_build_bridge import xai_client
from grok_build_bridge.xai_client import (
    ALLOWED_MODELS,
    APIConnectionError,
    BridgeRuntimeError,
    ConfigError,
    RateLimitError,
    RetryConfig,
    ToolExecutionError,
    XAIClient,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    content: str = "ok"


@dataclass
class _FakeChat:
    """One ``chat.create()`` result. Pulls from the parent's shared scripts.

    Scripts live on :class:`_FakeChats` so consecutive retry attempts consume
    a single sequence of outcomes (e.g. fail, fail, succeed), rather than
    each attempt getting a fresh copy of the full script.
    """

    create_kwargs: dict[str, Any]
    _parent: _FakeChats
    appended: list[Any] = field(default_factory=list)

    def append(self, message: Any) -> _FakeChat:
        self.appended.append(message)
        return self

    def stream(self) -> Iterator[tuple[Any, Any]]:
        script = self._parent.next_stream_script
        while script:
            head = script.pop(0)
            if isinstance(head, Exception):
                raise head
            yield head

    def sample(self) -> Any:
        script = self._parent.next_sample_script
        if not script:
            return _FakeResponse(content="sampled-ok")
        head = script.pop(0)
        if isinstance(head, Exception):
            raise head
        return head


@dataclass
class _FakeChats:
    """Tracks every ``chat.create()`` call and holds shared response scripts."""

    created: list[_FakeChat] = field(default_factory=list)
    next_stream_script: list[Any] = field(default_factory=list)
    next_sample_script: list[Any] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeChat:
        chat = _FakeChat(create_kwargs=kwargs, _parent=self)
        self.created.append(chat)
        return chat


@dataclass
class _FakeClient:
    api_key: str
    chat: _FakeChats = field(default_factory=_FakeChats)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Patch ``time.sleep`` so retry backoff never actually blocks the test run.

    Returns the list of recorded sleep durations, letting tests assert the
    backoff policy was obeyed without waiting wall-clock seconds.
    """
    sleeps: list[float] = []
    import time

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(float(seconds))

    monkeypatch.setattr(time, "sleep", _fake_sleep)
    return sleeps


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """Install a fake xAI SDK and return its single backing ``_FakeClient``.

    The patched factory always returns the **same** ``_FakeClient`` instance,
    so every ``XAIClient(...)`` constructed in a test sees the same chat
    recorder. Tests that need a custom factory (e.g. to observe the api_key
    argument) monkeypatch ``xai_client.Client`` themselves.
    """
    sdk = _FakeClient(api_key="unit-test-key")

    def _factory(api_key: str) -> _FakeClient:
        sdk.api_key = api_key
        return sdk

    monkeypatch.setattr(xai_client, "Client", _factory)
    monkeypatch.setenv("XAI_API_KEY", "unit-test-key")
    return sdk


@pytest.fixture
def fast_client(fake_sdk: _FakeClient) -> XAIClient:
    """Return an XAIClient with zero-wait retries for count-only assertions."""
    return XAIClient(
        retry_config=RetryConfig(
            max_attempts=3, wait_multiplier=0.0, wait_min=0.0, wait_max=0.0
        ),
    )


# ---------------------------------------------------------------------------
# Construction / config
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(ConfigError) as excinfo:
        XAIClient()
    assert "missing xAI API key" in excinfo.value.message
    assert excinfo.value.suggestion is not None


def test_env_api_key_is_picked_up(fake_sdk: _FakeClient) -> None:
    assert fake_sdk.api_key == "unit-test-key"


def test_explicit_api_key_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    holder: dict[str, _FakeClient] = {}

    def _factory(api_key: str) -> _FakeClient:
        client = _FakeClient(api_key=api_key)
        holder["client"] = client
        return client

    monkeypatch.setattr(xai_client, "Client", _factory)
    monkeypatch.setenv("XAI_API_KEY", "env-key")
    XAIClient(api_key="explicit-key")
    assert holder["client"].api_key == "explicit-key"


def test_unknown_model_rejected_before_any_call(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    with pytest.raises(ConfigError) as excinfo:
        fast_client.single_call("grok-not-a-thing", prompt="hi")
    assert "grok-not-a-thing" in excinfo.value.message
    assert fake_sdk.chat.created == []


def test_allowed_models_match_schema() -> None:
    # Pinned — keep in lockstep with bridge.schema.json::agent.model.
    assert ALLOWED_MODELS == {"grok-4.20-0309", "grok-4.20-multi-agent-0309"}


# ---------------------------------------------------------------------------
# Streaming pass-through
# ---------------------------------------------------------------------------


def test_stream_chat_yields_tuples_and_passes_options(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_stream_script = [
        (_FakeResponse(content="partial"), "chunk-1"),
        (_FakeResponse(content="partial+final"), "chunk-2"),
    ]

    chunks = list(
        fast_client.stream_chat(
            model="grok-4.20-0309",
            messages=[
                {"role": "system", "content": "you are a bot"},
                {"role": "user", "content": "hi"},
            ],
            reasoning_effort="high",
            include_verbose_streaming=True,
            use_encrypted_content=True,
            max_tokens=1234,
        )
    )

    assert [c[1] for c in chunks] == ["chunk-1", "chunk-2"]

    created = fake_sdk.chat.created
    assert len(created) == 1
    kwargs = created[0].create_kwargs
    assert kwargs["model"] == "grok-4.20-0309"
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["max_tokens"] == 1234
    assert kwargs["use_encrypted_content"] is True
    assert kwargs["include"] == ["verbose_streaming"]
    assert len(created[0].appended) == 2  # system + user


def test_stream_chat_include_none_when_flag_off(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_stream_script = [
        (_FakeResponse(content="x"), "only-chunk"),
    ]
    list(
        fast_client.stream_chat(
            model="grok-4.20-0309",
            messages=[{"role": "user", "content": "hi"}],
        )
    )
    assert fake_sdk.chat.created[0].create_kwargs["include"] is None


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_rate_limit_retried_three_times_then_raises(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        RateLimitError("quota"),
        RateLimitError("quota"),
        RateLimitError("quota"),
    ]

    with pytest.raises(BridgeRuntimeError) as excinfo:
        fast_client.single_call(model="grok-4.20-0309", prompt="hi")

    assert len(fake_sdk.chat.created) == 3
    assert "failed after 3 attempts" in excinfo.value.message
    assert isinstance(excinfo.value.__cause__, RateLimitError)


def test_recovers_after_two_rate_limits(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        RateLimitError("quota-1"),
        RateLimitError("quota-2"),
        _FakeResponse(content="finally!"),
    ]
    result = fast_client.single_call(model="grok-4.20-0309", prompt="hi")
    assert result == "finally!"
    assert len(fake_sdk.chat.created) == 3


def test_backoff_sleeps_between_attempts(
    fake_sdk: _FakeClient, no_sleep: list[float]
) -> None:
    fake_sdk.chat.next_sample_script = [
        RateLimitError("q"),
        RateLimitError("q"),
        RateLimitError("q"),
    ]
    # Production-ish config so we can assert the wait respected the min/max.
    client = XAIClient(
        retry_config=RetryConfig(
            max_attempts=3, wait_multiplier=1.0, wait_min=2.0, wait_max=16.0
        ),
    )
    with pytest.raises(BridgeRuntimeError):
        client.single_call(model="grok-4.20-0309", prompt="hi")

    # 3 attempts → 2 sleeps in between.
    assert len(no_sleep) == 2
    assert all(2.0 <= s <= 16.0 for s in no_sleep)


def test_api_connection_error_is_retryable(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        APIConnectionError("dns"),
        _FakeResponse(content="recovered"),
    ]
    assert fast_client.single_call("grok-4.20-0309", prompt="hi") == "recovered"


def test_httpx_timeout_is_retryable(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        httpx.ReadTimeout("slow"),
        _FakeResponse(content="done"),
    ]
    assert fast_client.single_call("grok-4.20-0309", prompt="hi") == "done"


def test_unexpected_exception_not_retried(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        ValueError("unexpected"),
        _FakeResponse(content="not reached"),
    ]
    with pytest.raises(ValueError, match="unexpected"):
        fast_client.single_call("grok-4.20-0309", prompt="hi")
    assert len(fake_sdk.chat.created) == 1


# ---------------------------------------------------------------------------
# Tool execution fallback
# ---------------------------------------------------------------------------


def test_tool_execution_error_triggers_tools_disabled_retry(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        ToolExecutionError("bad tool"),
        _FakeResponse(content="works without tools"),
    ]

    result = fast_client.single_call(
        "grok-4.20-0309",
        prompt="hi",
        tools=[{"name": "web_search"}],
    )
    assert result == "works without tools"

    created = fake_sdk.chat.created
    assert len(created) == 2
    assert created[0].create_kwargs["tools"] == [{"name": "web_search"}]
    assert created[1].create_kwargs["tools"] is None


def test_tool_execution_error_twice_surfaces_as_bridge_runtime_error(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [
        ToolExecutionError("first"),
        ToolExecutionError("second"),
    ]
    with pytest.raises(BridgeRuntimeError) as excinfo:
        fast_client.single_call(
            "grok-4.20-0309",
            prompt="hi",
            tools=[{"name": "web_search"}],
        )
    assert "tool execution failed twice" in excinfo.value.message
    assert isinstance(excinfo.value.__cause__, ToolExecutionError)


# ---------------------------------------------------------------------------
# Message conversion and kwargs
# ---------------------------------------------------------------------------


def test_unknown_role_raises(fake_sdk: _FakeClient, fast_client: XAIClient) -> None:
    with pytest.raises(BridgeRuntimeError, match="unknown message role"):
        list(
            fast_client.stream_chat(
                "grok-4.20-0309",
                messages=[{"role": "banana", "content": "nope"}],
            )
        )


def test_missing_role_or_content_raises(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    with pytest.raises(BridgeRuntimeError, match="missing role/content"):
        list(
            fast_client.stream_chat(
                "grok-4.20-0309",
                messages=[{"content": "no role"}],
            )
        )


def test_single_call_injects_system_prompt(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    fake_sdk.chat.next_sample_script = [_FakeResponse(content="hi")]
    fast_client.single_call(
        "grok-4.20-0309",
        prompt="hello",
        system="you are terse",
    )
    appended = fake_sdk.chat.created[0].appended
    assert len(appended) == 2  # system + user


def test_single_call_rejects_unknown_kwargs(
    fake_sdk: _FakeClient, fast_client: XAIClient
) -> None:
    with pytest.raises(BridgeRuntimeError, match="unexpected keyword"):
        fast_client.single_call("grok-4.20-0309", prompt="hi", wat=1)
