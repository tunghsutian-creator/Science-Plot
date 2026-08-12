"""Revise source-authorized series inside one live Veusz document."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
from sciplot_core.studio_core.series_presentation import selected_series_order
from sciplot_core.studio_core.veusz_series_revision_operations import (
    build_native_series_revision_operation,
    first_setting_number,
    series_widget_suffix,
    unique_widgets_by_name,
)


SUPPORTED_SERIES_REVISION_TEMPLATES = frozenset({"curve", "box_strip"})


class VeuszSeriesRevisionError(ValueError):
    """A live document does not satisfy the narrow revision contract."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def inspect_veusz_series_revision(
    document: Any,
    document_path: Path,
) -> dict[str, Any]:
    """Return the current live selection over the exact-current source set."""

    contract = _revision_contract(document, document_path)
    current_order = _current_order(contract)
    return {
        "kind": "sciplot_veusz_series_revision_state",
        "version": 1,
        "status": "ready",
        "template": contract["template"],
        "document": str(document_path.expanduser().resolve()),
        "source_order": list(contract["source_order"]),
        "current_order": current_order,
        "exact_current_order": list(contract["exact_current_order"]),
        "pending_commit": current_order != contract["exact_current_order"],
        "excluded": [
            label for label in contract["source_order"] if label not in current_order
        ],
        "size_mm": list(contract["size_mm"]),
        "native_undo_available": can_revert_veusz_series_revision(document),
    }


def preview_veusz_series_revision(
    document: Any,
    document_path: Path,
    target_order: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Describe one membership/order change without mutating the document."""

    contract = _revision_contract(document, document_path)
    target = _validated_target(target_order, source_order=contract["source_order"])
    current = _current_order(contract)
    current_set = set(current)
    target_set = set(target)
    common_before = [label for label in current if label in target_set]
    common_after = [label for label in target if label in current_set]
    moved = [
        label
        for label in common_after
        if common_before.index(label) != common_after.index(label)
    ]
    return {
        "kind": "sciplot_veusz_series_revision_preview",
        "version": 1,
        "status": "ready",
        "template": contract["template"],
        "document": str(document_path.expanduser().resolve()),
        "source_order": list(contract["source_order"]),
        "current_order": current,
        "target_order": target,
        "added": [label for label in target if label not in current_set],
        "removed": [label for label in current if label not in target_set],
        "moved": moved,
        "changed": current != target,
        "preserved": {
            "page_size_mm": list(contract["size_mm"]),
            "page_and_graph": True,
            "physical_margins": True,
            "y_axis": True,
            "series_style": True,
            "source_values": True,
        },
        "apply_scope": "one_live_veusz_document_one_native_undo_step",
    }


def apply_veusz_series_revision(
    document: Any,
    document_path: Path,
    target_order: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Apply a previewable revision as one native Veusz undo operation."""

    preview = preview_veusz_series_revision(document, document_path, target_order)
    if preview["changed"] is not True:
        return {**preview, "status": "no_change", "applied": False}

    contract = _revision_contract(document, document_path)
    _ensure_veusz_on_path()
    operation = build_native_series_revision_operation(
        document,
        contract=contract,
        target_order=list(preview["target_order"]),
        error_factory=VeuszSeriesRevisionError,
    )
    operation.sciplot_series_revision = {
        "document": str(document_path.expanduser().resolve()),
        "before": list(preview["current_order"]),
        "after": list(preview["target_order"]),
    }
    document.applyOperation(operation)
    return {
        **preview,
        "status": "applied",
        "applied": True,
        "native_undo_available": True,
    }


def can_revert_veusz_series_revision(document: Any) -> bool:
    """Return whether the next native Undo is a SciPlot series revision."""

    history = getattr(document, "historyundo", None)
    return bool(
        isinstance(history, list)
        and history
        and isinstance(
            getattr(history[-1], "sciplot_series_revision", None),
            dict,
        )
    )


def has_pending_veusz_series_revision(
    document: Any,
    document_path: Path | None = None,
) -> bool:
    """Return whether live membership/order differs from the persisted spec."""

    if document_path is not None:
        state = inspect_veusz_series_revision(document, document_path)
        return bool(state["pending_commit"])

    history = getattr(document, "historyundo", None)
    return bool(
        isinstance(history, list)
        and any(
            isinstance(getattr(operation, "sciplot_series_revision", None), dict)
            for operation in history
        )
    )


def revert_veusz_series_revision(
    document: Any,
    document_path: Path,
) -> dict[str, Any]:
    """Revert only when the next native Veusz Undo is this revision."""

    if not can_revert_veusz_series_revision(document):
        raise VeuszSeriesRevisionError(
            "series_revision_not_next_undo",
            "The next Veusz Undo is not a SciPlot series revision.",
        )
    operation = document.historyundo[-1]
    revision = dict(operation.sciplot_series_revision)
    document.undoOperation()
    state = inspect_veusz_series_revision(document, document_path)
    return {
        **state,
        "status": "reverted",
        "reverted": True,
        "reverted_order": revision.get("after"),
        "restored_order": revision.get("before"),
    }


def _revision_contract(document: Any, document_path: Path) -> dict[str, Any]:
    path = document_path.expanduser().resolve()
    spec_path = _veusz_spec_path(path)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VeuszSeriesRevisionError(
            "series_revision_spec_unavailable",
            f"The exact-current Veusz spec is unavailable: {spec_path}",
        ) from exc
    template = str(spec.get("template") or "").strip()
    if template not in SUPPORTED_SERIES_REVISION_TEMPLATES:
        raise VeuszSeriesRevisionError(
            "series_revision_template_unsupported",
            "Series revision currently supports source-bound curve and box_strip documents.",
        )
    direct_labels = spec.get("direct_labels")
    legend = spec.get("legend")
    if template == "curve" and (
        (isinstance(direct_labels, list) and bool(direct_labels))
        or (
            isinstance(legend, dict)
            and legend.get("presentation_kind") == "factorized_curve"
        )
    ):
        raise VeuszSeriesRevisionError(
            "series_revision_annotation_unsupported",
            "Series revision does not yet support direct-label or factorized-legend curves.",
        )
    raw_series = spec.get("series")
    if not isinstance(raw_series, list) or not raw_series:
        raise VeuszSeriesRevisionError(
            "series_revision_series_missing",
            "The exact-current spec has no ordered source series.",
        )
    series = [dict(item) for item in raw_series if isinstance(item, dict)]
    labels = [str(item.get("label") or "").strip() for item in series]
    names = [str(item.get("name") or "").strip() for item in series]
    if (
        len(series) != len(raw_series)
        or not all(labels)
        or len(labels) != len(set(labels))
        or not all(names)
        or len(names) != len(set(names))
    ):
        raise VeuszSeriesRevisionError(
            "series_revision_identity_invalid",
            "The exact-current spec does not have unique series labels and widgets.",
        )
    widgets = unique_widgets_by_name(
        document,
        names,
        error_factory=VeuszSeriesRevisionError,
    )
    parents = {id(widget.parent): widget.parent for widget in widgets.values()}
    if len(parents) != 1:
        raise VeuszSeriesRevisionError(
            "series_revision_graph_unsupported",
            "All revisable series must belong to one live Veusz graph.",
        )
    categorical_groups: dict[str, dict[str, Any]] = {}
    if template == "box_strip":
        categorical = spec.get("categorical")
        groups = categorical.get("groups") if isinstance(categorical, dict) else None
        if not isinstance(groups, list):
            raise VeuszSeriesRevisionError(
                "series_revision_categorical_contract_missing",
                "The box_strip spec has no source-bound categorical groups.",
            )
        categorical_groups = {
            str(group.get("label") or "").strip(): dict(group)
            for group in groups
            if isinstance(group, dict) and str(group.get("label") or "").strip()
        }
        if set(categorical_groups) != set(labels):
            raise VeuszSeriesRevisionError(
                "series_revision_categorical_contract_mismatch",
                "Categorical group identities do not match the source series.",
            )
        if any(
            group.get("boxplot_eligible") is not True
            for group in categorical_groups.values()
        ):
            raise VeuszSeriesRevisionError(
                "series_revision_categorical_group_unsupported",
                "Series revision currently requires a native boxplot for every sample.",
            )
    size = spec.get("size_mm")
    size_mm = (
        [float(size[0]), float(size[1])]
        if isinstance(size, list | tuple) and len(size) == 2
        else []
    )
    return {
        "spec": spec,
        "template": template,
        "series": series,
        "source_order": labels,
        "exact_current_order": selected_series_order(spec),
        "widgets": widgets,
        "graph": next(iter(parents.values())),
        "categorical_groups": categorical_groups,
        "size_mm": size_mm,
    }


def _validated_target(
    values: list[str] | tuple[str, ...],
    *,
    source_order: list[str],
) -> list[str]:
    target = [str(value).strip() for value in values if str(value).strip()]
    if not target:
        raise VeuszSeriesRevisionError(
            "series_revision_empty_selection",
            "At least one source-authorized series must remain visible.",
        )
    if len(target) != len(set(target)) or any(
        label not in source_order for label in target
    ):
        raise VeuszSeriesRevisionError(
            "series_revision_target_invalid",
            "Target order must contain unique labels from the exact-current source set.",
        )
    return target


def _current_order(contract: dict[str, Any]) -> list[str]:
    visible = {
        label
        for label, item in zip(
            contract["source_order"], contract["series"], strict=True
        )
        if not bool(contract["widgets"][item["name"]].settings.get("hide").get())
    }
    if contract["template"] == "curve":
        label_by_name = {
            item["name"]: label
            for label, item in zip(
                contract["source_order"], contract["series"], strict=True
            )
        }
        return [
            label_by_name[child.name]
            for child in contract["graph"].children
            if child.name in label_by_name and label_by_name[child.name] in visible
        ]
    positions: list[tuple[float, str]] = []
    for label, item in zip(contract["source_order"], contract["series"], strict=True):
        if label not in visible:
            continue
        box = unique_widgets_by_name(
            contract["widgets"][item["name"]].document,
            [
                "categorical_boxplot_"
                + series_widget_suffix(
                    item["name"],
                    error_factory=VeuszSeriesRevisionError,
                )
            ],
            error_factory=VeuszSeriesRevisionError,
        )
        widget = next(iter(box.values()))
        positions.append(
            (first_setting_number(widget.settings.get("posn").get()), label)
        )
    return [label for _position, label in sorted(positions)]


__all__ = [
    "SUPPORTED_SERIES_REVISION_TEMPLATES",
    "VeuszSeriesRevisionError",
    "apply_veusz_series_revision",
    "can_revert_veusz_series_revision",
    "has_pending_veusz_series_revision",
    "inspect_veusz_series_revision",
    "preview_veusz_series_revision",
    "revert_veusz_series_revision",
]
