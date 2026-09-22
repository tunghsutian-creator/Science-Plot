"""Keep semantic color and shape encodings outside external native style edits."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


SAMPLE_STYLE_FIELDS = {"color": "PlotLine/color", "width": "PlotLine/width"}
_CURVE_SHAPE_SUFFIXES = ("PlotLine/style", "PlotLine/transparency", "marker", "markerSize", "MarkerLine/hide", "MarkerFill/hide")


def ordinary_curve_paths(spec: dict[str, Any]) -> set[str]:
    """Allow only explicit ordinary-series contracts in the generated spec."""
    if not isinstance(spec, dict):
        raise ValueError("A generated figure specification object is required.")
    # veusz_spec_builder emits null for absent scalar/categorical contracts.
    # An empty or unfamiliar contract must not silently become ordinary styling.
    if (
        spec.get("template") not in {"curve", "point_line", "stacked_curve"}
        or any(spec.get(key) is not None for key in (
            "scalar_field", "performance_comparison", "categorical",
        ))
    ):
        return set()
    legend = spec.get("legend")
    if legend is not None and (
        not isinstance(legend, dict) or legend.get("native_key") is False
    ):
        return set()
    series = spec.get("series")
    if not isinstance(series, list) or not all(isinstance(item, dict) for item in series):
        return set()
    names = Counter(str(item.get("name")) for item in series)
    return {
        f"/page1/graph1/{item['name']}"
        for item in series
        if item.get("presentation_kind") == "curve"
        and isinstance(item.get("name"), str)
        and item["name"] not in {"", ".", ".."}
        and "/" not in item["name"]
        and names[item["name"]] == 1
    }


def sample_color_settings(spec: dict[str, Any]) -> dict[str, list[str]]:
    """Bind color companions by the generated series/direct-label contract."""
    allowed = ordinary_curve_paths(spec)
    if not allowed:
        return {}
    labels = spec.get("direct_labels") or []
    names = Counter(item["name"] for item in labels
                    if isinstance(item, dict) and isinstance(item.get("name"), str))
    result = {}
    for index, series in enumerate(spec.get("series") or [], 1):
        if not isinstance(series, dict):
            continue
        path = f"/page1/graph1/{series.get('name')}"
        if path not in allowed:
            continue
        # Native users can enable markers after creation; the immutable generated
        # spec's initial marker is not the current presentation authority.
        settings = [path + "/PlotLine/color", path + "/MarkerFill/color", path + "/MarkerLine/color"]
        name = f"label_{index}"
        if names[name] == 1 and any(isinstance(item, dict) and item.get("name") == name
                                  and item.get("label") == series.get("label") for item in labels):
            settings.append(f"/page1/graph1/{name}/Text/color")
        result[path] = settings
    return result


def _is_sample_color(setting_path: Any) -> bool:
    return isinstance(setting_path, str) and setting_path.endswith((
        "/PlotLine/color", "/MarkerFill/color", "/MarkerLine/color", "/Text/color"))


def _curve_shape_target(object_path: Any, setting_path: Any) -> bool:
    return isinstance(object_path, str) and any(
        setting_path == f"{object_path}/{suffix}" for suffix in _CURVE_SHAPE_SUFFIXES
    )


def _is_curve_shape(setting_path: Any) -> bool:
    return isinstance(setting_path, str) and setting_path.endswith(
        tuple(f"/{suffix}" for suffix in _CURVE_SHAPE_SUFFIXES)
    )


def filter_editable_fields(
    objects: dict[str, dict[str, Any]], spec_path: Path,
) -> dict[str, dict[str, Any]]:
    """Return native objects with unproven color and shape edits removed."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    curves = ordinary_curve_paths(spec)
    allowed = {setting for settings in sample_color_settings(spec).values()
               for setting in settings}
    return {
        path: {
            **widget,
            "editable_fields": [
                dict(field)
                for field in widget.get("editable_fields", [])
                if (
                    not _is_sample_color(field.get("setting_path"))
                    or (
                        widget.get("type") in {"xy", "label"} and field["setting_path"] in allowed
                        and field["setting_path"].rsplit("/", 2)[0] == path
                    )
                ) and (
                    not _is_curve_shape(field.get("setting_path"))
                    or (widget.get("type") == "xy" and path in curves
                        and _curve_shape_target(path, field.get("setting_path")))
                ) and (
                    field.get("setting_path") != "/page1/graph1/y/hide"
                    or (bool(curves) and widget.get("type") == "axis" and path == "/page1/graph1/y")
                )
            ],
        }
        for path, widget in objects.items()
    }


def validate_edit_science_policy(
    changes: list[dict[str, Any]], spec_path: Path,
) -> None:
    """Apply the same rule at submission; advertised permissions are not proof."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    curves = ordinary_curve_paths(spec)
    allowed = {setting for settings in sample_color_settings(spec).values()
               for setting in settings}
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Each native setting change must be an object.")
        path = change.get("object_path")
        setting = change.get("setting_path")
        if setting == "/page1/graph1/y/hide" and (not curves or path != "/page1/graph1/y"):
            raise ValueError("Y-axis visibility editing requires a bound ordinary Cartesian curve.")
        if _is_curve_shape(setting) and (
            not isinstance(path, str) or path not in curves
            or not _curve_shape_target(path, setting)
        ):
            raise ValueError(
                "Line and marker styles require a uniquely bound ordinary curve. "
                "Scalar, performance and categorical encodings must remain unchanged."
            )
        if _is_sample_color(setting) and (
            not isinstance(path, str) or setting not in allowed
            or setting.rsplit("/", 2)[0] != path
        ):
            raise ValueError(
                "Sample color editing requires a uniquely bound ordinary curve. "
                "Scalar, performance, categorical and condition color encodings "
                "must remain unchanged; inspect the available font or line-width settings."
            )


__all__ = ["filter_editable_fields", "validate_edit_science_policy"]
