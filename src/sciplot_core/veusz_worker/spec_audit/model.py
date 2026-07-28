"""Represent the mutable inventory shared by one closed spec-data audit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SpecAuditInventory:
    loaded_document: Any
    units: list[dict[str, Any]]
    seen_identities: set[str]
    allowed_xy_records: set[tuple[str, str, str]]
    expected_xy_order: list[tuple[str, str, str, str]]
    allowed_boxplot_records: set[tuple[str, tuple[str, ...], tuple[float, ...]]]
    expected_boxplot_order: list[tuple[str, tuple[str, ...], tuple[float, ...]]]
    categorical: Any
    categorical_kind: str
    categorical_groups: dict[str, dict[str, Any]]
    expected_box_name_by_y: dict[str, str]
    xy_records: list[dict[str, Any]]
    boxplot_records: list[dict[str, Any]]
    bar_records: list[dict[str, Any]]
    component_bar_record: dict[str, Any] | None
    component_bar_datasets_by_y: dict[str, list[dict[str, Any]]]
    allowed_bar_paths: set[str]
