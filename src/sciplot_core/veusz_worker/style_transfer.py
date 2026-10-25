"""Transfer compatible native presentation settings between source revisions."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract.source_identity import scientific_group_binding
from sciplot_core.veusz_worker.style_projection import LEGEND_POSITION_FIELDS, project_transferred_styles


_AXIS_STYLE = (
    "Label/font",
    "Label/size",
    "TickLabels/font",
    "TickLabels/size",
    "Line/width",
    "MajorTicks/width",
    "MinorTicks/width",
)
_XY_STYLE = ("PlotLine/width", "MarkerLine/width", "Label/font", "Label/size")
_XY_COLORS = ("PlotLine/color", "MarkerFill/color", "MarkerLine/color")
_BOX_STYLE = ("Border/width", "Whisker/width")
_BOX_COLORS = ("Fill/color", "Border/color", "Whisker/color")
_TEXT_STYLE = ("Text/font", "Text/size")
_LEGEND_POSITION = LEGEND_POSITION_FIELDS


def _compatibility_reason(
    previous: dict[str, Any], current: dict[str, Any]
) -> str | None:
    if previous.get("template") != current.get("template"):
        return "template_changed"
    for axis in ("x", "y"):
        old = previous.get("axes", {}).get(axis, {})
        new = current.get("axes", {}).get(axis, {})
        if (
            not old
            or not new
            or any(old.get(key) != new.get(key) for key in ("label", "scale", "mode"))
        ):
            return "axis_meaning_or_unit_changed"
    old_request = previous.get("source_request") or {}
    new_request = current.get("source_request") or {}
    if old_request.get("rule_id") != new_request.get("rule_id"):
        return "scientific_rule_changed"
    for key in (
        "figure_id",
        "metric_binding",
        "x_metric",
        "y_metric",
        "conditions",
        "condition_labels",
    ):
        if (old_request.get("resolved_figure_task") or {}).get(key) != (
            new_request.get("resolved_figure_task") or {}
        ).get(key):
            return "figure_task_identity_changed"
    return None


def _series_identity(item: dict[str, Any]) -> tuple[str, str]:
    binding = item.get("source_binding")
    if binding is not None:
        # Pair only a complete scientific correspondence, including the group
        # ID and original category/sample/condition proof. Display edits never
        # establish (or break) this relation.
        proof = scientific_group_binding(binding)
        return "source:" + json.dumps(proof, sort_keys=True, ensure_ascii=False), str(item.get("presentation_kind") or "curve")
    # Full labels retain condition and replicate distinctions. Ambiguous repeated
    # labels are deliberately not paired using their position or dataset name.
    return str(item.get("label") or ""), str(item.get("presentation_kind") or "curve")


def _semantic_colors(spec: dict[str, Any]) -> bool:
    categorical = spec.get("categorical") or {}
    legend = spec.get("legend") or {}
    return bool(
        spec.get("scalar_field")
        or spec.get("performance_comparison")
        or categorical.get("presentation_kind")
        in {"grouped_bar_error", "stacked_components", "point_line_raw_overlay"}
        or legend.get("native_key") is False
    )


def _series_widgets(
    spec: dict[str, Any],
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    series = [item for item in spec.get("series", []) if isinstance(item, dict)]
    counts = Counter(_series_identity(item) for item in series)
    result = {
        _series_identity(item): [(f"/page1/graph1/{item['name']}", "xy")]
        for item in series
        if item.get("label") and counts[_series_identity(item)] == 1
    }
    categorical = spec.get("categorical") or {}
    if categorical.get("native_veusz_boxplot") is True:
        by_y = {str(item.get("y_name")): _series_identity(item) for item in series}
        groups = [
            group
            for group in categorical.get("groups", [])
            if group.get("boxplot_eligible") is True
        ]
        for index, group in enumerate(groups, start=1):
            identity = by_y.get(str(group.get("y_name")))
            if identity in result:
                name = group.get("boxplot_name") or f"categorical_boxplot_{index}"
                result[identity].append((f"/page1/graph1/{name}", "boxplot"))
    return result


def _style_plan(
    previous: dict[str, Any],
    current: dict[str, Any],
    old_widgets: dict[str, dict[str, Any]],
    new_widgets: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reason = _compatibility_reason(previous, current)
    if reason:
        return [], [{"reason": reason}]
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    counts = Counter(_series_identity(item) for item in current.get("series", []))
    for identity, count in counts.items():
        if count > 1:
            skipped.append(
                {
                    "identity": list(identity),
                    "reason": "new_or_ambiguous_series_identity",
                }
            )

    def pair(old_path: str, new_path: str, fields: tuple[str, ...]) -> None:
        old, new = old_widgets.get(old_path), new_widgets.get(new_path)
        if not old or not new or old["type"] != new["type"]:
            skipped.append(
                {
                    "previous_widget": old_path,
                    "current_widget": new_path,
                    "reason": "widget_not_compatible",
                }
            )
            return
        for field in fields:
            if field not in old["settings"] or field not in new["settings"]:
                continue
            before, after = new["settings"][field], old["settings"][field]
            if before != after:
                applied.append(
                    {
                        "previous_widget": old_path,
                        "current_widget": new_path,
                        "setting": field,
                        "before": before,
                        "after": after,
                    }
                )

    old_series, new_series = _series_widgets(previous), _series_widgets(current)
    preserve_colors = not (_semantic_colors(previous) or _semantic_colors(current))
    if not preserve_colors:
        skipped.append({"reason": "semantic_color_encoding_kept_from_new_source"})
    for identity, new_nodes in new_series.items():
        old_nodes = dict((kind, path) for path, kind in old_series.get(identity, []))
        if not old_nodes:
            skipped.append(
                {
                    "identity": list(identity),
                    "reason": "new_or_ambiguous_series_identity",
                }
            )
        for new_path, kind in new_nodes:
            if kind not in old_nodes:
                continue
            styles = _XY_STYLE if kind == "xy" else _BOX_STYLE
            colors = _XY_COLORS if kind == "xy" else _BOX_COLORS
            pair(
                old_nodes[kind], new_path, styles + (colors if preserve_colors else ())
            )

    for path, widget in new_widgets.items():
        kind = widget["type"]
        if kind == "axis":
            pair(path, path, _AXIS_STYLE)
        elif kind == "key":
            pair(path, path, _TEXT_STYLE + ("Border/width",))
            old_key = old_widgets.get(path, {}).get("settings", {})
            legend = previous.get("legend") or {}
            moved = any(
                old_key.get(field) != legend.get(key)
                for field, key in _LEGEND_POSITION.items()
            )
            if moved and set(old_series) == set(new_series):
                pair(path, path, tuple(_LEGEND_POSITION))
            else:
                skipped.append(
                    {"current_widget": path, "reason": "new_source_legend_layout_kept"}
                )
        elif kind == "label":
            old = old_widgets.get(path)
            if old and old["settings"].get("label") == widget["settings"].get("label"):
                pair(path, path, _TEXT_STYLE)
    geometry_types = {widget["type"] for widget in new_widgets.values()} & {
        "bar",
        "line",
        "rect",
        "polygon",
        "image",
        "contour",
    }
    if geometry_types:
        skipped.append(
            {
                "reason": "scientific_geometry_style_kept_from_new_source",
                "widget_types": sorted(geometry_types),
            }
        )
    return applied, skipped


def transfer_document_styles(
    previous: Path, current: Path, previous_spec: Path, current_spec: Path, *,
    output_document: Path | None = None, output_spec: Path | None = None,
) -> dict[str, Any]:
    """Copy safe presentation only; validate science before atomic replacement."""

    previous, current, previous_spec, current_spec = (
        path.expanduser().resolve(strict=True)
        for path in (previous, current, previous_spec, current_spec)
    )
    if previous == current:
        raise ValueError(
            "Style transfer requires separate previous and current documents."
        )
    old_spec = json.loads(previous_spec.read_text(encoding="utf-8"))
    new_spec = json.loads(current_spec.read_text(encoding="utf-8"))
    if not isinstance(old_spec, dict) or not isinstance(new_spec, dict):
        raise ValueError("Style transfer requires two generated specification objects.")
    hashes = {
        str(path): file_sha256(path)
        for path in (previous, current, previous_spec, current_spec)
    }
    if (output_document is None) != (output_spec is None):
        raise ValueError("A private style preview requires both output paths")
    if output_document is not None and output_spec is not None:
        output_document, output_spec = output_document.absolute(), output_spec.absolute()
        if output_document.parent != output_spec.parent or output_document == output_spec:
            raise ValueError("A private style preview requires two distinct sibling outputs")
        if any(path.exists() or path.is_symlink() for path in (output_document, output_spec)):
            raise ValueError("Private style outputs must be fresh exclusive files")
        for parent in (output_document.parent, *output_document.parent.parents):
            if (parent / ".sciplot_store").exists() or (parent / "plot_request.json").exists():
                raise ValueError("Style preview outputs must remain outside active native projects")
        output_document.parent.mkdir(parents=True, exist_ok=True)
    reason = _compatibility_reason(old_spec, new_spec)
    payload: dict[str, Any] = {
        "kind": "sciplot_document_style_transfer",
        "version": 1,
        "status": "passed",
        "previous": str(previous),
        "current": str(current),
        "input_sha256": hashes,
        "applied": [],
        "skipped": [],
        "applied_count": 0,
    }
    if reason:
        payload.update(
            transfer_status="skipped",
            skipped=[{"reason": reason}],
            document_sha256=hashes[str(current)],
        )
        if output_document is not None and output_spec is not None:
            _copy_private_pair(current, current_spec, output_document, output_spec, hashes)
        return payload

    from PyQt6 import QtWidgets
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
    from sciplot_core.veusz_worker.spec_audit import audit_spec_data
    from sciplot_core.studio_core.style_transfer_storage import save_transferred_style_pair

    ensure_veusz_runtime_path()
    ensure_veusz_loader_compat()
    document = import_module("veusz.document")
    import_module("veusz.dataimport")
    import_module("veusz.widgets")
    CommandInterface = document.CommandInterface
    existing = QtWidgets.QApplication.instance()
    app = existing or QtWidgets.QApplication([])
    try:
        audit_spec_data(previous, previous_spec, check_presentation=False)
        audit_spec_data(current, current_spec, check_presentation=False)
        docs, states = [], []
        for path in (previous, current):
            loaded = document.Document()
            loaded.load(
                str(path),
                callbackunsafe=lambda: False,
                callbackimporterror=lambda *_args: False,
            )
            interface = CommandInterface(loaded)
            state: dict[str, dict[str, Any]] = {}

            def collect(
                widget_path: str,
                node: Any,
                *,
                current_interface: Any = interface,
                target_state: dict[str, dict[str, Any]] = state,
            ) -> None:
                from sciplot_core.veusz_worker.widget_bindings import _settings_snapshot

                settings = _settings_snapshot(node.settings)
                current_interface.To(widget_path)
                target_state[widget_path] = {
                    "type": str(node.typename),
                    "settings": {
                        key: deepcopy(current_interface.Get(key))
                        for key in settings
                        if key
                        in set(
                            _AXIS_STYLE
                            + _XY_STYLE
                            + _XY_COLORS
                            + _BOX_STYLE
                            + _BOX_COLORS
                            + _TEXT_STYLE
                            + tuple(_LEGEND_POSITION)
                            + ("label",)
                        )
                    },
                }

            loaded.walkNodes(collect, nodetypes=("widget",))
            docs.append(loaded)
            states.append(state)
        applied, skipped = _style_plan(old_spec, new_spec, states[0], states[1])
        interface = CommandInterface(docs[1])
        for operation in applied:
            interface.To(operation["current_widget"])
            interface.Set(operation["setting"], operation["after"])
        if any(file_sha256(Path(path)) != digest for path, digest in hashes.items()):
            raise ValueError(
                "Style-transfer input changed while its native documents were loaded."
            )
        if output_document is not None and output_spec is not None:
            if applied:
                from sciplot_core.studio_core.style_transfer_storage import stage_transferred_style_pair

                payload["save"] = stage_transferred_style_pair(docs[1], current, current_spec,
                    project_transferred_styles(new_spec, applied), output_document=output_document,
                    output_spec=output_spec, input_hashes=hashes)
            else:
                _copy_private_pair(current, current_spec, output_document, output_spec, hashes)
        elif applied:
            payload["save"] = save_transferred_style_pair(
                docs[1], current, current_spec, project_transferred_styles(new_spec, applied),
                input_hashes=hashes,
            )
        payload.update(
            applied=applied,
            skipped=skipped,
            applied_count=len(applied),
            transfer_status="applied" if applied else "unchanged",
            document_sha256=file_sha256(output_document or current),
        )
        return payload
    finally:
        if existing is None:
            app.quit()


def _copy_private_pair(current: Path, current_spec: Path, output_document: Path,
                       output_spec: Path, hashes: dict[str, str]) -> None:
    data = current.read_bytes(), current_spec.read_bytes()
    if any(file_sha256(Path(path)) != digest for path, digest in hashes.items()):
        raise ValueError("Style-transfer input changed before its private preview")
    with output_document.open("xb") as stream:
        stream.write(data[0])
    with output_spec.open("xb") as stream:
        stream.write(data[1])
    output_document.chmod(current.stat().st_mode & 0o777)
    output_spec.chmod(current_spec.stat().st_mode & 0o777)


__all__ = ["transfer_document_styles"]
