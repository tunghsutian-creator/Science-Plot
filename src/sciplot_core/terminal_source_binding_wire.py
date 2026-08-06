"""Parse and consume the private worker transport for terminal-source bindings."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.terminal_source_binding import (
    MaterializedTerminalSourceBinding,
    SealedTerminalSourceBinding,
    SourceArtifactBinding,
    TERMINAL_SOURCE_BINDING_KIND,
    TERMINAL_SOURCE_BINDING_VERSION,
    TerminalSourceBindingError,
)


TERMINAL_SOURCE_BINDING_ENV = "SCIPLOT_INTERNAL_TERMINAL_SOURCE_BINDING"
_CONTRACT_MISMATCH = "terminal_source_binding_contract_mismatch"
_REQUEST_MISMATCH = "terminal_source_binding_request_mismatch"
_PAYLOAD_FIELDS = {
    "kind",
    "version",
    "task_key",
    "rule_id",
    "template",
    "x_metric",
    "y_metric",
    "raw_sources",
    "prepared_source",
    "terminal_source",
    "sample_order",
    "point_counts",
    "request",
}


def _fail(reason_code: str, message: str) -> NoReturn:
    raise TerminalSourceBindingError(reason_code, message)


def sealed_terminal_source_binding_from_payload(
    value: object,
) -> SealedTerminalSourceBinding:
    if not isinstance(value, dict) or set(value) != _PAYLOAD_FIELDS:
        _fail(
            _CONTRACT_MISMATCH, "Internal terminal-source binding field set is invalid."
        )
    if (
        value.get("kind") != TERMINAL_SOURCE_BINDING_KIND
        or type(value.get("version")) is not int
        or value.get("version") != TERMINAL_SOURCE_BINDING_VERSION
    ):
        _fail(
            _CONTRACT_MISMATCH,
            "Internal terminal-source binding kind or version is unsupported.",
        )
    raw_values = value.get("raw_sources")
    samples = value.get("sample_order")
    counts = value.get("point_counts")
    if not (
        isinstance(raw_values, list)
        and isinstance(samples, list)
        and isinstance(counts, list)
    ):
        _fail(
            _CONTRACT_MISMATCH,
            "Internal terminal-source binding inventories are invalid.",
        )
    if any(
        not isinstance(item, dict) or set(item) != {"sample", "count"}
        for item in counts
    ):
        _fail(_CONTRACT_MISMATCH, "Internal terminal point-count record is invalid.")
    materialized = MaterializedTerminalSourceBinding(
        task_key=value.get("task_key"),
        rule_id=value.get("rule_id"),
        template=value.get("template"),
        x_metric=value.get("x_metric"),
        y_metric=value.get("y_metric"),
        raw_sources=tuple(
            SourceArtifactBinding.from_payload(item, label="Raw source")
            for item in raw_values
        ),
        prepared_source=SourceArtifactBinding.from_payload(
            value.get("prepared_source"), label="Prepared source"
        ),
        terminal_source=SourceArtifactBinding.from_payload(
            value.get("terminal_source"), label="Terminal source"
        ),
        sample_order=tuple(samples),
        point_counts=tuple((item.get("sample"), item.get("count")) for item in counts),
    )
    return SealedTerminalSourceBinding(
        materialized=materialized,
        request=SourceArtifactBinding.from_payload(
            value.get("request"), label="Terminal worker request"
        ),
    )


def consume_terminal_source_binding_environment(
    request_path: Path,
    request: Mapping[str, Any] | None = None,
) -> SealedTerminalSourceBinding | None:
    encoded = os.environ.pop(TERMINAL_SOURCE_BINDING_ENV, None)
    if encoded is None:
        return None
    try:
        payload = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise TerminalSourceBindingError(
            _CONTRACT_MISMATCH, "Internal terminal-source binding is not valid JSON."
        ) from exc
    if request is None:
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TerminalSourceBindingError(
                _REQUEST_MISMATCH, "Bound terminal worker request could not be read."
            ) from exc
    if not isinstance(request, dict):
        _fail(_REQUEST_MISMATCH, "Bound terminal worker request is not an object.")
    binding = sealed_terminal_source_binding_from_payload(payload)
    binding.validate_request(request_path, request)
    return binding


__all__ = [
    "TERMINAL_SOURCE_BINDING_ENV",
    "consume_terminal_source_binding_environment",
    "sealed_terminal_source_binding_from_payload",
]
