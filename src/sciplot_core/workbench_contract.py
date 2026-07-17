from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    RENDER_OPTION_KEYS,
    UNIFIED_HARD_OPTION_KEYS,
    normalize_categorical_summary,
    normalize_raw_point_jitter_fraction,
)
from sciplot_core.split import normalize_split_policy
from sciplot_core.study_model import sync_study_model_samples

ensure_legacy_core()

from src.plot_contract import load_plot_contract, template_contract  # noqa: E402

_RENDER_PARAMETER_NAMES = RENDER_OPTION_KEYS
_INTAKE_EXPORT_FORMATS = frozenset({"pdf", "svg", "png", "png_300", "png_600", "tiff", "tiff_300"})


def normalize_exports(exports: object) -> list[str]:
    if not isinstance(exports, list | tuple):
        return list(DEFAULT_EXPORT_FORMATS_POLICY)
    selected = [str(item).strip().lower() for item in exports if str(item).strip()]
    if not selected:
        return list(DEFAULT_EXPORT_FORMATS_POLICY)
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


def _validate_template_render_option_keys(keys: set[str], *, template: str | None) -> None:
    if not template:
        return
    contract = load_plot_contract()
    resolved_template = str(template).strip()
    if resolved_template not in contract.templates:
        known = ", ".join(sorted(contract.templates))
        raise ValueError(f"Unknown template: {resolved_template}. Supported templates: {known}")
    spec = (
        contract.templates[resolved_template]
        if resolved_template in contract.templates
        else template_contract(resolved_template)
    )
    unsupported = sorted(
        key
        for key in keys
        if key not in spec.editable_options
        and key not in UNIFIED_HARD_OPTION_KEYS
        and key not in {"fit_options", "custom_theme_id", "custom_theme_draft", "visual_theme_id"}
    )
    if unsupported:
        allowed = ", ".join(spec.editable_options)
        raise ValueError(
            f"Template `{resolved_template}` does not support option(s): {', '.join(unsupported)}. "
            f"Supported editable options: {allowed}."
        )


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

    # Keep old request files readable, but do not let legacy typography/stroke
    # options survive as effective settings.  The renderer owns one hard
    # project-wide style now.
    selected = {
        key: value for key, value in selected.items() if key not in UNIFIED_HARD_OPTION_KEYS
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

    if "summary_statistic" in selected:
        selected["summary_statistic"] = normalize_categorical_summary(selected["summary_statistic"])
    if "raw_point_jitter_fraction" in selected:
        selected["raw_point_jitter_fraction"] = normalize_raw_point_jitter_fraction(
            selected["raw_point_jitter_fraction"]
        )

    _validate_template_render_option_keys(set(selected), template=template)
    return selected


def normalize_clear_render_options(
    clear_render_options: object,
    *,
    template: str | None = None,
) -> list[str]:
    if not isinstance(clear_render_options, list | tuple | set):
        return []
    selected: list[str] = []
    seen: set[str] = set()
    for item in clear_render_options:
        key = str(item).strip()
        if not key or key in seen:
            continue
        selected.append(key)
        seen.add(key)

    unknown = sorted(key for key in selected if key not in _RENDER_PARAMETER_NAMES)
    if unknown:
        known = ", ".join(sorted(_RENDER_PARAMETER_NAMES))
        raise ValueError(
            f"Unsupported render option clear(s): {', '.join(unknown)}. Supported options: {known}."
        )
    _validate_template_render_option_keys(set(selected), template=template)
    return selected


def apply_request_patch(
    request: Mapping[str, Any],
    *,
    exports: object = None,
    render_options: object = None,
    clear_render_options: object = None,
    split_policy: object = None,
    series_order: object = None,
    template: str | None = None,
    review_note: str | None = None,
) -> dict[str, Any]:
    patched = dict(request)
    selected_exports = normalize_exports(exports if exports is not None else patched.get("exports"))
    current_render_options = patched.get("render_options") if isinstance(patched.get("render_options"), dict) else {}
    explicit_key_payload = patched.get("explicit_render_option_keys")
    explicit_keys = (
        {str(key) for key in explicit_key_payload if str(key) in current_render_options}
        if isinstance(explicit_key_payload, list | tuple | set)
        else set(current_render_options)
    )
    clear_keys = set(normalize_clear_render_options(clear_render_options, template=template))
    explicit_keys -= clear_keys
    current_render_options = {
        key: value for key, value in current_render_options.items() if key not in clear_keys
    }
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
    explicit_keys.update(normalized_patch)

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
        patched["explicit_render_option_keys"] = sorted(
            key for key in explicit_keys if key in merged_render_options
        )
    else:
        patched.pop("render_options", None)
        patched["explicit_render_option_keys"] = []
    if split_policy is not None:
        normalized_split_policy = normalize_split_policy(split_policy)
        if normalized_split_policy is not None:
            patched["split_policy"] = normalized_split_policy

    note = (review_note or "").strip()
    if note:
        notes = patched.get("review_notes") if isinstance(patched.get("review_notes"), list) else []
        patched["review_notes"] = [*notes, f"GUI refine: {note}"]
    return patched


__all__ = [
    "apply_request_patch",
    "normalize_clear_render_options",
    "normalize_exports",
    "normalize_render_options",
]
