from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core._utils import json_safe, slug
from sciplot_core.curate import curate_torque_project
from sciplot_core.policy import DEFAULT_FIGURE_SIZE
from sciplot_core.workflow import run_request

ensure_legacy_core()

from src.data_loader import read_raw_table  # noqa: E402

DEFAULT_3DPA_FTIR_LABELS = ("PA6", "A20", "A40", "A80", "A20-2MIN", "A30-2MIN")
DEFAULT_3DPA_TORQUE_DIRS = ("转矩/260607", "转矩/Z", "torque/260607", "torque/Z")
DEFAULT_DENSE_SERIES_COUNT = 44
DEFAULT_REPRESENTATIVE_COUNT = 6


@dataclass(frozen=True)
class SpectrumSeries:
    label: str
    source: Path
    data: pd.DataFrame


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
        raise ValueError(f"3D PA acceptance needs at least two FTIR CSV files under {root}.")
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
        if ("转矩" not in text and "torque" not in text) or len(list(directory.glob("*.txt"))) < 2:
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
        SpectrumSeries(label=_sample_label(path), source=path.expanduser().resolve(), data=_read_raw_spectrum(path))
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


def _build_dense_series(series: list[SpectrumSeries], *, series_count: int) -> list[SpectrumSeries]:
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
    path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(manifest["output"]))
    layout_quality = manifest.get("layout_quality") if isinstance(manifest.get("layout_quality"), dict) else {}
    delivery = manifest.get("delivery_package") if isinstance(manifest.get("delivery_package"), dict) else {}
    summaries = layout_quality.get("summaries") if isinstance(layout_quality.get("summaries"), list) else []
    first_axis: dict[str, Any] = {}
    if summaries:
        axes = summaries[0].get("axes") if isinstance(summaries[0], dict) else []
        if isinstance(axes, list) and axes:
            first_axis = axes[0] if isinstance(axes[0], dict) else {}
    pdf_count = len(list((output_dir / "figures").glob("*.pdf")))
    tiff_count = len(list((output_dir / "figures").glob("*_300dpi.tiff")))
    delivery_dir = Path(str(delivery.get("path"))) if delivery.get("path") else output_dir / "delivery"
    state = "ready"
    if manifest.get("qa", {}).get("status") != "passed":
        state = "needs_rule_repair"
    if layout_quality.get("issue_ids"):
        state = "needs_rule_repair"
    if delivery.get("complete") is not True:
        state = "needs_rule_repair"
    return {
        "state": state,
        "output": str(output_dir),
        "manifest": str(output_dir / "manifest.json"),
        "delivery": str(delivery_dir),
        "delivery_complete": bool(delivery.get("complete")),
        "qa_status": manifest.get("qa", {}).get("status"),
        "render_engine": manifest.get("render_engine"),
        "qa_target": manifest.get("qa_target"),
        "veusz_document_count": len(manifest.get("veusz_documents", [])),
        "veusz_spec_count": len(manifest.get("veusz_specs", [])),
        "layout_issue_ids": layout_quality.get("issue_ids", []),
        "autofixes_applied": layout_quality.get("autofixes_applied", []),
        "auto_split": layout_quality.get("auto_split"),
        "split_plan": layout_quality.get("split_plan"),
        "x_bounds": first_axis.get("x_bounds"),
        "x_ticks": first_axis.get("x_ticks"),
        "legend": first_axis.get("legend"),
        "pdf_count": pdf_count,
        "tiff_300_count": tiff_count,
    }


def _run_acceptance_request(
    *,
    run_root: Path,
    request_name: str,
    input_path: Path,
    render_options: dict[str, Any],
    review_notes: list[str],
) -> dict[str, Any]:
    request_dir = run_root / request_name
    request = {
        "template": "stacked_curve",
        "input": str(input_path.resolve()),
        "output": str((request_dir / "run_001").resolve()),
        "render_options": render_options,
        "review_notes": review_notes,
    }
    request_path = _write_request(request_dir / "plot_request.json", request)
    manifest = run_request(request_path)
    return {
        "id": request_name,
        "request_path": str(request_path),
        "summary": _manifest_summary(manifest),
    }


def _run_torque_acceptance(*, project_dir: Path, torque_dir: Path) -> dict[str, Any]:
    curation = curate_torque_project(
        torque_dir,
        output_root=project_dir / "_torque_curation_projects",
        project_name="3D PA torque acceptance",
        open_review=False,
    )
    request_path = Path(str(curation["plot_request"]))
    manifest = run_request(request_path)
    return {
        "id": "torque_260607_curve",
        "request_path": str(request_path),
        "summary": _manifest_summary(manifest),
        "curation": {
            "source_dir": str(torque_dir),
            "project_dir": curation.get("project_dir"),
            "selection_path": curation.get("selection_path"),
            "plot_data_path": curation.get("plot_data_path"),
            "review_html": curation.get("review_html"),
        },
    }


def run_3dpa_acceptance(
    input_root: Path,
    *,
    output_root: Path,
    project_name: str = "3dpa_acceptance",
    representative_count: int = DEFAULT_REPRESENTATIVE_COUNT,
    dense_series_count: int = DEFAULT_DENSE_SERIES_COUNT,
) -> dict[str, Any]:
    root = input_root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"3D PA input root not found: {input_root}")
    if representative_count < 2:
        raise ValueError("representative_count must be at least 2.")
    output_root = output_root.expanduser().resolve()
    project_dir = output_root / slug(project_name)
    data_dir = project_dir / "data"
    source_files = _find_ftir_files(root, representative_count=representative_count)
    spectra = _load_spectra(source_files)
    representative_table = _write_curve_table(spectra, data_dir / "3dpa_ftir_representative_stack.csv")
    dense_table = _write_curve_table(
        _build_dense_series(spectra, series_count=dense_series_count),
        data_dir / f"3dpa_ftir_dense_stack_{dense_series_count}.csv",
    )

    runs = [
        _run_acceptance_request(
            run_root=project_dir,
            request_name="ftir_representative_stack",
            input_path=representative_table,
            render_options={"size": DEFAULT_FIGURE_SIZE, "series_label_mode": "legend"},
            review_notes=["3D PA FTIR representative stack acceptance from raw two-column spectra."],
        ),
        _run_acceptance_request(
            run_root=project_dir,
            request_name="ftir_dense_auto_split",
            input_path=dense_table,
            render_options={"size": "60x110", "series_label_mode": "legend"},
            review_notes=[
                "3D PA FTIR dense-stack acceptance. Representative raw spectra are duplicated to exercise "
                "automatic split boundaries without synthetic curve shapes."
            ],
        ),
    ]
    torque_dir = _find_torque_dir(root)
    if torque_dir is not None:
        runs.append(_run_torque_acceptance(project_dir=project_dir, torque_dir=torque_dir))
    state = "ready" if all(run["summary"]["state"] == "ready" for run in runs) else "needs_rule_repair"
    payload = {
        "kind": "sciplot_acceptance_run",
        "target": "3dpa",
        "state": state,
        "project_dir": str(project_dir),
        "source_root": str(root),
        "source_files": [str(path) for path in source_files],
        "torque_source_dir": str(torque_dir) if torque_dir is not None else None,
        "data": {
            "representative_table": str(representative_table),
            "dense_table": str(dense_table),
            "dense_series_count": dense_series_count,
        },
        "runs": runs,
    }
    (project_dir / "acceptance_summary.json").write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "DEFAULT_3DPA_FTIR_LABELS",
    "DEFAULT_3DPA_TORQUE_DIRS",
    "DEFAULT_DENSE_SERIES_COUNT",
    "DEFAULT_REPRESENTATIVE_COUNT",
    "run_3dpa_acceptance",
]
