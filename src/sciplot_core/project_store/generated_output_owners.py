"""Authenticate generated destination roles from existing sealed business facts."""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from sciplot_core.project_commands import ProjectionRead
from sciplot_core.project_commands.read_projections import projection_digest
from .errors import ProjectConflict
from .io import StoreIO
from .locators import logical_for_literal


def logical(current: dict[str, Any], literal: str) -> str | None:
    path = PurePosixPath(literal)
    if not path.is_absolute():
        return literal if literal in current["files"] else None
    return logical_for_literal(current, literal)


def _exports(value: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(value.get("exports", [])) if isinstance(value.get("exports"), list) else []
    package = value.get("delivery_package")
    if isinstance(package, dict) and isinstance(package.get("figures"), list):
        rows.extend(package["figures"])
    return [item for item in rows if isinstance(item, dict)]


def receipt_matches(current: dict[str, Any], name: str, receipt: dict[str, Any]) -> bool:
    """Only named rendered media, not every member written by its producer."""
    suffixes = {"pdf": ".pdf", "tiff_300": ".tiff", "tiff_600": ".tiff", "png_300": ".png"}
    if name.startswith("runs/"):
        return False  # Run snapshots are immutable publication evidence.
    for row in _exports(receipt):
        format_name = row.get("format")
        suffix = suffixes.get(format_name) if isinstance(format_name, str) else None
        if suffix is None or not name.endswith(suffix) or row.get("sha256") != current["files"][name]["sha256"]:
            continue
        paths = [row.get("path")]
        if receipt.get("kind") == "sciplot_studio_export_run":
            paths.append(row.get("source"))  # The sealed run names its canonical render source too.
        if any(isinstance(path, str) and logical(current, path) == name for path in paths):
            return True
    return False


def catalog_matches(io: StoreIO, current: dict[str, Any], name: str, selector: ProjectionRead) -> bool:
    if selector.kind != "native_suite_figure_v1" or selector.resource not in {"suite.json", "@delivery/data/delivery_manifest.json"}:
        return False
    entry = current["files"].get(selector.resource)
    if entry is None:
        return False
    data = io.get(entry)
    if projection_digest(data, kind=selector.kind, key=selector.key) != selector.sha256:
        raise ProjectConflict("The generated output catalog selection changed.")
    value = json.loads(data)
    from sciplot_core.project_commands.native_suite_projections import _selected
    selected = _selected(value["documents"], selector.key)
    base = _selected(value["native_result"]["figures"], selector.key)
    overlay = _selected(value.get("last_export", []), selector.key, exported=True)
    receipt = overlay if overlay is not None else base
    if selected is None:
        return False
    if (receipt is None or receipt.get("document_sha256") != selected["sha256"]
            or name not in {logical(current, path) for path in selected["exports"]}):
        return False
    rows = _exports(receipt)
    if len(rows) != 3 or {row.get("format") for row in rows} != {"pdf", "tiff_300", "png_300"}:
        return False
    if receipt_matches(current, name, receipt):
        return True
    # Creation receipts bind the exact initial-render path, while the selected
    # catalog binds its exact installed destination; this is one fixed mapping.
    suffixes = {"pdf": ".pdf", "tiff_300": "_300dpi.tiff", "png_300": "_300dpi.png"}
    for row in _exports(receipt):
        format_name = row.get("format")
        suffix = suffixes.get(format_name) if isinstance(format_name, str) else None
        if suffix is None:
            continue
        initial = PurePosixPath(value["workspace"]) / "initial_render" / (selector.key + suffix)
        visible = PurePosixPath(value["delivery"]) / ("SI" if selector.key.startswith("SI_") else
            "" if selector.key.startswith("Figure_X") else "panels") / (selector.key + suffix)
        if (row.get("path") == str(initial) and logical(current, str(visible)) == name
                and row.get("sha256") == current["files"][name]["sha256"]):
            return True
    return False
