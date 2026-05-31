from __future__ import annotations

from pathlib import Path

import pandas as pd


def ensure_input_path(path_text: str | Path) -> Path:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Input path is not a file: {path}")
    return path


def list_sheet_names(input_path: str | Path) -> list[str]:
    path = Path(input_path).expanduser()
    if path.suffix.lower() not in {".xls", ".xlsx", ".xlsm"}:
        return []
    with pd.ExcelFile(path) as workbook:
        return list(workbook.sheet_names)
