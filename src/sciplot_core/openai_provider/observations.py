"""Observe bounded response metadata during one call, including failed calls."""

from __future__ import annotations

import json
from typing import Any

from sciplot_core.assistant_provider.facts import ProviderFacts, _fact_text
from sciplot_core.openai_provider.errors import OpenAIProviderError


class _ResponseFacts:
    def __init__(self, secret: str) -> None:
        self.value: ProviderFacts | None = None
        self._secret = secret

    def _identifier(self, value: Any) -> str | None:
        if not isinstance(value, str) or (self._secret and self._secret in value):
            return None
        try:
            return _fact_text(value)
        except ValueError:
            return None

    def observe(self, response: object, *, terminal: bool = False) -> None:
        if not isinstance(response, dict):
            return
        previous = self.value
        identity = self._identifier(response.get("id"))
        model = self._identifier(response.get("model"))
        if previous is not None:
            if identity is not None and previous.response_id not in {None, identity}:
                raise OpenAIProviderError("OpenAI response identity changed during one stream.")
            identity = identity or previous.response_id
            model = model or previous.model
        status = self._identifier(response.get("status")) if terminal else None
        usage = response.get("usage") if terminal else None
        usage_status = ("reported" if usage is not None else "not_reported") if terminal else "not_observed"
        try:
            observed = ProviderFacts.from_values(
                response_id=identity, model=model, usage=usage, usage_status=usage_status,
                terminal_status=status,
            )
            if (self._secret and observed.usage_json is not None
                    and json.dumps(self._secret)[1:-1] in observed.usage_json):
                raise ValueError("Provider usage contains sensitive metadata.")
            self.value = observed
        except (ValueError, TypeError):
            # Optional counter metadata cannot authorize or veto a proposal.
            # Retain the invalid observation, never its untrusted raw content.
            self.value = ProviderFacts.from_values(
                response_id=identity, model=model, usage_status="invalid", terminal_status=status)
