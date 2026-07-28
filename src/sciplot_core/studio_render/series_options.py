"""Apply request render options, palette choices, and replicate styling to series."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from sciplot_core.policy import (
    DEFAULT_CURVE_LINE_STYLE_SEQUENCE,
    DEFAULT_PALETTE_PRESET,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    categorical_component_fill_color,
)

from sciplot_core.studio_render.models import (
    DEFAULT_PALETTE,
    IMPACT_POINT_LINE_KINDS,
    POINT_LINE_MARKERS,
    StudioPreparationBlocked,
    StudioSeries,
)

from sciplot_core.studio_render.categorical_groups import (
    _factor_pair_identity,
    _grouped_bar_identity,
    _factorized_curve_grid,
)

from sciplot_core.studio_render.template_resolution import (
    _request_template,
)

from sciplot_core.studio_render.value_parsing import (
    _string_list,
)


def _replicate_group_style_indexes(
    labels: list[str],
) -> dict[str, tuple[int, int]]:
    """Return stable condition and within-condition replicate indexes."""

    pattern = re.compile(
        r"^(?P<condition>.+?)\s+replicate\s+(?P<replicate>\S+)\s*$",
        flags=re.IGNORECASE,
    )
    conditions: list[str] = []
    replicates: dict[str, list[str]] = {}
    parsed: dict[str, tuple[str, str]] = {}
    for label in labels:
        match = pattern.fullmatch(label.strip())
        if match is None:
            continue
        condition = match.group("condition").strip()
        replicate = match.group("replicate").strip()
        if condition not in conditions:
            conditions.append(condition)
        if replicate not in replicates.setdefault(condition, []):
            replicates[condition].append(replicate)
        parsed[label] = (condition, replicate)
    return {
        label: (
            conditions.index(condition),
            replicates[condition].index(replicate),
        )
        for label, (condition, replicate) in parsed.items()
    }


def _apply_series_options(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    request: dict[str, Any],
) -> list[StudioSeries]:
    include = _string_list(render_options.get("series_include"))
    order = _string_list(render_options.get("series_order")) or _string_list(
        request.get("series_order")
    )
    styles = (
        render_options.get("series_styles")
        if isinstance(render_options.get("series_styles"), list)
        else []
    )
    palette = _palette_for_render_options(render_options)
    marker_sequence = _string_list(render_options.get("marker_sequence"))
    if not marker_sequence:
        marker_sequence = list(POINT_LINE_MARKERS)
    line_style_sequence = _string_list(render_options.get("line_style_sequence"))
    if not line_style_sequence:
        line_style_sequence = list(DEFAULT_CURVE_LINE_STYLE_SEQUENCE)
    duplicate_labels = sorted(
        label
        for label, count in Counter(item.label for item in series).items()
        if count > 1
    )
    if duplicate_labels:
        raise StudioPreparationBlocked(
            "duplicate_series_labels",
            "Series labels must be unique before label-based selection: "
            + ", ".join(duplicate_labels),
        )
    duplicate_order = sorted(
        label for label, count in Counter(order).items() if count > 1
    )
    if duplicate_order:
        raise StudioPreparationBlocked(
            "duplicate_series_order",
            "series_order contains duplicate labels: " + ", ".join(duplicate_order),
        )
    duplicate_include = sorted(
        label for label, count in Counter(include).items() if count > 1
    )
    if duplicate_include:
        raise StudioPreparationBlocked(
            "duplicate_series_include",
            "series_include contains duplicate labels: " + ", ".join(duplicate_include),
        )
    by_label = {item.label: item for item in series}
    unknown_order = [label for label in order if label not in by_label]
    if unknown_order:
        if _is_inferred_source_group_order(order, request=request):
            order = [label for label in order if label in by_label]
        else:
            raise StudioPreparationBlocked(
                "unknown_series_order",
                "series_order contains unknown series labels: "
                + ", ".join(unknown_order),
            )
    ordered = [by_label[label] for label in order if label in by_label]
    ordered.extend(
        item for item in series if item.label not in {entry.label for entry in ordered}
    )
    if include:
        unknown_include = [label for label in include if label not in by_label]
        if unknown_include:
            raise StudioPreparationBlocked(
                "unknown_series_include",
                "series_include contains unknown series labels: "
                + ", ".join(unknown_include),
            )
        include_set = set(include)
        ordered = [item for item in ordered if item.label in include_set]
    style_by_label: dict[str, dict[str, Any]] = {}
    for style in styles:
        if isinstance(style, dict):
            label = (
                style.get("label")
                or style.get("sample")
                or style.get("name")
                or style.get("series_id")
            )
            if isinstance(label, str):
                style_by_label[label] = style
    styled: list[StudioSeries] = []
    template_id = _request_template(request)
    factorized_curve = _factorized_curve_grid(
        ordered,
        template_id=template_id,
    )
    grouped_replicate_styles = (
        _replicate_group_style_indexes([item.label for item in ordered])
        if str(request.get("rule_id") or "").strip() == "swelling_curve"
        else {}
    )
    grouped_bar_samples: list[str] = []
    for item in ordered:
        if item.presentation_kind != "categorical_grouped_replicates":
            continue
        sample, _condition = _grouped_bar_identity(item.label)
        if sample not in grouped_bar_samples:
            grouped_bar_samples.append(sample)
    for index, item in enumerate(ordered):
        style = style_by_label.get(item.label, {})
        if style.get("visible") is False or style.get("enabled") is False:
            continue
        impact_point_line_item = item.presentation_kind in IMPACT_POINT_LINE_KINDS
        condition_index, replicate_index = grouped_replicate_styles.get(
            item.label,
            (index, index),
        )
        factor_color: str | None = None
        factor_line_style: str | None = None
        if factorized_curve is not None:
            formula, condition = _factor_pair_identity(item.label)
            formula_index = factorized_curve["formula_order"].index(formula)
            factor_condition_index = factorized_curve["condition_order"].index(
                condition
            )
            condition_index = formula_index
            replicate_index = formula_index
            root_color = palette[formula_index % len(palette)]
            factor_color = categorical_component_fill_color(
                root_color,
                component_index=(
                    len(factorized_curve["condition_order"])
                    - 1
                    - factor_condition_index
                ),
                component_count=len(factorized_curve["condition_order"]),
            )
            # Factorized curves are continuous line charts: formula owns the
            # categorical colour root, condition owns the opaque light/dark
            # tone, and every measured trace remains solid with no markers.
            factor_line_style = "solid"
        if item.presentation_kind == "categorical_grouped_replicates":
            sample, _condition = _grouped_bar_identity(item.label)
            condition_index = grouped_bar_samples.index(sample)
        default_marker = (
            marker_sequence[replicate_index % len(marker_sequence)]
            if (
                template_id == "point_line"
                or item.presentation_kind == "categorical_replicates"
            )
            else "none"
        )
        if factor_line_style is not None:
            default_line_style = factor_line_style
        elif item.label in grouped_replicate_styles:
            default_line_style = line_style_sequence[
                replicate_index % len(line_style_sequence)
            ]
        elif template_id == "point_line" and len(ordered) > len(marker_sequence):
            default_line_style = line_style_sequence[
                (index // len(marker_sequence)) % len(line_style_sequence)
            ]
        elif template_id != "point_line" and len(ordered) > 1:
            default_line_style = line_style_sequence[index % len(line_style_sequence)]
        else:
            default_line_style = "solid"
        styled.append(
            StudioSeries(
                label=item.label,
                x_name=item.x_name,
                y_name=item.y_name,
                x_values=item.x_values,
                y_values=item.y_values,
                error_values=item.error_values,
                color=str(
                    style.get("color")
                    or (
                        factor_color or item.color
                        if impact_point_line_item
                        else factor_color or palette[condition_index % len(palette)]
                    )
                ),
                line_width=UNIFIED_LINE_WIDTH_PT,
                marker=style.get("marker", item.marker or default_marker),
                marker_size=(
                    item.marker_size
                    if impact_point_line_item and item.marker_size is not None
                    else UNIFIED_MARKER_SIZE_PT
                ),
                marker_alpha=item.marker_alpha,
                marker_line_color=item.marker_line_color,
                marker_line_width=item.marker_line_width,
                line_style=str(
                    style.get("line_style")
                    or style.get("linestyle")
                    or (item.line_style if impact_point_line_item else None)
                    or default_line_style
                ),
                presentation_kind=item.presentation_kind,
                category_position=item.category_position,
                component_labels=item.component_labels,
                source_artifacts=item.source_artifacts,
            )
        )
    if not styled:
        raise StudioPreparationBlocked(
            "no_visible_series",
            "The confirmed series selection leaves no visible series.",
        )
    return styled


def _is_inferred_source_group_order(
    order: list[str],
    *,
    request: dict[str, Any],
) -> bool:
    """Recognize intake grouping labels that are not terminal curve labels."""

    if not order:
        return False
    study_model = (
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {}
    )
    sample_order = _string_list(study_model.get("sample_order"))
    if order != sample_order:
        return False
    figure_queue = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    confirmation_statuses = {
        str(evidence.get("confirmation_status") or "").strip().casefold()
        for figure in figure_queue
        if isinstance(figure, dict)
        for evidence in [figure.get("evidence_contract")]
        if isinstance(evidence, dict)
    }
    return not confirmation_statuses.intersection(
        {"confirmed", "approved", "user_confirmed"}
    )


def _effective_render_options(request: dict[str, Any]) -> dict[str, Any]:
    template_id = _request_template(request)
    merged: dict[str, Any] = {}
    try:
        from sciplot_core.contract import load_plot_contract

        contract = load_plot_contract()
        template = contract.templates.get(template_id)
        if template is not None:
            merged.update(template.default_options)
    except Exception:
        if template_id == "stacked_curve":
            merged.update(
                {"series_label_mode": "inline", "baseline": "none", "reverse_x": False}
            )

    if isinstance(request.get("render_options"), dict):
        merged.update(request["render_options"])
    return merged


def _palette_for_render_options(render_options: dict[str, Any]) -> tuple[str, ...]:
    explicit_palette = _string_list(render_options.get("palette_colors"))
    if explicit_palette:
        return tuple(explicit_palette)
    palette_id = str(render_options.get("palette_preset") or DEFAULT_PALETTE_PRESET)
    if palette_id == DEFAULT_PALETTE_PRESET:
        return DEFAULT_PALETTE
    try:
        from sciplot_core.contract import load_plot_contract

        contract = load_plot_contract()
        palette = contract.palettes.get(palette_id)
        if palette is not None and palette.categorical:
            return tuple(str(color) for color in palette.categorical)
    except Exception:
        return DEFAULT_PALETTE
    return DEFAULT_PALETTE
