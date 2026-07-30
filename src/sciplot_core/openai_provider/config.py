"""Load and validate Responses API provider configuration."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

from sciplot_core.openai_provider.contracts import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_BASE_URL,
    OPENAI_REASONING_EFFORTS,
)

from sciplot_core.openai_provider.validation import (
    _required_text,
    _is_loopback,
)


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    api_key: str = field(repr=False)
    model: str = DEFAULT_OPENAI_MODEL
    base_url: str = DEFAULT_OPENAI_BASE_URL
    reasoning_effort: str = "medium"
    max_output_tokens: int = 2400
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        key = _required_text(self.api_key, "OpenAI API key", maximum=8192)
        if "\r" in key or "\n" in key:
            raise ValueError("OpenAI API key must not contain line breaks.")
        object.__setattr__(self, "api_key", key)
        model = _required_text(self.model, "OpenAI model", maximum=200)
        if any(character.isspace() for character in model):
            raise ValueError("OpenAI model must not contain whitespace.")
        object.__setattr__(self, "model", model)
        base_url = _required_text(
            self.base_url,
            "OpenAI base URL",
            maximum=2048,
        ).rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenAI base URL must be an absolute HTTP(S) URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "OpenAI base URL must not contain credentials, query, or fragment."
            )
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("OpenAI base URL has an invalid port.") from exc
        if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
            raise ValueError(
                "OpenAI base URL must use HTTPS except for loopback protocol tests."
            )
        if parsed.path.rstrip("/").endswith("/responses"):
            raise ValueError(
                "OpenAI base URL must name the API root, not the responses endpoint."
            )
        object.__setattr__(self, "base_url", base_url)
        effort = _required_text(
            self.reasoning_effort,
            "OpenAI reasoning effort",
            maximum=16,
        ).casefold()
        if effort not in OPENAI_REASONING_EFFORTS:
            raise ValueError(
                "OpenAI reasoning effort must be one of: "
                f"{', '.join(sorted(OPENAI_REASONING_EFFORTS))}."
            )
        object.__setattr__(self, "reasoning_effort", effort)
        if isinstance(self.max_output_tokens, bool) or not isinstance(
            self.max_output_tokens, int
        ):
            raise ValueError("OpenAI max output tokens must be an integer.")
        if not 256 <= self.max_output_tokens <= 32_000:
            raise ValueError("OpenAI max output tokens must be between 256 and 32000.")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ValueError("OpenAI timeout must be numeric.")
        timeout = float(self.timeout_seconds)
        if not math.isfinite(timeout) or not 1.0 <= timeout <= 300.0:
            raise ValueError("OpenAI timeout must be between 1 and 300 seconds.")
        object.__setattr__(self, "timeout_seconds", timeout)

    @property
    def endpoint(self) -> tuple[str, str, int | None, str]:
        parsed = urlsplit(self.base_url)
        base_path = parsed.path.rstrip("/")
        path = f"{base_path}/responses" if base_path else "/responses"
        return parsed.scheme, str(parsed.hostname), parsed.port, path

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> OpenAIResponsesConfig | None:
        values = os.environ if environ is None else environ
        key = str(
            values.get("SCIPLOT_OPENAI_API_KEY") or values.get("OPENAI_API_KEY") or ""
        ).strip()
        if not key:
            return None
        model = str(values.get("SCIPLOT_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()
        base_url = str(
            values.get("SCIPLOT_OPENAI_BASE_URL")
            or values.get("OPENAI_BASE_URL")
            or DEFAULT_OPENAI_BASE_URL
        ).strip()
        effort = str(values.get("SCIPLOT_OPENAI_REASONING_EFFORT") or "medium").strip()
        try:
            max_tokens = int(
                str(values.get("SCIPLOT_OPENAI_MAX_OUTPUT_TOKENS") or "2400")
            )
        except ValueError as exc:
            raise ValueError(
                "SCIPLOT_OPENAI_MAX_OUTPUT_TOKENS must be an integer."
            ) from exc
        try:
            timeout = float(str(values.get("SCIPLOT_OPENAI_TIMEOUT_SECONDS") or "90"))
        except ValueError as exc:
            raise ValueError("SCIPLOT_OPENAI_TIMEOUT_SECONDS must be numeric.") from exc
        return cls(
            api_key=key,
            model=model,
            base_url=base_url,
            reasoning_effort=effort,
            max_output_tokens=max_tokens,
            timeout_seconds=timeout,
        )
