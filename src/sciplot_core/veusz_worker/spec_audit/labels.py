"""Validate native legends and the ordered direct-label inventory."""

from __future__ import annotations

import re
from typing import Any

from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.visual_matchers import (
    _direct_label_record_matches_contract,
)
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings


def audit_legends_and_labels(
    inventory: SpecAuditInventory,
    spec: dict[str, Any],
    series: list[dict[str, Any]],
) -> None:
    from sciplot_core.performance_veusz import performance_label_contracts
    from sciplot_core.studio_core.legend_contracts import (
        categorical_component_legend_label_contracts,
        curve_factor_legend_label_contracts,
    )
    from sciplot_core.studio_core.series_request import veusz_literal_text

    loaded_document = inventory.loaded_document
    categorical = inventory.categorical
    legend = spec.get("legend")

    legend = legend if isinstance(legend, dict) else {}

    visible_keys = _visible_data_bindings(
        loaded_document, widget_type="key", setting_names=("title",)
    )

    expected_legend = legend.get("show") is True

    segmented_component_legend = (
        legend.get("presentation_kind") == "segmented_component"
    )

    factorized_curve_legend = legend.get("presentation_kind") == "factorized_curve"

    if expected_legend and (segmented_component_legend or factorized_curve_legend):
        if visible_keys:
            raise ValueError(
                "Exact-current custom factor/component legend must not use a single-colour native Veusz key."
            )
    elif expected_legend:
        if (
            len(visible_keys) != 1
            or visible_keys[0]["name"] != "key1"
            or str(visible_keys[0]["bindings"]["title"]) != ""
        ):
            raise ValueError(
                "Exact-current Veusz document does not contain its exact visible legend."
            )
    elif visible_keys:
        raise ValueError(
            "Exact-current Veusz document contains an unapproved visible legend."
        )

    direct_labels = spec.get("direct_labels")

    if not isinstance(direct_labels, list):
        raise ValueError("Veusz specification has no direct-label inventory.")

    expected_direct_labels: list[dict[str, Any]] = []

    seen_direct_label_names: set[str] = set()

    for raw_label in direct_labels:
        if not isinstance(raw_label, dict):
            raise ValueError("Veusz specification contains an invalid direct label.")
        label_name = str(raw_label.get("name") or "").strip()
        series_match = re.fullmatch("label_(\\d+)", label_name)
        category_match = re.fullmatch("category_label_(\\d+)", label_name)
        if series_match is not None:
            label_index = int(series_match.group(1)) - 1
            expected_label = (
                str(series[label_index].get("label") or "")
                if 0 <= label_index < len(series)
                else None
            )
        elif category_match is not None and isinstance(categorical, dict):
            label_index = int(category_match.group(1)) - 1
            x_axis = (
                spec.get("axes", {}).get("x")
                if isinstance(spec.get("axes"), dict)
                and isinstance(spec["axes"].get("x"), dict)
                else {}
            )
            category_labels = list(x_axis.get("category_labels") or [])
            expected_label = (
                str(category_labels[label_index])
                if 0 <= label_index < len(category_labels)
                else None
            )
        else:
            expected_label = None
        if (
            expected_label is None
            or str(raw_label.get("label") or "") != expected_label
            or label_name in seen_direct_label_names
        ):
            raise ValueError("Veusz direct label does not match its rendered series.")
        seen_direct_label_names.add(label_name)
        expected_direct_labels.append(
            {
                **raw_label,
                "path": f"/page1/graph1/{label_name}",
                "literal_label": veusz_literal_text(raw_label.get("label")),
            }
        )

    for raw_label in categorical_component_legend_label_contracts(spec):
        expected_direct_labels.append(
            {
                **raw_label,
                "path": f"/page1/graph1/{raw_label['name']}",
                "literal_label": veusz_literal_text(raw_label.get("label")),
            }
        )

    for raw_label in curve_factor_legend_label_contracts(spec):
        expected_direct_labels.append(
            {
                **raw_label,
                "path": f"/page1/graph1/{raw_label['name']}",
                "literal_label": veusz_literal_text(raw_label.get("label")),
            }
        )

    for raw_label in performance_label_contracts(spec):
        parent = str(raw_label.get("parent") or "graph")
        expected_direct_labels.append(
            {
                **raw_label,
                "path": f"/page1/{raw_label['name']}"
                if parent == "page"
                else f"/page1/graph1/{raw_label['name']}",
                "literal_label": veusz_literal_text(raw_label.get("label")),
            }
        )

    visible_direct_labels = _visible_data_bindings(
        loaded_document,
        widget_type="label",
        setting_names=(
            "label",
            "positioning",
            "xAxis",
            "yAxis",
            "xPos",
            "yPos",
            "alignHorz",
            "alignVert",
            "angle",
            "margin",
            "clip",
            "Text/size",
            "Text/color",
            "Text/hide",
            "Background/color",
            "Background/transparency",
            "Background/hide",
            "Border/color",
            "Border/width",
            "Border/style",
            "Border/transparency",
            "Border/hide",
        ),
    )

    if len(visible_direct_labels) != len(expected_direct_labels) or any(
        (
            not _direct_label_record_matches_contract(record, expected=expected)
            for record, expected in zip(
                visible_direct_labels, expected_direct_labels, strict=True
            )
        )
    ):
        raise ValueError(
            "Exact-current Veusz direct-label text, geometry, style, or ordered inventory differs from its series-bound contract."
        )
