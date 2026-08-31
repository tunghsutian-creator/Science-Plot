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
TERMINAL_SOURCE_PREPARED_ENV = "SCIPLOT_INTERNAL_TERMINAL_SOURCE_PREPARED"
_CONTRACT_MISMATCH = "terminal_source_binding_contract_mismatch"
_REQUEST_MISMATCH = "terminal_source_binding_request_mismatch"
_PAYLOAD_FIELDS = frozenset(
    {
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
)


def _fail(reason_code: str, message: str) -> NoReturn:
    raise TerminalSourceBindingError(reason_code, message)


def _mapping_with_fields(
    value: object,
    *,
    fields: frozenset[str],
    message: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail(_CONTRACT_MISMATCH, message)
    payload: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            _fail(_CONTRACT_MISMATCH, message)
        payload[key] = item
    if set(payload) != fields:
        _fail(_CONTRACT_MISMATCH, message)
    return payload


def _text(value: object, *, message: str) -> str:
    if not isinstance(value, str):
        _fail(_CONTRACT_MISMATCH, message)
    return value


def _integer(value: object, *, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(_CONTRACT_MISMATCH, message)
    return value


def _version(value: object) -> int:
    if type(value) is not int:
        _fail(
            _CONTRACT_MISMATCH,
            "Internal terminal-source binding kind or version is unsupported.",
        )
    return value


def _items(value: object, *, message: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        _fail(_CONTRACT_MISMATCH, message)
    return tuple(value)


def _sample_label(value: object) -> str:
    sample = _text(
        value,
        message="Terminal sample_order must contain unique canonical labels.",
    )
    if not sample or sample.strip() != sample:
        _fail(
            _CONTRACT_MISMATCH,
            "Terminal sample_order must contain unique canonical labels.",
        )
    return sample


def _point_count_record(value: object) -> tuple[str, int]:
    record = _mapping_with_fields(
        value,
        fields=frozenset({"sample", "count"}),
        message="Internal terminal point-count record is invalid.",
    )
    sample = _text(
        record["sample"],
        message="Terminal point_counts must follow the complete sample_order.",
    )
    if not sample or sample.strip() != sample:
        _fail(
            _CONTRACT_MISMATCH,
            "Terminal point_counts must follow the complete sample_order.",
        )
    count = _integer(
        record["count"],
        message="Terminal point counts must be positive integers.",
    )
    if count <= 0:
        _fail(
            _CONTRACT_MISMATCH,
            "Terminal point counts must be positive integers.",
        )
    return sample, count


def sealed_terminal_source_binding_from_payload(
    value: object,
) -> SealedTerminalSourceBinding:
    payload = _mapping_with_fields(
        value,
        fields=_PAYLOAD_FIELDS,
        message="Internal terminal-source binding field set is invalid.",
    )
    kind = _text(
        payload["kind"],
        message="Internal terminal-source binding kind or version is unsupported.",
    )
    version = _version(payload["version"])
    if kind != TERMINAL_SOURCE_BINDING_KIND or (
        version != TERMINAL_SOURCE_BINDING_VERSION
    ):
        _fail(
            _CONTRACT_MISMATCH,
            "Internal terminal-source binding kind or version is unsupported.",
        )
    task_key = _text(
        payload["task_key"],
        message="task_key must be one canonical lowercase identifier.",
    )
    rule_id = _text(
        payload["rule_id"],
        message="rule_id must be one canonical lowercase identifier.",
    )
    template = _text(
        payload["template"],
        message="template must be one canonical lowercase identifier.",
    )
    x_metric = _text(
        payload["x_metric"],
        message="x_metric must be one canonical metric identifier.",
    )
    y_metric = _text(
        payload["y_metric"],
        message="y_metric must be one canonical metric identifier.",
    )
    inventory_message = "Internal terminal-source binding inventories are invalid."
    raw_values = _items(payload["raw_sources"], message=inventory_message)
    sample_values = _items(payload["sample_order"], message=inventory_message)
    count_values = _items(payload["point_counts"], message=inventory_message)
    samples = tuple(_sample_label(item) for item in sample_values)
    point_counts = tuple(_point_count_record(item) for item in count_values)
    if tuple(sample for sample, _count in point_counts) != samples:
        _fail(
            _CONTRACT_MISMATCH,
            "Terminal point_counts must follow the complete sample_order.",
        )
    raw_sources = tuple(
        SourceArtifactBinding.from_payload(item, label="Raw source")
        for item in raw_values
    )
    prepared_source = SourceArtifactBinding.from_payload(
        payload["prepared_source"], label="Prepared source"
    )
    terminal_source = SourceArtifactBinding.from_payload(
        payload["terminal_source"], label="Terminal source"
    )
    request = SourceArtifactBinding.from_payload(
        payload["request"], label="Terminal worker request"
    )
    materialized = MaterializedTerminalSourceBinding(
        task_key=task_key,
        rule_id=rule_id,
        template=template,
        x_metric=x_metric,
        y_metric=y_metric,
        raw_sources=raw_sources,
        prepared_source=prepared_source,
        terminal_source=terminal_source,
        sample_order=samples,
        point_counts=point_counts,
    )
    return SealedTerminalSourceBinding(
        materialized=materialized,
        request=request,
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


def consume_terminal_source_prepared_environment() -> bool:
    """Consume the private single-pass semantic-preparation marker."""

    return os.environ.pop(TERMINAL_SOURCE_PREPARED_ENV, None) == "1"


__all__ = [
    "TERMINAL_SOURCE_BINDING_ENV",
    "TERMINAL_SOURCE_PREPARED_ENV",
    "consume_terminal_source_binding_environment",
    "consume_terminal_source_prepared_environment",
    "sealed_terminal_source_binding_from_payload",
]
