"""Carry immutable inputs shared by semantic preparation handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source import (
        ResolvedScientificSource,
    )


@dataclass(frozen=True)
class SemanticPreparationContext:
    source: Path
    processed_dir: Path
    family: str
    rule_id: str | None
    curation_path: str | Path | None
    series_order: object
    column_confirmations: object
    replicate_mode: object
    source_tree_sha256_before: str | None = None
    resolved_scientific_source: ResolvedScientificSource | None = None
