from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core.semantic import classify_source

ensure_legacy_core()

from src.plot_style import save_pdf  # noqa: E402
from src.rendering.recommendation import inspect_input_file  # noqa: E402
from src.rendering.render_service import (  # noqa: E402
    build_rendered_plots,
    close_rendered_plots,
    export_rendered_plots,
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

DEFAULT_EXPORT_FORMATS = ("pdf", "tiff_300")


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def inspect_payload(input_path: Path, *, sheet: str | int = 0) -> dict[str, Any]:
    payload = json_safe(inspect_input_file(input_path, sheet))
    payload["sciplot_semantics"] = json_safe(
        classify_source(input_path, sheet=sheet, vendor_inspection=payload),
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


def _export_rendered_plots(
    rendered: list[Any],
    output_dir: Path,
    export_formats: tuple[str, ...],
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if export_formats == ("pdf",):
        outputs = export_rendered_plots(rendered, output_dir, close=False)
        return outputs, [{"path": str(path), "format": "pdf", "dpi": None} for path in outputs]

    outputs: list[Path] = []
    export_records: list[dict[str, Any]] = []
    for plot in rendered:
        for export_format in export_formats:
            target_format, dpi, _suffix = _EXPORT_FORMATS[export_format]
            path = _export_path(plot.filename, output_dir, export_format)
            if target_format == "pdf":
                save_pdf(plot.figure, path)
            else:
                plot.figure.savefig(path, format=target_format, dpi=dpi, bbox_inches=None, pad_inches=0.0)
            outputs.append(path)
            export_records.append({"path": str(path), "format": export_format, "dpi": dpi})
    return outputs, export_records


def render_to_dir(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    export_formats: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    options = dict(options or {})
    normalized_exports = _normalize_export_formats(export_formats)
    rendered = build_rendered_plots(template, input_path, sheet, **options)
    try:
        outputs, export_records = _export_rendered_plots(rendered, output_dir, normalized_exports)
        return {
            "template": template,
            "input": str(input_path),
            "sheet": sheet,
            "export_formats": list(normalized_exports),
            "exports": export_records,
            "outputs": [str(path) for path in outputs],
            "qa_reports": [json_safe(plot.qa_report) for plot in rendered],
        }
    finally:
        close_rendered_plots(rendered)


__all__ = ["DEFAULT_EXPORT_FORMATS", "inspect_payload", "json_safe", "render_to_dir"]
