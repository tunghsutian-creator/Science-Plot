"""Define redacted provider and unavailable-context errors."""

from __future__ import annotations


class OpenAIProviderError(RuntimeError):
    """A redacted production-provider transport or protocol failure."""


class _AssistantContextUnavailable(ValueError):
    """The current Veusz selection cannot yet form a provider request."""
