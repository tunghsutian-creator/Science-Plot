"""Copy, validate, and clean terminal renderer exports."""

from __future__ import annotations

import shutil
from collections import Counter
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.policy.export_formats import export_suffix
from sciplot_core.policy.frame_export import CANONICAL_EXPORT_FORMATS


def _export_destination(output_dir: Path, output_base: str, fmt: str) -> Path:
    suffix, _dpi = export_suffix(fmt)
    return output_dir / (Path(f"{output_base}.pdf").stem + suffix)


def _require_new_render_path(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Render target already exists: {path}. Choose a new output directory.")


class PartialRenderError(OSError):
    """An unsuccessful terminal render left some completed outputs in place."""

    reason_code = "partial_terminal_render"

    def __init__(self, installed: list[Path], cause: Exception) -> None:
        paths = [str(path.absolute()) for path in installed]
        self.diagnostics = {"installed_outputs": paths}
        super().__init__(
            f"Render stopped after writing {len(paths)} output(s). "
            f"Use a new output directory to retry. Cause: {cause}"
        )


@contextmanager
def _report_partial_render(installed: list[Path]) -> Iterator[None]:
    try:
        yield
    except Exception as cause:
        if installed:
            raise PartialRenderError(installed, cause) from cause
        raise


def _copy_veusz_exports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    output_base: str,
    installed: list[Path] | None = None,
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
        if fmt not in CANONICAL_EXPORT_FORMATS:
            raise RuntimeError(
                f"Veusz export record {index} has unsupported format `{fmt or 'missing'}`."
            )
        source = Path(source_value).expanduser()
        if not source.is_file() or source.stat().st_size <= 0:
            raise RuntimeError(
                f"Veusz reported a missing or empty `{fmt}` export: {source}"
            )
        destination = _export_destination(output_dir, output_base, fmt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".sciplot-export-", dir=destination.parent) as staging:
            candidate = Path(staging) / destination.name
            shutil.copy2(source, candidate)
            install_new_delivery(candidate, destination)
            if installed is not None:
                installed.append(destination)
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


def _cleanup_worker_exports(panel_dir: Path) -> None:
    for path in (panel_dir / "studio" / "exports", panel_dir / "runs"):
        if path.exists():
            shutil.rmtree(path)
