from __future__ import annotations

from pathlib import Path

from src.plot_contract import validation_rule
from src.rendering.cache import (
    load_curve_table_for_options,
    load_heatmap_table_for_options,
    load_replicate_table_for_options,
    read_raw_table_for_options,
)
from src.rendering.common import (
    aligned_replicate_band,
    append_multi_output_warning,
    humanize_preflight_exception,
    load_segmented_config,
    looks_like_tensile_curve,
    preview_output_filenames,
    style_preflight_warnings,
    summarize_replicate_distribution,
    validate_manual_axis_overrides,
    validate_rheology_bundle_scales,
    validate_series_scales,
)
from src.rendering.datagraph_inputs import series_looks_polar, table_figure_size_error
from src.rendering.dataset_models import build_normalized_dataset
from src.rendering.models import PreflightResult, RenderOptions, TemplateName
from src.rendering.series_order import unknown_series_order_labels
from src.rendering.template_lifecycle import resolve_template_id, template_family_ids, template_identity
from src.submission import build_render_submission_report

_FIT_SCATTER_TEMPLATES = set(template_family_ids("scatter_fit"))
_BUBBLE_SCATTER_TEMPLATES = set(template_family_ids("bubble_scatter"))
_MEAN_BAND_TEMPLATES = set(template_family_ids("mean_band"))
_STANDARD_CURVE_TEMPLATES = {"point_line", "curve", "area_curve", "step_line", "function_curve"}


def preflight_render_request(
    template: TemplateName,
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
) -> PreflightResult:
    resolved_template = resolve_template_id(template, input_path=input_path, sheet=sheet)
    identity = template_identity(template, resolved_template_id=resolved_template)
    warnings: list[str] = list(style_preflight_warnings(options))
    errors: list[str] = []
    normalized_dataset = (
        build_normalized_dataset(input_path, sheet, options=options)
        if resolved_template
        in _STANDARD_CURVE_TEMPLATES
        | _FIT_SCATTER_TEMPLATES
        | _BUBBLE_SCATTER_TEMPLATES
        | _MEAN_BAND_TEMPLATES
        else None
    )

    try:
        if resolved_template in _STANDARD_CURVE_TEMPLATES | _MEAN_BAND_TEMPLATES:
            if normalized_dataset and normalized_dataset.model in {
                "frequency_sweep",
                "temperature_sweep",
                "stress_relaxation",
            }:
                if resolved_template in _MEAN_BAND_TEMPLATES:
                    raise ValueError(f"{resolved_template} is not supported for rheology export bundles.")
                validate_manual_axis_overrides(options, template=resolved_template)
                metric_series = validate_rheology_bundle_scales(
                    normalized_dataset.model,
                    input_path,
                    sheet,
                    xscale=options.xscale,
                    yscale=options.yscale,
                )
                unknown_series = unknown_series_order_labels(
                    [series.sample for series_list in metric_series.values() for series in series_list],
                    options.series_order,
                )
                if unknown_series:
                    raise ValueError(
                        "series_order contains unknown series labels: " + ", ".join(unknown_series)
                    )
            else:
                curve_series = load_curve_table_for_options(input_path, sheet, options)
                validate_series_scales(curve_series, xscale=options.xscale, yscale=options.yscale)
                validate_manual_axis_overrides(
                    options,
                    template=resolved_template,
                    is_tensile_curve=looks_like_tensile_curve(curve_series),
                )
                unknown_series = unknown_series_order_labels(
                    [series.sample for series in curve_series],
                    options.series_order,
                )
                if unknown_series:
                    raise ValueError(
                        "series_order contains unknown series labels: " + ", ".join(unknown_series)
                    )
                if resolved_template in _MEAN_BAND_TEMPLATES:
                    aligned_replicate_band(curve_series)
        elif resolved_template in {"stacked_curve", "stacked_area"}:
            curve_series = load_curve_table_for_options(input_path, sheet, options)
            validate_manual_axis_overrides(options, template=resolved_template)
            unknown_series = unknown_series_order_labels(
                [series.sample for series in curve_series],
                options.series_order,
            )
            if unknown_series:
                raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown_series))
        elif resolved_template == "segmented_stacked_curve":
            curve_series = load_curve_table_for_options(input_path, sheet, options)
            validate_manual_axis_overrides(options, template=resolved_template)
            unknown_series = unknown_series_order_labels(
                [series.sample for series in curve_series],
                options.series_order,
            )
            if unknown_series:
                raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown_series))
            load_segmented_config(
                input_path,
                curve_series,
                use_sidecar=True if options.use_sidecar is None else options.use_sidecar,
            )
        elif resolved_template in {"scatter"} | _BUBBLE_SCATTER_TEMPLATES:
            curve_series = load_curve_table_for_options(input_path, sheet, options)
            validate_series_scales(curve_series, xscale=options.xscale, yscale=options.yscale)
            validate_manual_axis_overrides(
                options,
                template=resolved_template,
                is_tensile_curve=looks_like_tensile_curve(curve_series),
            )
            unknown_series = unknown_series_order_labels(
                [series.sample for series in curve_series],
                options.series_order,
            )
            if unknown_series:
                raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown_series))
        elif resolved_template in _FIT_SCATTER_TEMPLATES:
            curve_series = load_curve_table_for_options(input_path, sheet, options)
            validate_series_scales(curve_series, xscale=options.xscale, yscale=options.yscale)
            validate_manual_axis_overrides(
                options,
                template=resolved_template,
                is_tensile_curve=looks_like_tensile_curve(curve_series),
            )
            unknown_series = unknown_series_order_labels(
                [series.sample for series in curve_series],
                options.series_order,
            )
            if unknown_series:
                raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown_series))
            if not curve_series:
                raise ValueError("No valid X/Y series found.")
            for series in curve_series:
                data = series.data.dropna(subset=["x", "y"])
                if data.shape[0] < 2:
                    raise ValueError(
                        f"Series {series.sample!r} does not contain enough points for a deterministic linear fit."
                    )
                if data["x"].nunique() < 2:
                    raise ValueError(
                        f"Series {series.sample!r} has constant x values, so a linear fit cannot be computed."
                    )
        elif resolved_template in {
            "bar",
            "box",
            "box_strip",
            "violin",
            "violin_box",
            "point_error",
            "lollipop_error",
            "histogram_density",
            "density_area",
        }:
            groups = load_replicate_table_for_options(input_path, sheet, options)
            if not groups:
                raise ValueError("No valid groups were found in the replicate table.")
            validate_manual_axis_overrides(options, template=resolved_template)
            unknown_groups = unknown_series_order_labels(
                [group.group for group in groups],
                options.series_order,
            )
            if unknown_groups:
                raise ValueError("series_order contains unknown group labels: " + ", ".join(unknown_groups))
            summary = summarize_replicate_distribution(groups)
            if resolved_template in {"histogram_density", "density_area"}:
                if summary.total_points < 12 or summary.min_group_points < 4:
                    warnings.append(
                        "Density overlays are less stable with sparse replicates; "
                        "box/distribution views may read better."
                    )
                if summary.total_points >= 8 and summary.pooled_unique_ratio <= 0.35:
                    warnings.append(
                        "Values are highly discrete, so density overlays may look blocky."
                    )
            if len(groups) >= 6:
                warnings.append(validation_rule("dense_group_label_warning").description)
        elif resolved_template in {"heatmap", "annotated_heatmap"}:
            table = load_heatmap_table_for_options(input_path, sheet, options)
            if resolved_template == "annotated_heatmap":
                x_count = int(table.data["x"].nunique(dropna=True))
                y_count = int(table.data["y"].nunique(dropna=True))
                matrix_cells = x_count * y_count
                if x_count < 2 or y_count < 2:
                    warnings.append(
                        "Annotated heatmap adds limited value for single-row/column matrices; "
                        "plain heatmap may be clearer."
                    )
                if matrix_cells > 225:
                    warnings.append(
                        "Annotated heatmap may become dense at this matrix size; "
                        "consider plain heatmap for readability."
                    )
        elif resolved_template == "contour_field":
            table = load_heatmap_table_for_options(input_path, sheet, options)
            finite_count = int(table.data.dropna(subset=["x", "y", "z"]).shape[0])
            if finite_count < 3:
                raise ValueError("Contour field requires at least three finite X/Y/Z points.")
            if int(table.data["x"].nunique(dropna=True)) < 2 or int(table.data["y"].nunique(dropna=True)) < 2:
                raise ValueError("Contour field requires at least two distinct X and Y coordinates.")
            validate_manual_axis_overrides(options, template=resolved_template)
        elif resolved_template == "polar_curve":
            curve_series = load_curve_table_for_options(input_path, sheet, options)
            if not curve_series:
                raise ValueError("No valid theta/r series found.")
            if not series_looks_polar(curve_series):
                raise ValueError("Polar curve requires theta/radius columns with radian or degree theta units.")
            validate_manual_axis_overrides(options, template=resolved_template)
        elif resolved_template == "table_figure":
            raw = read_raw_table_for_options(input_path, sheet, options).dropna(how="all").dropna(axis=1, how="all")
            if raw.empty:
                raise ValueError("Table figure requires at least one visible row and column.")
            if size_error := table_figure_size_error(raw):
                raise ValueError(size_error)
        else:
            raise ValueError(f"Unsupported template in preflight: {resolved_template}")
    except Exception as exc:
        errors.append(humanize_preflight_exception(exc))

    if not errors:
        preview_names = preview_output_filenames(
            resolved_template,
            input_path,
            sheet,
            normalized_dataset.model if normalized_dataset else None,
        )
        append_multi_output_warning(warnings, preview_names)
    else:
        preview_names = ()

    return PreflightResult(
        template=resolved_template,
        requested_template_id=identity.requested_template_id,
        canonical_id=identity.canonical_id,
        role=identity.role,
        lifecycle_policy=identity.lifecycle_policy,
        implementation_id=identity.implementation_id,
        warnings=tuple(warnings),
        errors=tuple(errors),
        output_filenames=preview_names,
        submission_report=build_render_submission_report(
            context="preflight",
            template=resolved_template,
            options=options,
            output_filenames=preview_names,
            blockers=errors,
            warnings=warnings,
        ),
    )


__all__ = ["preflight_render_request"]
