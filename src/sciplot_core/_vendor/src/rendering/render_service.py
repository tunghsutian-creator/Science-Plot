from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt

from src import plot_style
from src.plot_style import save_pdf
from src.rendering.analytical_layers import apply_analytical_layers
from src.rendering.axis_breaks import apply_axis_breaks
from src.rendering.custom_theme_store import resolve_custom_theme
from src.rendering.extra_axes import apply_extra_axes
from src.rendering.fit_analysis import fit_options_from_payload
from src.rendering.models import RenderedPlot, RenderOptions, TemplateName
from src.rendering.options import resolve_render_options, validate_template_name
from src.rendering.reference_guides import apply_reference_guides
from src.rendering.render_registry import TEMPLATE_RENDERERS
from src.rendering.shape_annotations import apply_shape_annotations
from src.rendering.style_composer import DEFAULT_STYLE_COMPOSER
from src.rendering.template_lifecycle import resolve_template_id
from src.rendering.text_annotations import apply_text_annotations


def close_rendered_plots(rendered_plots: list[RenderedPlot]) -> None:
    for rendered in rendered_plots:
        plt.close(rendered.figure)


def export_rendered_plots(
    rendered_plots: list[RenderedPlot],
    output_dir: Path,
    *,
    close: bool = False,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [save_pdf(rendered.figure, output_dir / rendered.filename) for rendered in rendered_plots]
    if close:
        close_rendered_plots(rendered_plots)
    return outputs


def build_rendered_plots_from_options(
    template: TemplateName,
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
    *,
    resolved_template_id: str | None = None,
) -> list[RenderedPlot]:
    requested_template = validate_template_name(template)
    resolved_template = resolved_template_id or resolve_template_id(
        requested_template,
        input_path=input_path,
        sheet=sheet,
    )
    custom_theme = resolve_custom_theme(options.custom_theme_id, options.custom_theme_draft)
    style_bundle = DEFAULT_STYLE_COMPOSER.compose(
        options.style_preset,
        options.visual_theme_id,
        custom_theme=custom_theme,
    )
    resolved_palette_preset = (
        custom_theme.palette_preset
        if custom_theme is not None and custom_theme.palette_preset
        else options.palette_preset
    )
    try:
        plot_style.apply_style(
            style_bundle.publication_profile_id,
            resolved_palette_preset,
            hard_overrides=style_bundle.hard_overrides,
            palette_colors=style_bundle.palette_colors,
            soft_overrides=style_bundle.resolved_soft,
        )
        renderer = TEMPLATE_RENDERERS[resolved_template]
        rendered_plots = renderer.render(input_path, sheet, options)
        return [
            apply_text_annotations(
                apply_shape_annotations(
                    apply_reference_guides(
                        apply_analytical_layers(
                            apply_extra_axes(
                                apply_axis_breaks(rendered, options=options),
                                options=options,
                            ),
                            options=options,
                        ),
                        options=options,
                    ),
                    options=options,
                ),
                options=options,
            )
            for rendered in rendered_plots
        ]
    finally:
        plot_style.apply_style(style_bundle.publication_profile_id, resolved_palette_preset)


def build_rendered_plots(
    template: TemplateName,
    input_path: Path,
    sheet: str | int = 0,
    *,
    size: str | None = None,
    xscale: str | None = None,
    yscale: str | None = None,
    reverse_x: bool | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    x_padding_fraction: float | None = None,
    x_tick_density: str | None = None,
    y_tick_density: str | None = None,
    x_tick_edge_labels: str | None = None,
    y_tick_edge_labels: str | None = None,
    series_order: list[str] | tuple[str, ...] | None = None,
    series_styles: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    series_offsets: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    legend_position: str | None = None,
    series_label_mode: str | None = None,
    x_label_override: str | None = None,
    y_label_override: str | None = None,
    baseline: str | None = None,
    show_colorbar: bool | None = None,
    style_preset: str | None = None,
    palette_preset: str | None = None,
    use_sidecar: bool | None = None,
    visual_theme_id: str | None = None,
    fit_options: dict[str, object] | None = None,
    extra_x_axis: dict[str, object] | None = None,
    extra_y_axis: dict[str, object] | None = None,
    x_axis_breaks: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    y_axis_breaks: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    reference_guides: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    reference_line: dict[str, object] | None = None,
    reference_band: dict[str, object] | None = None,
    text_annotations: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    shape_annotations: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    analytical_layers: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    data_variables: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    data_transforms: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
) -> list[RenderedPlot]:
    requested_template = validate_template_name(template)
    resolved_template = resolve_template_id(requested_template, input_path=input_path, sheet=sheet)
    options = resolve_render_options(
        template=requested_template,
        size=size,
        xscale=xscale,
        yscale=yscale,
        reverse_x=reverse_x,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        x_padding_fraction=x_padding_fraction,
        x_tick_density=x_tick_density,
        y_tick_density=y_tick_density,
        x_tick_edge_labels=x_tick_edge_labels,
        y_tick_edge_labels=y_tick_edge_labels,
        series_order=series_order,
        series_styles=series_styles,
        series_offsets=series_offsets,
        legend_position=legend_position,
        series_label_mode=series_label_mode,
        x_label_override=x_label_override,
        y_label_override=y_label_override,
        baseline=baseline,
        show_colorbar=show_colorbar,
        style_preset=style_preset,
        palette_preset=palette_preset,
        use_sidecar=use_sidecar,
        visual_theme_id=visual_theme_id,
        extra_x_axis=extra_x_axis,
        extra_y_axis=extra_y_axis,
        x_axis_breaks=x_axis_breaks,
        y_axis_breaks=y_axis_breaks,
        reference_guides=reference_guides,
        reference_line=reference_line,
        reference_band=reference_band,
        text_annotations=text_annotations,
        shape_annotations=shape_annotations,
        analytical_layers=analytical_layers,
        data_variables=data_variables,
        data_transforms=data_transforms,
        resolved_template_id=resolved_template,
    )
    options = replace(
        options,
        fit_options=fit_options_from_payload(fit_options).__dict__,
    )
    return build_rendered_plots_from_options(
        requested_template,
        input_path,
        sheet,
        options,
        resolved_template_id=resolved_template,
    )


def render_template(
    template: TemplateName,
    input_path: Path,
    output_dir: Path,
    sheet: str | int = 0,
    *,
    size: str | None = None,
    xscale: str | None = None,
    yscale: str | None = None,
    reverse_x: bool | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    x_padding_fraction: float | None = None,
    x_tick_density: str | None = None,
    y_tick_density: str | None = None,
    x_tick_edge_labels: str | None = None,
    y_tick_edge_labels: str | None = None,
    series_order: list[str] | tuple[str, ...] | None = None,
    series_styles: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    series_offsets: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    legend_position: str | None = None,
    series_label_mode: str | None = None,
    x_label_override: str | None = None,
    y_label_override: str | None = None,
    baseline: str | None = None,
    show_colorbar: bool | None = None,
    style_preset: str | None = None,
    palette_preset: str | None = None,
    use_sidecar: bool | None = None,
    visual_theme_id: str | None = None,
    fit_options: dict[str, object] | None = None,
    extra_x_axis: dict[str, object] | None = None,
    extra_y_axis: dict[str, object] | None = None,
    x_axis_breaks: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    y_axis_breaks: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    reference_guides: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    reference_line: dict[str, object] | None = None,
    reference_band: dict[str, object] | None = None,
    text_annotations: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    shape_annotations: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    analytical_layers: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    data_variables: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    data_transforms: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
) -> list[Path]:
    rendered_plots = build_rendered_plots(
        template,
        input_path,
        sheet,
        size=size,
        xscale=xscale,
        yscale=yscale,
        reverse_x=reverse_x,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        x_padding_fraction=x_padding_fraction,
        x_tick_density=x_tick_density,
        y_tick_density=y_tick_density,
        x_tick_edge_labels=x_tick_edge_labels,
        y_tick_edge_labels=y_tick_edge_labels,
        series_order=series_order,
        series_styles=series_styles,
        series_offsets=series_offsets,
        legend_position=legend_position,
        series_label_mode=series_label_mode,
        x_label_override=x_label_override,
        y_label_override=y_label_override,
        baseline=baseline,
        show_colorbar=show_colorbar,
        style_preset=style_preset,
        palette_preset=palette_preset,
        use_sidecar=use_sidecar,
        visual_theme_id=visual_theme_id,
        fit_options=fit_options,
        extra_x_axis=extra_x_axis,
        extra_y_axis=extra_y_axis,
        x_axis_breaks=x_axis_breaks,
        y_axis_breaks=y_axis_breaks,
        reference_guides=reference_guides,
        reference_line=reference_line,
        reference_band=reference_band,
        text_annotations=text_annotations,
        shape_annotations=shape_annotations,
        analytical_layers=analytical_layers,
        data_variables=data_variables,
        data_transforms=data_transforms,
    )
    return export_rendered_plots(rendered_plots, output_dir, close=True)


__all__ = [
    "TEMPLATE_RENDERERS",
    "build_rendered_plots",
    "build_rendered_plots_from_options",
    "close_rendered_plots",
    "export_rendered_plots",
    "render_template",
]
