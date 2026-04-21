"""Thin async wrapper around the official ``xai-sdk`` Grok client.

Adds retry/backoff via ``tenacity``, structured logging, and a narrow
surface focused on the calls the builder and safety layers need.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GrokMessage:
    """Single chat message sent to or received from the Grok API."""

    role: str
    content: str


class XAIClient:
    """High-level wrapper over the xAI Grok SDK."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        """Build a client. If ``api_key`` is ``None``, read ``XAI_API_KEY`` from the env."""
        raise NotImplementedError("filled in session 2")

    async def complete(
        self,
        messages: list[GrokMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat completion request and return the assistant text."""
        raise NotImplementedError("filled in session 2")

    async def close(self) -> None:
        """Release any underlying HTTP resources."""
        raise NotImplementedError("filled in session 2")
