"""Normalize and hash persisted numeric and text dataset evidence."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _exact_numeric_token(value: object) -> str:
    number = float(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "inf" if number > 0.0 else "-inf"
    return number.hex()


def _persisted_expected_numeric_token(value: object) -> str:
    number = float(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "inf" if number > 0.0 else "-inf"
    # Veusz Save writes ordinary numeric datasets with six digits after the
    # decimal point in scientific notation. Quantize the generation spec once
    # to that persisted token, then compare the reopened value exactly. Do not
    # round the reopened value: a hand-edited token carrying extra precision
    # must remain distinguishable.
    return float(f"{number:.6e}").hex()


def _numeric_payload(
    value: object,
    *,
    expected_persisted: bool = False,
) -> list[Any]:
    materialized = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(materialized, list | tuple):
        raise ValueError("Veusz numeric evidence must be a list or array.")
    token = (
        _persisted_expected_numeric_token
        if expected_persisted
        else _exact_numeric_token
    )
    return [
        _numeric_payload(item, expected_persisted=expected_persisted)
        if isinstance(item, list | tuple) or hasattr(item, "tolist")
        else token(item)
        for item in materialized
    ]


def _numeric_digest(
    value: object,
    *,
    expected_persisted: bool = False,
) -> str:
    payload = json.dumps(
        _numeric_payload(value, expected_persisted=expected_persisted),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _dataset_evidence(
    loaded_document: Any,
    *,
    dataset_name: str,
    expected_values: object,
    dimensions: int,
) -> dict[str, Any]:
    dataset = loaded_document.data.get(dataset_name)
    if dataset is None:
        raise ValueError(
            f"Exact-current Veusz document has no dataset {dataset_name!r}."
        )
    if int(getattr(dataset, "dimensions", -1)) != dimensions:
        raise ValueError(
            f"Veusz dataset {dataset_name!r} has the wrong dimensionality."
        )
    actual_values = getattr(dataset, "data", None)
    expected_hash = _numeric_digest(
        expected_values,
        expected_persisted=True,
    )
    actual_hash = _numeric_digest(actual_values)
    if actual_hash != expected_hash:
        raise ValueError(
            f"Veusz dataset {dataset_name!r} differs from the rendered specification."
        )
    materialized = (
        actual_values.tolist() if hasattr(actual_values, "tolist") else actual_values
    )
    if dimensions == 1:
        shape = [len(materialized)]
    else:
        rows = len(materialized)
        columns = len(materialized[0]) if rows else 0
        if any(
            not isinstance(row, list | tuple) or len(row) != columns
            for row in materialized
        ):
            raise ValueError(
                f"Veusz dataset {dataset_name!r} is not a rectangular 2D array."
            )
        shape = [rows, columns]
    return {
        "name": dataset_name,
        "dimensions": dimensions,
        "shape": shape,
        "value_sha256": actual_hash,
    }


def _text_dataset_values(
    loaded_document: Any,
    *,
    dataset_name: str,
) -> list[str]:
    dataset = loaded_document.data.get(dataset_name)
    if dataset is None:
        raise ValueError(
            f"Exact-current Veusz document has no text dataset {dataset_name!r}."
        )
    values = getattr(dataset, "data", None)
    materialized = values.tolist() if hasattr(values, "tolist") else values
    if not isinstance(materialized, list | tuple):
        raise ValueError(f"Veusz text dataset {dataset_name!r} is not a text sequence.")
    return [str(value) for value in materialized]
