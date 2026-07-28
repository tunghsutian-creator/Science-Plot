"""Shared constants for the intake confirmation surface."""

from __future__ import annotations

from pathlib import Path
from sciplot_core.policy import FIGURE_SIZE_PRESETS

_DEFAULT_OUTPUT_ROOT = Path("outputs") / "intake_projects"

APPROVED_INTAKE_SIZE_PRESETS = FIGURE_SIZE_PRESETS

_TEXT_EXTENSIONS = {".csv", ".tsv", ".txt"}

_TABLE_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}

_PREVIEW_SCAN_ROWS = 80

_PREVIEW_DISPLAY_ROWS = 24

_PREVIEW_DISPLAY_COLUMNS = 24

_COLUMN_ROLES = {"auto", "x", "y", "series", "sample", "unit", "metadata", "ignore"}

_COLUMN_TYPES = {
    "auto",
    "numeric",
    "text",
    "categorical",
    "datetime",
    "unit",
    "metadata",
    "ignore",
}

_REPLICATE_MODES = {"mean", "representative", "individual"}

SAXS_SCALING_REVIEW_NOTE = (
    "Retained positive SAXS source intensity values were preserved without "
    "inferred vertical-offset correction; non-positive log-domain points were "
    "excluded, and absolute cross-series magnitudes remain unvalidated unless "
    "source metadata documents its scaling."
)

_LEGACY_SAXS_SCALING_REVIEW_NOTE_PREFIX = (
    "SAXS source intensity values are preserved without inferred "
)
