"""Preserve binary64 curve values through the native Veusz text writer."""

from typing import Any


NUMERIC_ENCODING_KEY = "native_1d_numeric_encoding"
FLOAT64_ENCODING = "float64_round_trip_v1"


def ensure_veusz_numeric_precision() -> None:
    """Keep upstream serialization and descriptors; change only its float format."""
    from veusz.datasets.oned import Dataset1DBase

    current = Dataset1DBase.datasetAsText
    if getattr(current, "_sciplot_float64_round_trip", False):
        return

    def dataset_as_text(dataset: Any, fmt: str = "%g", join: str = "\t") -> str:
        # Native Save uses %e (seven significant digits). Seventeen significant
        # digits round-trip every binary64 value, including error datasets.
        full = getattr(getattr(dataset, "document", None), "_sciplot_write_full_precision", True)
        return current(dataset, fmt="%.17g" if fmt == "%e" and full else fmt, join=join)

    dataset_as_text._sciplot_float64_round_trip = True  # type: ignore[attr-defined]
    Dataset1DBase.datasetAsText = dataset_as_text
