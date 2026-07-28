"""Discover and reshape 3DPA FTIR and torque inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.source_tables import read_raw_table

from sciplot_core.acceptance.fixtures import (
    DEFAULT_3DPA_FTIR_LABELS,
    DEFAULT_3DPA_TORQUE_DIRS,
    SpectrumSeries,
)


def _normalize_label(value: str) -> str:
    return value.strip().casefold().replace("_", "-").replace(" ", "")


def _candidate_ftir_dirs(root: Path) -> list[Path]:
    candidates = [
        root,
        root / "FTIR",
        root / "FTIR" / "红外",
        root / "FTIR" / "20 min",
        root / "FTIR" / "2 min",
        root / "红外",
    ]
    seen: set[Path] = set()
    existing: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def _find_ftir_files(root: Path, *, representative_count: int) -> list[Path]:
    files: list[Path] = []
    for directory in _candidate_ftir_dirs(root):
        files.extend(sorted(path for path in directory.glob("*.CSV") if path.is_file()))
        files.extend(sorted(path for path in directory.glob("*.csv") if path.is_file()))
        if len(files) >= representative_count:
            break
    if not files:
        files = sorted(path for path in root.rglob("*.CSV") if path.is_file())
        files.extend(sorted(path for path in root.rglob("*.csv") if path.is_file()))

    by_label = {_normalize_label(path.stem): path for path in files}
    selected: list[Path] = []
    selected_set: set[Path] = set()
    for label in DEFAULT_3DPA_FTIR_LABELS:
        path = by_label.get(_normalize_label(label))
        if path is not None and path not in selected_set:
            selected.append(path)
            selected_set.add(path)
    for path in files:
        if len(selected) >= representative_count:
            break
        if path not in selected_set:
            selected.append(path)
            selected_set.add(path)

    if len(selected) < 2:
        raise ValueError(
            f"3D PA acceptance needs at least two FTIR CSV files under {root}."
        )
    return selected[:representative_count]


def _candidate_torque_dirs(root: Path) -> list[Path]:
    candidates = [root / item for item in DEFAULT_3DPA_TORQUE_DIRS]
    torque_root = root / "转矩"
    if torque_root.exists():
        candidates.extend(path for path in torque_root.glob("*") if path.is_dir())
    seen: set[Path] = set()
    existing: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        if len(list(resolved.glob("*.txt"))) < 2:
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def _find_torque_dir(root: Path) -> Path | None:
    candidates = _candidate_torque_dirs(root)
    if candidates:
        return candidates[0]
    for directory in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
        if not directory.is_dir():
            continue
        text = directory.as_posix().casefold()
        if ("转矩" not in text and "torque" not in text) or len(
            list(directory.glob("*.txt"))
        ) < 2:
            continue
        return directory
    return None


def _sample_label(path: Path) -> str:
    return path.stem.strip()


def _read_raw_spectrum(path: Path) -> pd.DataFrame:
    raw = read_raw_table(path)
    if raw.shape[1] < 2:
        raise ValueError(f"FTIR spectrum must have at least two columns: {path}")
    frame = raw.iloc[:, :2].apply(pd.to_numeric, errors="coerce").dropna()
    if frame.empty:
        raise ValueError(f"FTIR spectrum has no numeric x/y rows: {path}")
    frame.columns = ["x", "raw_y"]
    frame = frame.sort_values("x").reset_index(drop=True)
    y = frame["raw_y"].astype(float)
    low = float(y.quantile(0.01))
    high = float(y.quantile(0.99))
    if high <= low:
        normalized = y * 0.0
    else:
        normalized = ((y - low) / (high - low)).clip(lower=0.0, upper=1.25)
    return pd.DataFrame({"x": frame["x"].astype(float), "y": normalized.astype(float)})


def _load_spectra(paths: list[Path]) -> list[SpectrumSeries]:
    return [
        SpectrumSeries(
            label=_sample_label(path),
            source=path.expanduser().resolve(),
            data=_read_raw_spectrum(path),
        )
        for path in paths
    ]


def _write_curve_table(series: list[SpectrumSeries], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[list[Any]] = [
        sum((["Wavenumber", "Normalized absorbance"] for _ in series), []),
        sum((["cm^-1", "a.u."] for _ in series), []),
        sum(([item.label, item.label] for item in series), []),
    ]
    max_len = max(len(item.data) for item in series)
    for row_index in range(max_len):
        row: list[Any] = []
        for item in series:
            if row_index < len(item.data):
                row.extend(
                    [
                        float(item.data.iat[row_index, 0]),
                        float(item.data.iat[row_index, 1]),
                    ]
                )
            else:
                row.extend(["", ""])
        rows.append(row)
    pd.DataFrame(rows).to_csv(output, header=False, index=False)
    return output


def _build_dense_series(
    series: list[SpectrumSeries], *, series_count: int
) -> list[SpectrumSeries]:
    if series_count < 1:
        raise ValueError("dense series count must be at least 1.")
    dense: list[SpectrumSeries] = []
    for index in range(series_count):
        item = series[index % len(series)]
        repeat = index // len(series) + 1
        dense.append(
            SpectrumSeries(
                label=f"{item.label} r{repeat:02d}",
                source=item.source,
                data=item.data,
            )
        )
    return dense


def _write_request(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path
