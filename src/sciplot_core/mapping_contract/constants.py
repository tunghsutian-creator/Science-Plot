"""Declare mapping contract kinds, versions, roles, and declarative operations."""

from __future__ import annotations

import re


DATA_MAPPING_PROPOSAL_KIND = "sciplot_data_mapping_proposal"


DATA_MAPPING_PROPOSAL_VERSION = 2


DATA_MAPPING_CONFIRMATION_KIND = "sciplot_data_mapping_confirmation"


DATA_MAPPING_CONFIRMATION_LEGACY_VERSION = 1


DATA_MAPPING_CONFIRMATION_VERSION = 2


DECLARATIVE_TRANSFORMATIONS = frozenset(
    {
        "rename",
        "select",
        "exclude",
        "drop_missing",
        "sort",
        "unit_convert",
        "derive_ratio",
        "normalize_baseline",
        "aggregate_replicates",
    }
)


DATA_COLUMN_ROLES = frozenset(
    {
        "x",
        "y",
        "z",
        "value",
        "sample",
        "replicate",
        "category",
        "x_error",
        "y_error",
        "metadata",
    }
)


DATA_MAPPING_REQUEST_PATCH_KEYS = frozenset(
    {
        "recipe",
        "rule_id",
        "template",
        "x_metric",
        "y_metric",
        "z_metric",
        "series_order",
        "replicate_mode",
    }
)


_REPLICATE_MODES = frozenset({"mean", "representative", "individual"})


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


_SHA256 = re.compile(r"[0-9a-f]{64}")


_FORBIDDEN_EXECUTABLE_KEYS = {
    "python",
    "code",
    "script",
    "command",
    "shell",
    "executable",
    "expression",
    "eval",
}
