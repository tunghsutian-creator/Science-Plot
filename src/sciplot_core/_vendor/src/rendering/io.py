from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.rendering.constants import WORKSPACE_OUTPUT_DIR
from src.rendering.models import OutputMode


def coerce_sheet(sheet: str) -> str | int:
    return int(sheet) if sheet.isdigit() else sheet


def ensure_input_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Input path is not a file: {path}")
    return path


def normalize_input_path_text(path_text: str) -> str:
    cleaned = path_text.strip()
    if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    return re.sub(r"\\(.)", r"\1", cleaned)


def default_output_dir(input_path: Path) -> Path:
    return input_path.parent / "plots"


def resolve_output_dir(input_path: Path, output_dir: str | None, output_mode: OutputMode) -> Path:
    if output_dir:
        return Path(output_dir).expanduser()
    if output_mode == "data_dir":
        return default_output_dir(input_path)
    return WORKSPACE_OUTPUT_DIR


def list_sheet_names(input_path: Path) -> list[str]:
    if input_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return []
    with pd.ExcelFile(input_path) as workbook:
        return list(workbook.sheet_names)
