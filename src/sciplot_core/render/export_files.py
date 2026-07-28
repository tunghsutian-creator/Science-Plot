"""Copy, validate, and clean terminal renderer exports."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from sciplot_core.render.formats import (
    _EXPORT_FORMATS,
    _export_path,
)


def _copy_veusz_exports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    output_base: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    outputs: list[Path] = []
    export_records: list[dict[str, Any]] = []
    raw_exports = payload.get("exports")
    if not isinstance(raw_exports, list):
        raise RuntimeError("Veusz export response must contain an `exports` list.")
    for index, item in enumerate(raw_exports):
        if not isinstance(item, dict):
            raise RuntimeError(f"Veusz export record {index} is not an object.")
        source_value = item.get("path")
        fmt = str(item.get("format") or "").strip().lower()
        if not isinstance(source_value, str) or not source_value.strip():
            raise RuntimeError(f"Veusz export record {index} has no artifact path.")
        if fmt not in _EXPORT_FORMATS:
            raise RuntimeError(
                f"Veusz export record {index} has unsupported format `{fmt or 'missing'}`."
            )
        source = Path(source_value).expanduser()
        if not source.is_file() or source.stat().st_size <= 0:
            raise RuntimeError(
                f"Veusz reported a missing or empty `{fmt}` export: {source}"
            )
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


def _validate_export_records(
    records: list[dict[str, Any]], *, requested: tuple[str, ...]
) -> None:
    received = tuple(str(record.get("format") or "") for record in records)
    if Counter(received) == Counter(requested):
        return
    missing = list((Counter(requested) - Counter(received)).elements())
    unexpected = list((Counter(received) - Counter(requested)).elements())
    raise RuntimeError(
        "Veusz export response does not match the requested format set: "
        f"missing={missing or 'none'}, unexpected={unexpected or 'none'}."
    )


def _remove_stale_render_exports(
    output_dir: Path,
    *,
    source_stem: str,
    template: str,
    keep: set[Path] | None = None,
) -> None:
    base = re.escape(f"{source_stem}_{template}")
    generated_name = re.compile(
        rf"^{base}(?:_part\d{{2}})?(?:_(?:300|600)dpi)?\.(?:pdf|svg|png|tiff)$",
        flags=re.IGNORECASE,
    )
    if not output_dir.is_dir():
        return
    retained = {path.expanduser().resolve() for path in (keep or set())}
    for path in output_dir.iterdir():
        if (
            path.is_file()
            and generated_name.fullmatch(path.name)
            and path.resolve() not in retained
        ):
            path.unlink()


def _cleanup_worker_exports(panel_dir: Path) -> None:
    for path in (panel_dir / "studio" / "exports", panel_dir / "runs"):
        if path.exists():
            shutil.rmtree(path)
