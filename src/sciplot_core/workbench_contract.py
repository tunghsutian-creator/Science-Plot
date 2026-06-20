from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core.render import DEFAULT_EXPORT_FORMATS
from sciplot_core.study_model import sync_study_model_samples

ensure_legacy_core()

from src.plot_contract import load_plot_contract, template_contract  # noqa: E402
from src.rendering.options import validate_template_name  # noqa: E402
from src.rendering.render_service import build_rendered_plots  # noqa: E402

_RENDER_PARAMETER_NAMES = frozenset(
    name
    for name, parameter in inspect.signature(build_rendered_plots).parameters.items()
    if name not in {"template", "input_path", "sheet"} and parameter.kind is inspect.Parameter.KEYWORD_ONLY
)
_INTAKE_EXPORT_FORMATS = frozenset({"pdf", "svg", "png", "png_300", "png_600", "tiff", "tiff_300"})


def normalize_exports(exports: object) -> list[str]:
    if not isinstance(exports, list | tuple):
        return list(DEFAULT_EXPORT_FORMATS)
    selected = [str(item).strip().lower() for item in exports if str(item).strip()]
    if not selected:
        return list(DEFAULT_EXPORT_FORMATS)
    unknown = [item for item in selected if item not in _INTAKE_EXPORT_FORMATS]
    if unknown:
        known = ", ".join(sorted(_INTAKE_EXPORT_FORMATS))
        raise ValueError(f"Unsupported export format(s): {', '.join(unknown)}. Available exports: {known}.")
    return selected


def _selected_series_labels(*values: object) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list | tuple):
            continue
        for item in value:
            label = str(item).strip()
            if not label:
                continue
            key = label.casefold()
            if key in seen:
                continue
            labels.append(label)
            seen.add(key)
    return labels


def normalize_render_options(
    render_options: object,
    *,
    template: str | None = None,
) -> dict[str, Any]:
    if not isinstance(render_options, Mapping):
        return {}
    selected: dict[str, Any] = {
        str(key): value
        for key, value in render_options.items()
        if value not in (None, "")
    }

    unknown = sorted(key for key in selected if key not in _RENDER_PARAMETER_NAMES)
    if unknown:
        known = ", ".join(sorted(_RENDER_PARAMETER_NAMES))
        raise ValueError(f"Unsupported render option(s): {', '.join(unknown)}. Supported options: {known}.")

    size = selected.get("size")
    contract = load_plot_contract()
    size_names = tuple(contract.size_presets.keys())
    if size is not None and str(size) not in size_names:
        allowed = ", ".join(size_names)
        raise ValueError(f"Unsupported figure size `{size}`. Allowed sizes: {allowed}.")

    if template:
        resolved_template = validate_template_name(template)
        spec = (
            contract.templates[resolved_template]
            if resolved_template in contract.templates
            else template_contract(resolved_template)
        )
        unsupported = sorted(
            key
            for key in selected
            if key not in spec.editable_options
            and key not in {"fit_options", "custom_theme_id", "custom_theme_draft", "visual_theme_id"}
        )
        if unsupported:
            allowed = ", ".join(spec.editable_options)
            raise ValueError(
                f"Template `{resolved_template}` does not support option(s): {', '.join(unsupported)}. "
                f"Supported editable options: {allowed}."
            )
    return selected


def apply_request_patch(
    request: Mapping[str, Any],
    *,
    exports: object = None,
    render_options: object = None,
    series_order: object = None,
    template: str | None = None,
    review_note: str | None = None,
) -> dict[str, Any]:
    patched = dict(request)
    selected_exports = normalize_exports(exports if exports is not None else patched.get("exports"))
    current_render_options = patched.get("render_options") if isinstance(patched.get("render_options"), dict) else {}
    normalized_patch = normalize_render_options(render_options, template=template)
    selected_series = _selected_series_labels(series_order)
    explicit_order = _selected_series_labels(normalized_patch.get("series_order"))
    explicit_include = _selected_series_labels(normalized_patch.get("series_include"))
    if not selected_series:
        selected_series = explicit_order or explicit_include
    if selected_series:
        normalized_patch["series_order"] = selected_series
        if explicit_include:
            normalized_patch["series_include"] = explicit_include
        else:
            normalized_patch["series_include"] = selected_series

    merged_render_options = {**current_render_options, **normalized_patch}
    merged_render_options = normalize_render_options(
        merged_render_options,
        template=template,
    )

    patched["exports"] = selected_exports
    if selected_series:
        patched["series_order"] = selected_series
        synced_study_model = sync_study_model_samples(
            patched.get("study_model") if isinstance(patched.get("study_model"), dict) else None,
            sample_order=selected_series,
        )
        if isinstance(synced_study_model, dict):
            patched["study_model"] = synced_study_model
    if merged_render_options:
        patched["render_options"] = merged_render_options
    else:
        patched.pop("render_options", None)

    note = (review_note or "").strip()
    if note:
        notes = patched.get("review_notes") if isinstance(patched.get("review_notes"), list) else []
        patched["review_notes"] = [*notes, f"GUI refine: {note}"]
    return patched


__all__ = ["apply_request_patch", "normalize_exports", "normalize_render_options"]
