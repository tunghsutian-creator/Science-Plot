"""Copy verified Studio exports into an immutable run directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256

from sciplot_core.studio_core.runtime import (
    _export_suffix,
    _normalize_export_format,
)


def copy_studio_run_exports(
    *,
    exports: list[dict[str, Any]],
    output_dir: Path,
    figure_set_export_scope: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Verify source hashes and copy each export under the run's figures tree."""

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    copied_exports: list[dict[str, Any]] = []
    figures: list[str] = []
    for item in exports:
        source = _verified_export_source(item)
        expected_hash = str(item.get("sha256") or "")
        figure_id = str(item.get("figure_id") or "").strip()
        if isinstance(figure_set_export_scope, dict) and figure_id:
            export_suffix, _dpi = _export_suffix(
                _normalize_export_format(str(item.get("format") or ""))
            )
            destination = figures_dir / f"{figure_id}{export_suffix}"
        else:
            destination = figures_dir / source.name
        shutil.copy2(source, destination)
        if existing_file_sha256(destination) != expected_hash:
            raise RuntimeError(f"Copied project export hash mismatch: {destination}")
        copied_exports.append(
            {
                **item,
                "source": str(source),
                "path": str(destination),
                "relative_path": str(destination.relative_to(output_dir)),
                "sha256": expected_hash,
            }
        )
        figures.append(str(destination))
    return copied_exports, figures


def _verified_export_source(item: dict[str, Any]) -> Path:
    source_value = item.get("path")
    if not isinstance(source_value, str) or not source_value.strip():
        raise RuntimeError("A project export record has no artifact path.")
    source = Path(source_value).expanduser()
    if not source.exists() or not source.is_file():
        raise RuntimeError(f"A project export disappeared before packaging: {source}")
    expected_hash = str(item.get("sha256") or "")
    if not expected_hash or existing_file_sha256(source) != expected_hash:
        raise RuntimeError(
            f"A project export changed before it could be copied into the run: {source}"
        )
    return source
