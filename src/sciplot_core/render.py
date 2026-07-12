from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core._utils import json_safe
from sciplot_core.ingest import normalized_source
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.semantic import classify_source
from sciplot_core.split import SUPPORTED_SPLIT_TEMPLATES, build_split_plan, normalize_split_policy
from sciplot_core.veusz_runtime import veusz_worker_environment

ensure_legacy_core()

from src.data_loader import load_curve_table  # noqa: E402
from src.rendering.options import validate_template_name  # noqa: E402
from src.rendering.recommendation import inspect_input_file  # noqa: E402
from src.rendering.series_order import (  # noqa: E402
    filter_curve_series,
    reorder_curve_series,
    unknown_series_order_labels,
)

_EXPORT_FORMATS = {
    "pdf": ("pdf", None, ""),
    "svg": ("svg", None, ""),
    "png": ("png", 300, "_300dpi"),
    "png_300": ("png", 300, "_300dpi"),
    "png_600": ("png", 600, "_600dpi"),
    "tiff": ("tiff", 300, "_300dpi"),
    "tiff_300": ("tiff", 300, "_300dpi"),
}

DEFAULT_EXPORT_FORMATS = DEFAULT_EXPORT_FORMATS_POLICY
DEFAULT_RENDER_ENGINE = "veusz"


def inspect_payload(input_path: Path, *, sheet: str | int = 0) -> dict[str, Any]:
    with normalized_source(input_path) as source:
        payload = json_safe(inspect_input_file(source, sheet))
        payload["sciplot_semantics"] = json_safe(
            classify_source(source, sheet=sheet, vendor_inspection=payload),
        )
    return payload


def _normalize_export_formats(export_formats: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if export_formats is None:
        return DEFAULT_EXPORT_FORMATS
    normalized = tuple(str(item).strip().lower() for item in export_formats if str(item).strip())
    if not normalized:
        return DEFAULT_EXPORT_FORMATS
    unknown = [item for item in normalized if item not in _EXPORT_FORMATS]
    if unknown:
        known = ", ".join(sorted(_EXPORT_FORMATS))
        raise ValueError(f"Unknown export format(s): {', '.join(unknown)}. Available exports: {known}.")
    return normalized


def _export_path(filename: str, output_dir: Path, export_format: str) -> Path:
    target_format, _dpi, suffix = _EXPORT_FORMATS[export_format]
    base = Path(filename).with_suffix("").name
    if target_format == "pdf":
        return output_dir / f"{base}.pdf"
    extension = "tiff" if target_format == "tiff" else target_format
    return output_dir / f"{base}{suffix}.{extension}"


def _series_labels_for_split(source: Path, sheet: str | int, options: dict[str, Any]) -> list[str]:
    series_list = load_curve_table(source, sheet_name=sheet)
    available = [series.sample for series in series_list]
    series_include = options.get("series_include")
    unknown_include = unknown_series_order_labels(available, series_include)
    if unknown_include:
        raise ValueError("series_include contains unknown series labels: " + ", ".join(unknown_include))
    selected = filter_curve_series(series_list, series_include)
    if not selected and series_include:
        raise ValueError("series_include did not match any series.")
    selected_labels = [series.sample for series in selected]
    series_order = options.get("series_order")
    unknown_order = unknown_series_order_labels(selected_labels, series_order)
    if unknown_order:
        raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown_order))
    ordered = reorder_curve_series(selected, series_order)
    return [series.sample for series in ordered]


def _veusz_worker_env() -> dict[str, str]:
    return veusz_worker_environment()


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _veusz_target_base(source: Path, template: str, *, panel_index: int | None = None) -> str:
    base = f"{source.stem}_{template}"
    if panel_index is not None:
        base = f"{base}_part{panel_index:02d}"
    return base


def _render_studio_exports(request_path: Path, export_formats: tuple[str, ...]) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "export",
        str(request_path),
        "--formats",
        ",".join(export_formats),
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        env=_veusz_worker_env(),
    )
    return json.loads(result.stdout)


def _veusz_layout_report(
    *,
    template: str,
    spec: dict[str, Any],
    document: Path,
    outputs: list[Path],
    split_panel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    size = spec.get("size_mm") if isinstance(spec.get("size_mm"), list) else []
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    y_axis = axes.get("y") if isinstance(axes.get("y"), dict) else {}
    summary: dict[str, Any] = {
        "kind": "sciplot_veusz_layout_summary",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template,
        "document": str(document),
        "outputs": [str(path) for path in outputs],
        "series_count": len(series),
        "requested_size_mm": size,
        "figure_size_mm": size,
        "axes": [
            {
                "x_label": x_axis.get("label"),
                "y_label": y_axis.get("label"),
                "x_bounds": [x_axis.get("min"), x_axis.get("max")],
                "y_bounds": [y_axis.get("min"), y_axis.get("max")],
                "x_ticks": x_axis.get("ticks") or [],
                "y_ticks": y_axis.get("ticks") or [],
                "legend": spec.get("legend", {}),
            }
        ],
    }
    if split_panel is not None:
        summary["split_panel"] = split_panel
    issues: list[dict[str, Any]] = [
        item for item in spec.get("layout_issues", []) if isinstance(item, dict)
    ]
    if (
        split_panel is None
        and template in SUPPORTED_SPLIT_TEMPLATES
        and len(series) >= 24
        and len(size) >= 2
        and float(size[1]) >= 100.0
    ):
        issues.append(
            {
                "id": "stack_peak_too_small",
                "severity": "warning",
                "message": "Dense stacked Veusz output should be split into readable panels.",
            }
        )
    return {
        "kind": "sciplot_veusz_qa_report",
        "engine": "veusz",
        "issues": issues,
        "autofixes_applied": [
            str(item) for item in spec.get("autofixes_applied", []) if isinstance(item, str)
        ],
        "layout_summary": summary,
    }


def _copy_veusz_exports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    output_base: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    outputs: list[Path] = []
    export_records: list[dict[str, Any]] = []
    for item in payload.get("exports", []):
        if not isinstance(item, dict):
            continue
        source_value = item.get("path")
        fmt = str(item.get("format") or "").strip().lower()
        if not isinstance(source_value, str) or not fmt:
            continue
        source = Path(source_value).expanduser()
        if not source.exists():
            continue
        destination = _export_path(f"{output_base}.pdf", output_dir, fmt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record = {
            "path": str(destination),
            "format": fmt,
            "dpi": item.get("dpi"),
            "source": str(source),
            "exists": destination.exists(),
            "size_bytes": destination.stat().st_size if destination.exists() else 0,
        }
        outputs.append(destination)
        export_records.append(record)
    return outputs, export_records


def _cleanup_worker_exports(panel_dir: Path) -> None:
    for path in (panel_dir / "studio" / "exports", panel_dir / "runs"):
        if path.exists():
            shutil.rmtree(path)


def _render_veusz_panel(
    source: Path,
    *,
    template: str,
    output_dir: Path,
    panel_dir: Path,
    output_base: str,
    options: dict[str, Any],
    export_formats: tuple[str, ...],
    split_panel: dict[str, Any] | None = None,
) -> tuple[list[Path], list[dict[str, Any]], dict[str, Any], Path, Path]:
    panel_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "input": str(source.resolve()),
        "template": template,
        "output": str(output_dir),
        "exports": list(export_formats),
        "render_options": dict(options),
    }
    request_path = panel_dir / "plot_request.json"
    request_path.write_text(json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8")
    payload = _render_studio_exports(request_path, export_formats)
    outputs, export_records = _copy_veusz_exports(payload, output_dir=output_dir, output_base=output_base)
    document = Path(str(payload["document"]))
    spec = Path(str(payload.get("studio", {}).get("spec") or document.with_suffix(".spec.json")))
    spec_payload = _read_json_if_exists(spec)
    report = _veusz_layout_report(
        template=template,
        spec=spec_payload,
        document=document,
        outputs=outputs,
        split_panel=split_panel,
    )
    _cleanup_worker_exports(panel_dir)
    return outputs, export_records, report, document, spec


def _render_to_dir_veusz(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    export_formats: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = dict(options or {})
    normalized_exports = _normalize_export_formats(export_formats)
    normalized_split_policy = normalize_split_policy(split_policy)
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_root = output_dir / "_veusz"
    if worker_root.exists():
        shutil.rmtree(worker_root)
    worker_root.mkdir(parents=True, exist_ok=True)

    all_outputs: list[Path] = []
    all_exports: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    documents: list[str] = []
    specs: list[str] = []
    with normalized_source(input_path) as source:
        split_plan: dict[str, Any] | None = None
        panels: list[tuple[int | None, list[str] | None]]
        if normalized_split_policy is None:
            panels = [(None, None)]
        else:
            labels = _series_labels_for_split(source, sheet, options)
            split_plan = build_split_plan(labels, policy=normalized_split_policy)
            chunks = [list(chunk["series"]) for chunk in split_plan["chunks"]]
            panels = [(index, chunk) for index, chunk in enumerate(chunks, start=1)]

        for panel_index, chunk in panels:
            panel_options = dict(options)
            split_panel: dict[str, Any] | None = None
            if chunk is not None and panel_index is not None:
                panel_options["series_include"] = list(chunk)
                panel_options["series_order"] = list(chunk)
                split_panel = {
                    "index": panel_index,
                    "count": len(panels),
                    "series": list(chunk),
                    "policy": dict(normalized_split_policy or {}),
                }
            output_base = _veusz_target_base(source, template, panel_index=panel_index)
            outputs, export_records, report, document, spec = _render_veusz_panel(
                source,
                template=template,
                output_dir=output_dir,
                panel_dir=worker_root / (f"panel_{panel_index:02d}" if panel_index else "single"),
                output_base=output_base,
                options=panel_options,
                export_formats=normalized_exports,
                split_panel=split_panel,
            )
            all_outputs.extend(outputs)
            all_exports.extend(export_records)
            reports.append(report)
            documents.append(str(document))
            specs.append(str(spec))

    payload = {
        "kind": "sciplot_render_result",
        "template": template,
        "input": str(input_path),
        "sheet": sheet,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(normalized_exports),
        "exports": all_exports,
        "outputs": [str(path) for path in all_outputs],
        "qa_reports": reports,
        "veusz_documents": documents,
        "veusz_specs": specs,
    }
    if split_plan is not None:
        payload["split_plan"] = json_safe(split_plan)
    return payload


def render_to_dir(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    export_formats: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = validate_template_name(template)
    return _render_to_dir_veusz(
        input_path,
        template=template,
        output_dir=output_dir,
        sheet=sheet,
        options=options,
        export_formats=export_formats,
        split_policy=split_policy,
    )


__all__ = [
    "DEFAULT_EXPORT_FORMATS",
    "DEFAULT_RENDER_ENGINE",
    "inspect_payload",
    "json_safe",
    "render_to_dir",
]
