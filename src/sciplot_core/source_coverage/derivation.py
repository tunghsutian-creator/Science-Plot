"""Remap derived artifacts and build terminal render derivation evidence."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.source_coverage.file_snapshots import (
    _canonical_sha256,
    _assert_snapshot_current,
    _write_private_snapshot,
)

from sciplot_core.source_coverage.terminal_requests import (
    _authoritative_terminal_render_requests,
)


def _remap_derived_source_artifacts(
    records: object,
    *,
    private_to_original: dict[str, dict[str, str]],
    label: str,
) -> list[dict[str, str]]:
    if not isinstance(records, list) or not records:
        raise ValueError(f"{label} has no source artifacts.")
    remapped: list[dict[str, str]] = []
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{label} source artifact {index} is invalid.")
        private_path = str(Path(str(raw.get("path") or "")).expanduser().resolve())
        original = private_to_original.get(private_path)
        if original is None or raw.get("sha256") != original["sha256"]:
            raise ValueError(
                f"{label} consumed an unapproved private terminal snapshot."
            )
        remapped.append(dict(original))
    return sorted(
        remapped,
        key=lambda record: (record["path"], record["sha256"]),
    )


def _terminal_render_derivation(
    *,
    result: dict[str, Any],
    authoritative_request: dict[str, Any],
    declared_requests: list[dict[str, Any]] | None,
    terminal_snapshots: list[dict[str, Any]],
    spec_unit_groups: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    from sciplot_core.studio_render import derive_terminal_render_data_contract

    terminal_outputs = [
        {
            "path": str(snapshot["path"]),
            "sha256": str(snapshot["sha256"]),
        }
        for snapshot in terminal_snapshots
    ]
    snapshot_by_original = {
        str(snapshot["path"]): snapshot for snapshot in terminal_snapshots
    }
    signature_inventory: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix="sciplot_terminal_data_audit_"
    ) as temporary:
        snapshot_root = Path(temporary)
        os.chmod(snapshot_root, 0o700)
        private_to_original: dict[str, dict[str, str]] = {}
        private_by_original: dict[str, Path] = {}
        for index, snapshot in enumerate(terminal_snapshots, start=1):
            source = Path(snapshot["path"])
            private_parent = snapshot_root / f"source_{index:04d}"
            private_parent.mkdir(mode=0o700)
            private_source = private_parent / source.name
            _write_private_snapshot(private_source, snapshot["bytes"])
            original_record = {
                "path": str(source),
                "sha256": str(snapshot["sha256"]),
            }
            private_to_original[str(private_source.resolve())] = original_record
            private_by_original[str(source)] = private_source

        requests = _authoritative_terminal_render_requests(
            result=result,
            authoritative_request=authoritative_request,
            declared_requests=declared_requests,
            private_sources=[
                private_by_original[str(snapshot["path"])]
                for snapshot in terminal_snapshots
            ],
            spec_count=len(spec_unit_groups),
        )
        if len(requests) != len(spec_unit_groups):
            raise ValueError(
                "Terminal render requests and specification groups disagree."
            )
        for request_index, (request, spec_units) in enumerate(
            zip(requests, spec_unit_groups, strict=True),
            start=1,
        ):
            expected_source_paths = sorted(
                {
                    str(record["path"])
                    for unit in spec_units
                    for record in unit["source_artifacts"]
                }
            )
            if not expected_source_paths:
                raise ValueError(
                    f"Veusz specification {request_index} has no terminal "
                    "source inventory."
                )
            if any(path not in snapshot_by_original for path in expected_source_paths):
                raise ValueError(
                    f"Veusz specification {request_index} cites a source "
                    "outside the captured terminal snapshots."
                )
            derived = derive_terminal_render_data_contract(
                request=request,
                terminal_sources=[
                    private_by_original[path] for path in expected_source_paths
                ],
            )
            if (
                derived.get("kind") != "sciplot_terminal_render_data_contract"
                or derived.get("version") != 1
                or derived.get("status") != "passed"
            ):
                raise ValueError("Terminal render-data derivation did not pass.")
            derived_sources = _remap_derived_source_artifacts(
                derived.get("source_artifacts"),
                private_to_original=private_to_original,
                label=f"terminal derivation {request_index}",
            )
            expected_sources = sorted(
                (
                    {
                        "path": path,
                        "sha256": str(snapshot_by_original[path]["sha256"]),
                    }
                    for path in expected_source_paths
                ),
                key=lambda record: (record["path"], record["sha256"]),
            )
            if derived_sources != expected_sources:
                raise ValueError(
                    "Terminal render-data derivation did not consume the exact "
                    "private terminal snapshot inventory."
                )
            derived_units = derived.get("units")
            if (
                not isinstance(derived_units, list)
                or not derived_units
                or derived.get("unit_count") != len(derived_units)
            ):
                raise ValueError(
                    "Terminal render-data derivation has no closed unit inventory."
                )
            for unit_index, unit in enumerate(derived_units, start=1):
                if not isinstance(unit, dict):
                    raise ValueError(
                        "Terminal render-data derivation contains an invalid unit."
                    )
                unit["source_artifacts"] = _remap_derived_source_artifacts(
                    unit.get("source_artifacts"),
                    private_to_original=private_to_original,
                    label=(f"terminal derivation {request_index} unit {unit_index}"),
                )
            signature_fields = (
                "kind",
                "name",
                "label",
                "x_name",
                "y_name",
                "data_name",
                "x_values",
                "y_values",
                "z_values",
                "z_label",
                "scalar_visual",
                "axes",
                "reference_guides",
                "direct_labels",
                "presentation_kind",
                "category_position",
                "plot_line_hide",
                "raw_points_visible",
                "boxplot_eligible",
                "source_artifacts",
            )
            derived_signatures = [
                _canonical_sha256(
                    {
                        field: unit.get(field)
                        for field in signature_fields
                        if field in unit
                    }
                )
                for unit in derived_units
            ]
            spec_signatures = [
                _canonical_sha256(
                    {
                        field: unit.get(field)
                        for field in signature_fields
                        if field in unit
                    }
                )
                for unit in spec_units
            ]
            if spec_signatures != derived_signatures:
                raise ValueError(
                    "Rendered specification data, axes, or ordered series "
                    "identity do not reproduce from the exact terminal "
                    "plotted tables."
                )
            signature_inventory.extend(derived_signatures)
    for index, snapshot in enumerate(terminal_snapshots, start=1):
        _assert_snapshot_current(
            snapshot,
            label=f"terminal plotted data snapshot {index}",
        )
    return {
        "kind": "sciplot_terminal_render_data_derivation",
        "version": 1,
        "status": "passed",
        "request_sha256": _canonical_sha256(requests),
        "terminal_artifacts": terminal_outputs,
        "terminal_artifact_count": len(terminal_outputs),
        "unit_signatures": signature_inventory,
        "unit_count": len(signature_inventory),
    }
