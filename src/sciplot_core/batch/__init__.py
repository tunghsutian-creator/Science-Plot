"""Batch regression runner and compatibility facade."""

from sciplot_core.batch.run import run_batch
from sciplot_core.batch.source_discovery import (
    is_tensile_related as _is_tensile_related,  # noqa: F401
)

__all__ = ["run_batch"]
