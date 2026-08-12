"""Public API for reading and parsing source tables."""

from __future__ import annotations

from sciplot_core.source_tables.curve_tables import (
    load_curve_table,
    load_curve_table_from_frame,
)
from sciplot_core.source_tables.heatmap_tables import (
    load_heatmap_table,
    load_heatmap_table_from_frame,
)
from sciplot_core.source_tables.models import (
    CurveSeries,
    HeatmapTable,
    ReplicateGroup,
)
from sciplot_core.source_tables.raw_readers import read_raw_table
from sciplot_core.source_tables.replicate_tables import (
    load_replicate_table,
    load_replicate_table_from_frame,
)
from sciplot_core.source_tables.text_normalization import (
    canonicalize_token,
    clean_source_text,
    normalize_label,
    normalize_unit,
    slugify_canonical_label,
    slugify_label,
)


__all__ = [
    "CurveSeries",
    "HeatmapTable",
    "ReplicateGroup",
    "canonicalize_token",
    "clean_source_text",
    "load_curve_table",
    "load_curve_table_from_frame",
    "load_heatmap_table",
    "load_heatmap_table_from_frame",
    "load_replicate_table",
    "load_replicate_table_from_frame",
    "normalize_label",
    "normalize_unit",
    "read_raw_table",
    "slugify_canonical_label",
    "slugify_label",
]
