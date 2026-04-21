"""Production-grade wrapper around the official ``xai-sdk`` Grok client.

Provides:

* A single :class:`XAIClient` facade with ``stream_chat`` and ``single_call``.
* A local exception hierarchy rooted at :class:`BridgeRuntimeError` so every
  downstream module can ``except BridgeRuntimeError:`` once and be done.
* Tenacity-powered retries with exponential backoff on the transient error
  classes xAI commonly emits.
* Dedicated fallback for ``ToolExecutionError``: one retry with tools
  disabled, then surface.
* Rich console warnings on each retry so operators see what is happening
  in real time without turning on DEBUG logging.

The module never issues real network calls unless ``__init__`` is given a
live ``XAI_API_KEY``; tests inject fakes by monkeypatching the module-level
:data:`Client` symbol.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypeVar

import httpx
from rich.text import Text
from tenacity import (
    RetryCallState,
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from xai_sdk import Client
from xai_sdk.chat import assistant as _assistant
from xai_sdk.chat import developer as _developer
from xai_sdk.chat import system as _system
from xai_sdk.chat import user as _user

from grok_build_bridge._console import console, warn

T = TypeVar("T")

# Kept in lockstep with ``agent.model`` in ``bridge.schema.json``. Duplicated
# here (rather than parsed from the schema) so importing the client does not
# pull the parser transitively, and so unknown models can be rejected before
# any network round-trip.
ALLOWED_MODELS: Final[frozenset[str]] = frozenset(
    {
        "grok-4.20-0309",
        "grok-4.20-multi-agent-0309",
    }
)

_MAX_ATTEMPTS: Final[int] = 3


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class BridgeRuntimeError(RuntimeError):
    """Root of every recoverable/unrecoverable error the bridge raises.

    Carries an optional ``suggestion`` string so the CLI can render a
    single actionable next step instead of a bare stacktrace.
    """

    def __init__(self, message: str, *, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.suggestion: str | None = suggestion

    def __str__(self) -> str:
        if self.suggestion:
            return f"{self.message}\n→ {self.suggestion}"
        return self.message


class ConfigError(BridgeRuntimeError):
    """Raised when the client cannot be constructed (missing key, bad model)."""


class RateLimitError(BridgeRuntimeError):
    """429 / quota-exhausted responses from xAI. Retryable."""


class APIConnectionError(BridgeRuntimeError):
    """Transport-layer failures (DNS, TCP reset, TLS). Retryable."""


class ToolExecutionError(BridgeRuntimeError):
    """The model invoked a tool and the tool raised.

    Handled outside the normal retry predicate: we retry once with tools
    disabled, then surface. That rule lives at the method level in
    :class:`XAIClient` so the retry wrapper stays free of tool-specific
    knowledge.
    """


# Attempt to import the real SDK's ToolExecutionError so we can normalise
# whatever it raises into ``ToolExecutionError`` above. The SDK does not
# expose one today (checked against xai-sdk 1.11), so we fall back to a
# never-matching sentinel class that ``isinstance`` will cleanly ignore.
try:  # pragma: no cover — depends on installed SDK version
    from xai_sdk.errors import (
        ToolExecutionError as _SdkToolExecutionError,  # type: ignore[import-not-found]
    )
except ImportError:  # pragma: no cover

    class _SdkToolExecutionError(Exception):
        """Sentinel used when the SDK does not export a ToolExecutionError."""


# ---------------------------------------------------------------------------
# Config and helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class RetryConfig:
    """Tenacity retry knobs, exposed for tests and advanced callers.

    Defaults match the specification: three attempts total, exponential
    backoff clamped to [2s, 16s]. ``frozen=True`` so an instance cannot be
    mutated by one call and affect the next.
    """

    max_attempts: int = _MAX_ATTEMPTS
    wait_multiplier: float = 1.0
    wait_min: float = 2.0
    wait_max: float = 16.0


# Module-level singleton so ``_run_with_retries`` can name it as a default
# argument without tripping ruff's B008 (no function call in defaults).
_DEFAULT_RETRY_CONFIG: Final[RetryConfig] = RetryConfig()


_ROLE_CONSTRUCTORS: Final[dict[str, Callable[..., Any]]] = {
    "user": _user,
    "system": _system,
    "assistant": _assistant,
    "developer": _developer,
}


def _to_sdk_messages(messages: Sequence[dict[str, Any]]) -> list[Any]:
    """Convert plain ``{"role": ..., "content": ...}`` dicts to SDK messages.

    Args:
        messages: Sequence of role/content dicts.

    Returns:
        List of ``xai_sdk.chat`` ``Message`` objects ready for ``chat.append``.

    Raises:
        BridgeRuntimeError: If a message is missing ``role``/``content`` or
            carries an unknown role.
    """
    out: list[Any] = []
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise BridgeRuntimeError(f"message #{idx} is not a dict: {msg!r}")
        role = msg.get("role")
        content = msg.get("content")
        if role is None or content is None:
            raise BridgeRuntimeError(
                f"message #{idx} missing role/content: {msg!r}",
                suggestion="Each message must be {'role': ..., 'content': ...}.",
            )
        ctor = _ROLE_CONSTRUCTORS.get(role)
        if ctor is None:
            raise BridgeRuntimeError(
                f"unknown message role: {role!r}",
                suggestion=f"Use one of {sorted(_ROLE_CONSTRUCTORS)}.",
            )
        out.append(ctor(content))
    return out


def _validate_model(model: str) -> None:
    """Reject models outside the pinned enum before any network I/O."""
    if model not in ALLOWED_MODELS:
        raise ConfigError(
            f"unknown model {model!r}",
            suggestion=f"Expected one of {sorted(ALLOWED_MODELS)}.",
        )


def _warn_before_sleep(retry_state: RetryCallState) -> None:
    """Tenacity ``before_sleep`` hook that prints a coloured retry line."""
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None else None
    wait_seconds = (
        retry_state.next_action.sleep
        if retry_state.next_action is not None
        else 0.0
    )
    next_attempt = retry_state.attempt_number + 1
    exc_name = type(exc).__name__ if exc is not None else "Exception"
    # Emoji allow-listed in the project style guide.
    console.print(
        Text(
            f"⚠️  Retry {next_attempt}/{_MAX_ATTEMPTS} after {exc_name} "
            f"(waited {wait_seconds:.0f}s)...",
            style="yellow",
        )
    )


def _run_with_retries(
    fn: Callable[[], T],
    *,
    config: RetryConfig = _DEFAULT_RETRY_CONFIG,
) -> T:
    """Execute ``fn`` under the standard retry policy.

    Args:
        fn: Zero-argument callable. Keeping the signature closed lets callers
            bind arguments via ``lambda`` or ``functools.partial`` and keeps
            the retry wrapper reusable for both streaming and non-streaming
            paths.
        config: Retry knobs. Default matches the production policy.

    Returns:
        Whatever ``fn`` returns.

    Raises:
        BridgeRuntimeError: When every attempt has failed with a retryable
            exception. The underlying exception is chained via ``__cause__``.
        Exception: Non-retryable exceptions (including
            :class:`ToolExecutionError`) propagate unchanged.
    """
    retryer = Retrying(
        stop=stop_after_attempt(config.max_attempts),
        wait=wait_exponential(
            multiplier=config.wait_multiplier,
            min=config.wait_min,
            max=config.wait_max,
        ),
        retry=retry_if_exception_type(
            (RateLimitError, APIConnectionError, httpx.TimeoutException)
        ),
        before_sleep=_warn_before_sleep,
        reraise=False,
    )
    try:
        return retryer(fn)
    except RetryError as exc:
        last = exc.last_attempt.exception() if exc.last_attempt else exc
        raise BridgeRuntimeError(
            f"xAI call failed after {config.max_attempts} attempts: {last}",
            suggestion=(
                "Verify XAI_API_KEY, check rate limits at https://console.x.ai, "
                "or retry later."
            ),
        ) from last


# ---------------------------------------------------------------------------
# Public client
# ---------------------------------------------------------------------------


class XAIClient:
    """Thin, retry-aware wrapper over :class:`xai_sdk.Client`.

    Args:
        api_key: xAI API key. If ``None``, read from ``XAI_API_KEY``.
        retry_config: Optional override for the retry policy.
        client_factory: Optional callable used instead of :class:`xai_sdk.Client`.
            Prefer monkeypatching the module-level ``Client`` name in tests;
            this hook is provided for callers that want to inject a mock
            without touching module globals.

    Raises:
        ConfigError: If no API key can be resolved.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        retry_config: RetryConfig | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        resolved = api_key if api_key is not None else os.environ.get("XAI_API_KEY")
        if not resolved:
            raise ConfigError(
                "missing xAI API key",
                suggestion=(
                    "Set XAI_API_KEY in your environment or pass api_key=... "
                    "to XAIClient()."
                ),
            )
        self._api_key: str = resolved
        self._retry_config: RetryConfig = retry_config or RetryConfig()
        factory: Callable[..., Any] = client_factory if client_factory is not None else Client
        self._client: Any = factory(api_key=resolved)

    # -- internal -----------------------------------------------------------

    def _build_chat(
        self,
        *,
        model: str,
        reasoning_effort: str,
        tools: Sequence[Any] | None,
        max_tokens: int,
        include_verbose_streaming: bool,
        use_encrypted_content: bool,
    ) -> Any:
        """Create an SDK ``Chat`` object with the requested settings."""
        include = ["verbose_streaming"] if include_verbose_streaming else None
        return self._client.chat.create(
            model=model,
            reasoning_effort=reasoning_effort,
            tools=tools,
            max_tokens=max_tokens,
            include=include,
            use_encrypted_content=use_encrypted_content,
        )

    def _prime_chat(self, chat: Any, messages: Sequence[dict[str, Any]]) -> Any:
        """Append every caller-provided message onto an SDK ``Chat``."""
        for msg in _to_sdk_messages(messages):
            chat.append(msg)
        return chat

    # -- public -------------------------------------------------------------

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        reasoning_effort: str = "medium",
        include_verbose_streaming: bool = False,
        use_encrypted_content: bool = False,
        max_tokens: int = 8000,
    ) -> Iterator[tuple[Any, Any]]:
        """Stream a chat completion, yielding ``(response, chunk)`` tuples.

        Args:
            model: Grok model id. Must be in :data:`ALLOWED_MODELS`.
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            tools: Optional sequence of SDK ``Tool`` objects.
            reasoning_effort: One of ``low``, ``medium``, ``high``, ``xhigh``.
            include_verbose_streaming: When True, requests the
                ``verbose_streaming`` include option from xAI.
            use_encrypted_content: Forwarded to the SDK's
                ``use_encrypted_content`` parameter.
            max_tokens: Per-call ceiling on generated tokens.

        Yields:
            ``(response, chunk)`` tuples exactly as produced by
            ``xai_sdk.chat.Chat.stream``.

        Raises:
            ConfigError: If ``model`` is not in :data:`ALLOWED_MODELS`.
            BridgeRuntimeError: On retry exhaustion or an unhandled tool
                execution error.
        """
        _validate_model(model)

        def _start(current_tools: Sequence[Any] | None) -> Iterator[tuple[Any, Any]]:
            chat = self._build_chat(
                model=model,
                reasoning_effort=reasoning_effort,
                tools=current_tools,
                max_tokens=max_tokens,
                include_verbose_streaming=include_verbose_streaming,
                use_encrypted_content=use_encrypted_content,
            )
            self._prime_chat(chat, messages)
            return chat.stream()

        try:
            iterator = _run_with_retries(
                lambda: _start(tools),
                config=self._retry_config,
            )
        except (ToolExecutionError, _SdkToolExecutionError) as exc:
            warn(
                "⚠️  ToolExecutionError — retrying once with tools disabled "
                "before surfacing."
            )
            try:
                iterator = _run_with_retries(
                    lambda: _start(None),
                    config=self._retry_config,
                )
            except (ToolExecutionError, _SdkToolExecutionError) as second:
                raise BridgeRuntimeError(
                    f"tool execution failed twice: {second}",
                    suggestion=(
                        "Inspect the tool implementation or remove it from "
                        "the bridge config's build.required_tools."
                    ),
                ) from second
            except BridgeRuntimeError:
                raise
            # Preserve original cause for debuggability.
            del exc

        yield from iterator

    def single_call(self, model: str, prompt: str, **kwargs: Any) -> str:
        """Issue a non-streaming completion and return the assistant text.

        Args:
            model: Grok model id.
            prompt: User message contents.
            **kwargs: Forwarded to :meth:`_build_chat` / the SDK. Recognised
                keys: ``reasoning_effort``, ``tools``, ``max_tokens``,
                ``use_encrypted_content``, ``system``.

        Returns:
            The assistant's ``content`` string.

        Raises:
            ConfigError: If ``model`` is not in :data:`ALLOWED_MODELS`.
            BridgeRuntimeError: On retry exhaustion or unhandled tool errors.
        """
        _validate_model(model)

        system_prompt: str | None = kwargs.pop("system", None)
        reasoning_effort: str = kwargs.pop("reasoning_effort", "medium")
        tools: Sequence[Any] | None = kwargs.pop("tools", None)
        max_tokens: int = kwargs.pop("max_tokens", 8000)
        use_encrypted_content: bool = kwargs.pop("use_encrypted_content", False)
        if kwargs:
            raise BridgeRuntimeError(
                f"unexpected keyword arguments: {sorted(kwargs)}",
                suggestion="Check the single_call signature in xai_client.py.",
            )

        messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        def _sample(current_tools: Sequence[Any] | None) -> str:
            chat = self._build_chat(
                model=model,
                reasoning_effort=reasoning_effort,
                tools=current_tools,
                max_tokens=max_tokens,
                include_verbose_streaming=False,
                use_encrypted_content=use_encrypted_content,
            )
            self._prime_chat(chat, messages)
            response = chat.sample()
            return str(response.content)

        try:
            return _run_with_retries(
                lambda: _sample(tools),
                config=self._retry_config,
            )
        except (ToolExecutionError, _SdkToolExecutionError):
            warn(
                "⚠️  ToolExecutionError — retrying once with tools disabled "
                "before surfacing."
            )
            try:
                return _run_with_retries(
                    lambda: _sample(None),
                    config=self._retry_config,
                )
            except (ToolExecutionError, _SdkToolExecutionError) as second:
                raise BridgeRuntimeError(
                    f"tool execution failed twice: {second}",
                    suggestion=(
                        "Inspect the tool implementation or remove it from "
                        "the bridge config's build.required_tools."
                    ),
                ) from second
