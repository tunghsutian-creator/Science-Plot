"""Compare scientific figure contents before a reviewed source replacement."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set


def payload_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def project_figures(project: Path) -> dict[str, tuple[Path, Path]]:
    request_path = project / "plot_request.json"
    request = json.loads(request_path.read_text()) if request_path.is_file() else {}
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    registry = _read_studio_figure_set(
        project, expected_plan=plan, require_ready_artifacts=True
    )
    if registry is None:
        if (project / "studio" / "figure_set.json").exists() or plan is not None:
            raise ValueError(
                "Repair the missing, corrupt, or inconsistent figure-set registry before updating its source."
            )
        document = project / "studio" / "document.vsz"
        spec = project / "studio" / "spec.json"
        if not document.is_file() or not spec.is_file():
            raise ValueError(
                "Source updates require a managed document and its scientific specification."
            )
        return {"primary": (document, spec)}
    figures = {}
    for item in registry.get("figures", []):
        if item.get("status") != "ready":
            raise ValueError(
                "Resolve the incomplete figure set before updating its source."
            )
        identity = str(item["figure_id"])
        document, spec = Path(item["document"]), Path(item["spec"])
        if identity in figures or not all(
            path.is_file() and path.resolve().is_relative_to(project / "studio")
            for path in (document, spec)
        ):
            raise ValueError(
                "Source updates require unique, project-local figure documents."
            )
        figures[identity] = (document, spec)
    if not figures:
        raise ValueError("The managed project has no complete figures.")
    return figures


def _numbers(values: object) -> dict[str, Any]:
    sequence = values if isinstance(values, list) else []
    finite = [
        float(x) for x in sequence if isinstance(x, int | float) and math.isfinite(x)
    ]
    return {
        "count": len(sequence),
        "minimum": min(finite) if finite else None,
        "maximum": max(finite) if finite else None,
        "sha256": payload_hash(sequence),
    }


def scientific_summary(spec: dict[str, Any]) -> dict[str, Any]:
    series = []
    for item in spec.get("series", []):
        series.append(
            {
                "sample": str(item.get("label") or item.get("legend_key") or ""),
                "presentation": item.get("presentation_kind"),
                "x": _numbers(item.get("x_values")),
                "y": _numbers(item.get("y_values")),
                "error": _numbers(item.get("error_values")),
            }
        )
    axes = {
        name: {key: axis.get(key) for key in ("label", "scale", "reverse")}
        for name, axis in spec.get("axes", {}).items()
    }
    categorical = spec.get("categorical") or {}
    groups = [
        {
            "sample": group.get("label") or group.get("sample"),
            "statistics": group.get("descriptive_statistics"),
            "raw_values": _numbers(group.get("raw_values")),
            "replicate_count": group.get("replicate_count"),
            "condition": group.get("condition_label"),
        }
        for group in categorical.get("groups", [])
    ]
    scalar = spec.get("scalar_field") or {}
    task = (spec.get("source_request") or {}).get("resolved_figure_task") or {}
    return {
        "template": spec.get("template"),
        "axes": axes,
        "series": series,
        "groups": groups,
        "task": {
            k: task.get(k)
            for k in (
                "title",
                "conditions",
                "sample_order",
                "replicate_counts",
                "metric_binding",
                "x_metric",
                "y_metric",
            )
        },
        "scalar_sha256": payload_hash(
            {
                k: scalar.get(k)
                for k in (
                    "x_values",
                    "y_values",
                    "z_values",
                    "x_column",
                    "y_column",
                    "z_column",
                )
            }
        )
        if scalar
        else None,
    }


def _value_difference(old: list[Any], new: list[Any]) -> dict[str, Any]:
    changed = [
        i
        for i in range(max(len(old), len(new)))
        if i >= len(old) or i >= len(new) or old[i] != new[i]
    ]
    return {
        "changed_value_count": len(changed),
        "examples": [
            {
                "point_index": i + 1,
                "before": old[i] if i < len(old) else None,
                "after": new[i] if i < len(new) else None,
            }
            for i in changed[:8]
        ],
        "omitted_example_count": max(0, len(changed) - 8),
    }


def numerical_differences(
    old: dict[str, Any], new: dict[str, Any]
) -> list[dict[str, Any]]:
    """Expose actual changed values, retaining duplicate observations by index."""
    changes = []
    for category, fields in (
        ("series", ("x_values", "y_values", "error_values")),
        ("groups", ("raw_values",)),
    ):
        before = (
            old.get("series", [])
            if category == "series"
            else (old.get("categorical") or {}).get("groups", [])
        )
        after = (
            new.get("series", [])
            if category == "series"
            else (new.get("categorical") or {}).get("groups", [])
        )
        for item in after:
            label = item.get("label") or ""
            matches = [s for s in before if s.get("label") == label]
            if len(matches) != 1 or sum(s.get("label") == label for s in after) != 1:
                continue  # Added or ambiguous samples are disclosed by the full summaries.
            for field in fields:
                delta = _value_difference(
                    matches[0].get(field) or [], item.get(field) or []
                )
                if delta["changed_value_count"]:
                    changes.append(
                        {
                            "sample": label,
                            "category": category,
                            "values": field,
                            **delta,
                        }
                    )
    return changes


def compare_figures(previous: Path, candidate: Path) -> dict[str, Any]:
    before = project_figures(previous)
    after = project_figures(candidate)
    changes = []
    for identity in dict.fromkeys([*before, *after]):
        old_spec = (
            json.loads(before[identity][1].read_text()) if identity in before else None
        )
        new_spec = (
            json.loads(after[identity][1].read_text()) if identity in after else None
        )
        old = scientific_summary(old_spec) if old_spec is not None else None
        new = scientific_summary(new_spec) if new_spec is not None else None
        old_samples = [s["sample"] for s in old["series"]] if old else []
        new_samples = [s["sample"] for s in new["series"]] if new else []
        changes.append(
            {
                "figure_id": identity,
                "change": "added"
                if old is None
                else "removed"
                if new is None
                else "unchanged"
                if old == new
                else "updated",
                "samples_added": sorted(set(new_samples) - set(old_samples)),
                "samples_removed": sorted(set(old_samples) - set(new_samples)),
                "sample_order_changed": old_samples != new_samples,
                "axes_changed": old is not None
                and new is not None
                and old["axes"] != new["axes"],
                "before": old,
                "after": new,
                "numerical_differences": numerical_differences(
                    old_spec or {}, new_spec or {}
                ),
            }
        )
    return {
        "before_figure_count": len(before),
        "after_figure_count": len(after),
        "figures": changes,
    }


__all__ = ["compare_figures", "payload_hash", "project_figures", "scientific_summary"]
