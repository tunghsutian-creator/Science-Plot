"""Define normalized data models returned by source-table parsers."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CurveSeries:
    sample: str
    x_label: str
    y_label: str
    x_unit: str
    y_unit: str
    data: pd.DataFrame


@dataclass
class ReplicateGroup:
    group: str
    value_label: str
    value_unit: str
    data: pd.Series


@dataclass
class HeatmapTable:
    x_label: str
    y_label: str
    z_label: str
    x_unit: str
    y_unit: str
    z_unit: str
    data: pd.DataFrame


__all__ = ["CurveSeries", "HeatmapTable", "ReplicateGroup"]
