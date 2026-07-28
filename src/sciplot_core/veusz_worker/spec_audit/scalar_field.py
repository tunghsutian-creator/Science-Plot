"""Validate scalar datasets, images, contours, colormaps, and colorbars."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.scalar_visual import scalar_visual_contract
from sciplot_core.veusz_worker.axis_matchers import _scalar_image_matches_contract
from sciplot_core.veusz_worker.contours import (
    _actual_contour_record,
    _expected_contour_records,
)
from sciplot_core.veusz_worker.numeric_evidence import (
    _dataset_evidence,
    _numeric_digest,
)
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory
from sciplot_core.veusz_worker.visual_matchers import (
    _colorbar_record_matches_contract,
)
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings


def audit_scalar_field(
    inventory: SpecAuditInventory,
    spec: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    from sciplot_core.scalar_visual import opaque_color_to_veusz_rgba

    loaded_document = inventory.loaded_document
    units = inventory.units
    seen_identities = inventory.seen_identities
    scalar = spec.get("scalar_field")

    allowed_scalar_dataset: str | None = None

    if isinstance(scalar, dict):
        visual = scalar_visual_contract(
            scalar, label="Veusz scalar-field specification"
        )
        data_name = str(scalar.get("data_name") or "").strip()
        allowed_scalar_dataset = data_name
        identity = "scalar_field"
        if not data_name or identity in seen_identities:
            raise ValueError(
                "Veusz scalar-field specification has no unique data identity."
            )
        dataset = _dataset_evidence(
            loaded_document,
            dataset_name=data_name,
            expected_values=scalar.get("z_values"),
            dimensions=2,
        )
        loaded_dataset = loaded_document.data[data_name]
        x_centres, y_centres = loaded_dataset.getPixelCentres()
        x_evidence = _numeric_digest(x_centres)
        y_evidence = _numeric_digest(y_centres)
        if x_evidence != _numeric_digest(
            scalar.get("x_values"), expected_persisted=True
        ) or y_evidence != _numeric_digest(
            scalar.get("y_values"), expected_persisted=True
        ):
            raise ValueError(
                "Exact-current Veusz scalar-field coordinates differ from the rendered specification."
            )
        dataset["x_value_sha256"] = x_evidence
        dataset["y_value_sha256"] = y_evidence
        image_records = _visible_data_bindings(
            loaded_document,
            widget_type="image",
            setting_names=(
                "data",
                "min",
                "max",
                "colorScaling",
                "colorMap",
                "colorInvert",
                "mapping",
                "drawMode",
                "transparency",
            ),
        )
        if len(image_records) != 1 or not _scalar_image_matches_contract(
            image_records[0], data_name=data_name, visual=visual
        ):
            raise ValueError(
                "Exact-current Veusz scalar image differs from its range, scaling, colormap, inversion, mapping, or draw contract."
            )
        expected_colormap = [
            list(opaque_color_to_veusz_rgba(value))
            for value in visual["colormap_colors"]
        ]
        matching_colormaps = [
            json_safe(value)
            for name, value in loaded_document.evaluate.def_colormaps
            if str(name) == str(visual["colormap_name"])
        ]
        if matching_colormaps != [expected_colormap]:
            raise ValueError(
                "Exact-current Veusz custom colormap differs from the rendered scalar-field contract."
            )
        contour_records = _visible_data_bindings(
            loaded_document,
            widget_type="contour",
            setting_names=(
                "data",
                "scaling",
                "manualLevels",
                "numLevels",
                "Lines/lines",
                "Lines/hide",
                "Fills/hide",
                "SubLines/hide",
                "ContourLabels/hide",
                "keyLevels",
            ),
        )
        if [
            _actual_contour_record(record) for record in contour_records
        ] != _expected_contour_records(data_name=data_name, visual=visual):
            raise ValueError(
                "Exact-current Veusz contour inventory differs from the rendered scalar-field contract."
            )
        units.append(
            {
                "identity": identity,
                "kind": "scalar_field",
                "datasets": [dataset],
                "consumer_paths": [
                    str(image_records[0]["path"]),
                    *[str(record["path"]) for record in contour_records],
                ],
                "scalar_visual": visual,
            }
        )

    colorbar_records = _visible_data_bindings(
        loaded_document,
        widget_type="colorbar",
        setting_names=(
            "label",
            "widgetName",
            "min",
            "max",
            "direction",
            "horzPosn",
            "vertPosn",
            "horzManual",
            "vertManual",
            "width",
            "height",
            "TickLabels/format",
            "MajorTicks/manualTicks",
            "Label/size",
            "TickLabels/size",
            "Line/width",
            "Border/width",
            "MajorTicks/width",
            "MajorTicks/length",
            "MinorTicks/width",
            "MinorTicks/length",
            "Label/hide",
            "TickLabels/hide",
            "MajorTicks/hide",
            "MinorTicks/hide",
            "Line/hide",
            "Border/hide",
            "Line/transparency",
            "Border/transparency",
            "MajorTicks/transparency",
            "MinorTicks/transparency",
            "Line/color",
            "Border/color",
            "Label/color",
            "TickLabels/color",
        ),
    )

    visual: dict[str, Any] | None = None

    if isinstance(scalar, dict) and scalar.get("show_colorbar") is True:
        visual = scalar_visual_contract(
            scalar, label="Veusz scalar-field specification"
        )

    expected_colorbar_count = 1 if visual is not None else 0

    if len(colorbar_records) != expected_colorbar_count or (
        visual is not None
        and (
            not _colorbar_record_matches_contract(
                colorbar_records[0], scalar=scalar, visual=visual
            )
        )
    ):
        raise ValueError(
            "Exact-current Veusz colorbar dimensions, text, ticks, colors, or placement differ from the rendered scalar-field contract."
        )
    return allowed_scalar_dataset, visual
