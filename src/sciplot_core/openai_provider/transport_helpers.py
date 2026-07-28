"""Represent and decode bounded Responses transport results."""

from __future__ import annotations

import http.client
from dataclasses import dataclass

from sciplot_core.openai_provider.validation import (
    _redact,
)


@dataclass(frozen=True)
class _StreamResult:
    text: str = ""
    refusal: str | None = None
    incomplete_reason: str | None = None


def _error_message(payload: object, *, status: int, secret: str) -> str:
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            raw_message = error.get("message")
            raw_code = error.get("code") or error.get("type")
            if isinstance(raw_message, str):
                message = raw_message
            if isinstance(raw_code, str) and raw_code:
                message = f"{raw_code}: {message}" if message else raw_code
    safe = _redact(message, secrets=(secret,)) if message else ""
    suffix = f": {safe}" if safe else "."
    return f"OpenAI Responses API returned HTTP {status}{suffix}"


def _response_content(response: object) -> tuple[str, str | None]:
    if not isinstance(response, dict):
        return "", None
    texts: list[str] = []
    refusal: str | None = None
    output = response.get("output")
    if not isinstance(output, list):
        return "", None
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "output_text" and isinstance(part.get("text"), str):
                texts.append(str(part["text"]))
            elif part_type == "refusal" and isinstance(part.get("refusal"), str):
                refusal = str(part["refusal"])
    return "".join(texts), refusal


def _connection(
    scheme: str,
    host: str,
    port: int | None,
    timeout: float,
) -> http.client.HTTPConnection:
    connection_class = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    return connection_class(host, port=port, timeout=timeout)
