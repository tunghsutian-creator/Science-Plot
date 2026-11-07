"""Probe canonical visible delivery layout and hashes."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sciplot_core.delivery.runtime_evidence import recorded_editor_launcher_current, recorded_delivery_identity, recorded_legacy_veusz_current
from sciplot_core.launchers import inspect_delivery_editor_launcher_contract, inspect_delivery_launcher_contract


def _delivery_layout_probe(delivery: dict[str, Any]) -> dict[str, Any]:
    """Verify the small user-facing delivery surface and its CSV contract."""

    delivery_path = Path(str(delivery.get("path") or "")).expanduser().resolve()
    identity_checks, identity_probe, identity_name = recorded_delivery_identity(delivery, delivery_path)
    expected_entries = {"data", "figures", "project", identity_name}
    editor_recorded = any(key in delivery for key in (
        "open_in_sciplot", "open_in_sciplot_sha256", "editor_launcher_contract"))
    if editor_recorded:
        expected_entries.add("Open_in_SciPlot.command")
    native_legacy_recorded = delivery.get("version") == 7 and "legacy_veusz_launcher" in delivery
    if native_legacy_recorded:
        expected_entries.add("Open_in_Veusz.command")
    actual_entries = (
        {path.name for path in delivery_path.iterdir()}
        if delivery_path.is_dir()
        else set()
    )
    forbidden_names = {
        "_sciplot_internal",
        "editable",
        "pdf",
        "tiff",
        "README.md",
        ".sciplot",
        "manifest.json",
        "raw",
        "tables",
    }
    forbidden_paths = (
        [
            str(path)
            for path in delivery_path.rglob("*")
            if path.name in forbidden_names
            or path.suffix.casefold() in {".xlsx", ".xls", ".sciplot"}
        ]
        if delivery_path.is_dir()
        else []
    )

    data_records = (
        delivery.get("data_csvs") if isinstance(delivery.get("data_csvs"), list) else []
    )
    data_checks: list[dict[str, Any]] = []
    for record in data_records:
        path = (
            Path(str(record.get("path") or "")) if isinstance(record, dict) else Path()
        )
        rows: list[list[str]] = []
        if path.is_file():
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        data_checks.append(
            {
                "path": str(path),
                "under_data": path.parent == delivery_path / "data",
                "row_count": len(rows),
                "four_row_header": len(rows) >= 4
                and all(rows[index] for index in range(3)),
                "data_rows": max(len(rows) - 3, 0),
                "column_count": len(rows[0]) if rows else 0,
            }
        )

    figure_records = (
        delivery.get("figures") if isinstance(delivery.get("figures"), list) else []
    )
    figure_locations = [
        {
            "path": str(record.get("path")),
            "format": record.get("format"),
            "in_expected_folder": (
                Path(str(record.get("path") or "")).parent == delivery_path / "figures"
            ),
        }
        for record in figure_records
        if isinstance(record, dict)
    ]
    project_records = delivery.get("project_documents")
    project_records = project_records if isinstance(project_records, list) else []
    project_locations = [
        {
            "path": str(record.get("path")),
            "in_project": Path(str(record.get("path") or "")).parent
            == delivery_path / "project",
            "exists": bool(record.get("exists")),
        }
        for record in project_records
        if isinstance(record, dict)
    ]

    editor_probe = inspect_delivery_editor_launcher_contract(delivery_path) if editor_recorded else None
    editor_current = editor_probe is None or recorded_editor_launcher_current(
        delivery, expected_root=delivery_path, contract=editor_probe)

    native_legacy_probe = inspect_delivery_launcher_contract(delivery_path) if native_legacy_recorded else None
    native_legacy_current = native_legacy_probe is None or recorded_legacy_veusz_current(
        delivery, expected_root=delivery_path, contract=native_legacy_probe)

    passed = (
        delivery_path.is_dir()
        and actual_entries == expected_entries
        and not forbidden_paths
        and bool(data_checks)
        and all(
            item["under_data"]
            and item["four_row_header"]
            and item["data_rows"] > 0
            and item["column_count"] > 0
            for item in data_checks
        )
        and bool(figure_locations)
        and all(item["in_expected_folder"] for item in figure_locations)
        and bool(project_locations)
        and all(item["in_project"] and item["exists"] for item in project_locations)
        and all(identity_checks.values())
        and editor_current
        and native_legacy_current
    )
    return {
        "passed": passed,
        "delivery_path": str(delivery_path),
        "expected_entries": sorted(expected_entries),
        "actual_entries": sorted(actual_entries),
        "forbidden_paths": forbidden_paths,
        "data": data_checks,
        "figures": figure_locations,
        "projects": project_locations,
        "identity": identity_probe,
        "legacy_editor_launcher": editor_probe,
        "legacy_veusz_launcher": native_legacy_probe,
    }
