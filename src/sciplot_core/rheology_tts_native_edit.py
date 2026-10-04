"""Conflict-checked native candidates for resolved TTS presentation changes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_presentation_audit import (
    expected_fields_equal,
    field_matches,
    native_series_fields,
    native_legend_position_fields,
    read_native_field,
    set_native_field,
)


def _matching_series(
    old: dict[str, Any], new: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]]:
    if old["id"] != new["id"] or len(old["panels"]) != len(new["panels"]):
        raise ValueError("Restyle cannot change the figure or panel inventory.")
    if any(old[key] != new[key] for key in ("width_mm", "height_mm")):
        raise ValueError("Restyle cannot change figure dimensions.")
    pairs = []
    for old_panel, new_panel in zip(old["panels"], new["panels"], strict=True):
        if old_panel["id"] != new_panel["id"] or len(old_panel["series"]) != len(
            new_panel["series"]
        ):
            raise ValueError("Restyle cannot change panel or series identities.")
        if any(
            old_panel.get(key) != new_panel.get(key)
            for key in (
                "rect_mm",
                "axes",
                "title",
                "notes",
                "reference_lines",
                "standard_frame",
                "x_tick_labels",
            )
        ):
            raise ValueError("Restyle cannot change axes, titles or panel layout.")
        if bool(old_panel["legend"]) != bool(new_panel["legend"]):
            raise ValueError("Restyle cannot add or remove a native legend widget.")
        for before, after in zip(old_panel["series"], new_panel["series"], strict=True):
            if any(
                before[key] != after[key]
                for key in ("name", "kind", "bar_width", "x_name", "y_name")
            ):
                raise ValueError(
                    "Restyle cannot change source-bound series names, kinds or dataset bindings."
                )
            if any(
                not np.array_equal(before[f"{axis}_values"], after[f"{axis}_values"])
                for axis in ("x", "y")
            ):
                raise ValueError(
                    "Restyle cannot change source-bound numeric coordinates."
                )
            if not np.array_equal(
                before.get("error_values", []), after.get("error_values", [])
            ):
                raise ValueError(
                    "Restyle cannot change source-bound uncertainty coordinates."
                )
            pairs.append((old_panel, new_panel, before, after))
    return pairs


def _presentation_targets(old_figure: dict, new_figure: dict, pairs: list):
    for old_panel, new_panel, before, after in pairs:
        yield (
            f"/page1/{old_panel['id']}/{before['name']}",
            native_series_fields(before, old_panel),
            native_series_fields(after, new_panel),
        )
    for old_panel, new_panel in zip(
        old_figure["panels"], new_figure["panels"], strict=True
    ):
        if old_panel["legend"] == new_panel["legend"]:
            continue
        if str(new_panel["legend"]).strip().casefold() not in {
            "upper_left",
            "top_left",
            "upper_right",
            "top_right",
            "lower_left",
            "bottom_left",
            "lower_right",
            "bottom_right",
            "inside_best",
        }:
            raise ValueError(
                "Restyle legend position requires a supported named corner."
            )
        yield (
            f"/page1/{old_panel['id']}/key1",
            native_legend_position_fields(old_panel["legend"]),
            native_legend_position_fields(new_panel["legend"]),
        )


def restyle_native_document(
    path: Path,
    out_path: Path,
    old_figure: dict[str, Any],
    new_figure: dict[str, Any],
    expected_sha256: str,
) -> dict[str, Any]:
    """Preserve the original; write only changed, conflict-free style targets."""
    from veusz import document
    from veusz.document import CommandInterface
    from sciplot_core.rheology_tts_native import audit_native_figure

    if path.resolve() == out_path.resolve():
        raise ValueError(
            "Restyle requires a distinct candidate path; the current document is preserved."
        )
    if out_path.exists():
        raise FileExistsError(
            "Restyle candidate already exists; no file was overwritten."
        )
    if file_sha256(path) != expected_sha256:
        raise ValueError(
            "Current native document SHA differs from the expected revision; restyle is stale."
        )
    pairs = _matching_series(old_figure, new_figure)
    baseline_audit = audit_native_figure(path, old_figure, check_presentation=False)
    doc = document.Document()
    doc.load(str(path))
    doc._sciplot_write_full_precision = True
    interface = CommandInterface(doc)
    changes = []
    targets = []
    # Validate every target before mutating the in-memory candidate.
    for native_path, old_fields, new_fields in _presentation_targets(
        old_figure, new_figure, pairs
    ):
        interface.To(native_path)
        if set(old_fields) != set(new_fields):
            raise ValueError(
                "Restyle cannot change the native presentation field inventory."
            )
        for name, new_field in new_fields.items():
            old_field = old_fields[name]
            if expected_fields_equal(old_field, new_field):
                continue
            actual = read_native_field(interface, name, old_field)
            if not field_matches(actual, old_field):
                raise ValueError(
                    f"Native style conflict at {native_path} {name}: current {actual!r} differs from old expected {old_field['value']!r}; existing native edit was preserved."
                )
            targets.append((native_path, name, new_field))
            changes.append(
                {
                    "widget_path": native_path,
                    "field": name,
                    "before": actual,
                    "old_expected": old_field["value"],
                    "after_expected": new_field["value"],
                    "comparison": new_field["kind"],
                }
            )
    for native_path, name, field in targets:
        interface.To(native_path)
        set_native_field(interface, name, field)
    if file_sha256(path) != expected_sha256:
        raise ValueError("Current native document changed during restyle preparation.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusively reserve the candidate so even a concurrent creation is retained.
    with out_path.open("xb"):
        pass
    try:
        interface.Save(str(out_path))
        candidate_audit = audit_native_figure(
            out_path, new_figure, check_presentation=False
        )
        candidate = document.Document()
        candidate.load(str(out_path))
        candidate_interface = CommandInterface(candidate)
        for native_path, name, field in targets:
            candidate_interface.To(native_path)
            actual = read_native_field(candidate_interface, name, field)
            if not field_matches(actual, field):
                raise ValueError(
                    f"Restyle candidate did not retain changed field: {native_path} {name}."
                )
        if file_sha256(path) != expected_sha256:
            raise ValueError(
                "Current native document changed during candidate save; candidate rejected."
            )
        candidate_sha = file_sha256(out_path)
        candidate_audit.update(document=str(out_path), document_sha256=candidate_sha)
        candidate_audit["changed_presentation"] = {
            "status": "passed",
            "changed_field_count": len(changes),
            "scope": "Only compiled old-to-new target changes enforced; unrelated native settings retained.",
        }
        return {
            "kind": "sciplot_rheology_tts_restyle_candidate",
            "version": 1,
            "status": "candidate_ready",
            "source_document": str(path),
            "source_document_sha256": expected_sha256,
            "document": str(out_path),
            "document_sha256": candidate_sha,
            "changes": changes,
            "baseline_audit": baseline_audit,
            "candidate_audit": candidate_audit,
        }
    except Exception:
        out_path.unlink(missing_ok=True)
        raise
