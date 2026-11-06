"""Define redacted provider and unavailable-context errors."""

from __future__ import annotations

from sciplot_core.assistant_provider.provider import AssistantProviderFailure


class OpenAIProviderError(AssistantProviderFailure):
    """A redacted production-provider transport or protocol failure."""


class _AssistantContextUnavailable(ValueError):
    """The current Veusz selection cannot yet form a provider request."""
