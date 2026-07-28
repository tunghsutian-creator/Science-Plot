"""Construct an OpenAI provider from environment configuration."""

from __future__ import annotations

from typing import Mapping

from sciplot_core.openai_provider.config import (
    OpenAIResponsesConfig,
)

from sciplot_core.openai_provider.provider import (
    OpenAIResponsesProvider,
)


def load_openai_provider_from_environment(
    environ: Mapping[str, str] | None = None,
) -> OpenAIResponsesProvider | None:
    config = OpenAIResponsesConfig.from_environment(environ)
    return OpenAIResponsesProvider(config) if config is not None else None
