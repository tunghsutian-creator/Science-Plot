"""Private native naming, numeric arrays and literal text shared by IR versions."""

from hashlib import sha256
from typing import Any


def native_name(prefix: str, identity: str) -> str:
    return f"{prefix}_{sha256(identity.encode()).hexdigest()[:20]}"


def dataset_name(dataset_id: str, column_id: str) -> str:
    return native_name("data", f"{dataset_id}\0{column_id}")


def number_unit(value: float, unit: str) -> str:
    return f"{repr(float(value))}{unit}"


def _text(value: str) -> str:
    # Literal labels, never Veusz expression/format instructions.
    from sciplot_core.studio_core.series_request import _veusz_literal_text

    return _veusz_literal_text(value)


def native_datasets(ir: dict[str, Any]) -> dict[str, list[float]]:
    return {dataset_name(identity, column): [float("nan") if value is None else float(value)
                                            for value in record["values"]]
            for identity, dataset in ir["datasets"].items() for column, record in dataset["columns"].items()}


