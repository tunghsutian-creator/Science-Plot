"""Carry immutable inputs shared by semantic preparation handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SemanticPreparationContext:
    source: Path
    processed_dir: Path
    family: str
    curation_path: str | Path | None
    series_order: object
    column_confirmations: object
    replicate_mode: object
