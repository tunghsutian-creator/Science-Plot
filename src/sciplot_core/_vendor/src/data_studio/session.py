from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from src import plot_style
from src.data_studio.models import (
    DataStudioFigurePreference,
    DataStudioGroupState,
    DataStudioSessionPayload,
    DataStudioSpecimenState,
)
from src.plot_contract import template_names
from src.rendering.fit_analysis import normalize_fit_options_payload
from src.rendering.template_lifecycle import compatibility_template_ids, resolve_template_id

_RECIPE_TEMPLATE_IDS = tuple(
    sorted(
        {*(str(template_id) for template_id in template_names()), *compatibility_template_ids()},
        key=len,
        reverse=True,
    )
)


def _iter_objects(value: object) -> tuple[object, ...]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        return tuple(value)
    return ()


def _mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _int_value(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _normalize_template_id(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return resolve_template_id(cleaned)


def _normalize_style_value(value: object) -> str:
    normalized = plot_style.normalize_style_preset(str(value) if value is not None else None)
    return normalized if normalized in plot_style.list_style_presets() else plot_style.DEFAULT_STYLE_PRESET


def _normalize_render_options(value: object) -> dict[str, object]:
    option_map = _mapping(value) or {}
    normalized = dict(option_map)
    normalized["style_preset"] = _normalize_style_value(option_map.get("style_preset"))
    return normalized


def _normalize_comparison_recipe_id(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned == "representative_curve":
        return cleaned or None
    for template_id in _RECIPE_TEMPLATE_IDS:
        suffix = f"_{template_id}"
        if not cleaned.endswith(suffix):
            continue
        metric_prefix = cleaned[: -len(suffix)]
        if not metric_prefix:
            return cleaned
        normalized_template_id = _normalize_template_id(template_id)
        if normalized_template_id is None:
            return cleaned
        return f"{metric_prefix}_{normalized_template_id}"
    return cleaned


def normalize_session_payload(payload: dict[str, object]) -> DataStudioSessionPayload:
    workbook_paths = tuple(str(Path(str(path)).expanduser()) for path in _iter_objects(payload.get("workbook_paths")))
    imported_paths = tuple(str(Path(str(path)).expanduser()) for path in _iter_objects(payload.get("imported_paths")))
    comparison_recipe_ids = tuple(
        dict.fromkeys(
            recipe_id
            for item in _iter_objects(payload.get("comparison_recipe_ids"))
            if (recipe_id := _normalize_comparison_recipe_id(item))
        )
    )

    group_states_list: list[DataStudioGroupState] = []
    for item in _iter_objects(payload.get("group_states")):
        item_map = _mapping(item)
        if item_map is None or not item_map.get("workbook_path"):
            continue
        workbook_path = str(Path(str(item_map.get("workbook_path", ""))).expanduser())
        group_states_list.append(
            DataStudioGroupState(
                workbook_path=workbook_path,
                display_name=str(item_map.get("display_name", "")).strip() or Path(workbook_path).stem,
                include_in_compare=bool(item_map.get("include_in_compare", True)),
                sort_order=_int_value(item_map.get("sort_order", 0), 0),
            )
        )
    group_states = tuple(group_states_list)

    specimen_states_list: list[DataStudioSpecimenState] = []
    for item in _iter_objects(payload.get("specimen_states")):
        item_map = _mapping(item)
        if item_map is None or not item_map.get("workbook_path"):
            continue
        specimen_id = str(item_map.get("specimen_id", "")).strip()
        if not specimen_id:
            continue
        specimen_states_list.append(
            DataStudioSpecimenState(
                workbook_path=str(Path(str(item_map.get("workbook_path", ""))).expanduser()),
                specimen_id=specimen_id,
                included=bool(item_map.get("included", True)),
                selected_as_representative=bool(item_map.get("selected_as_representative", False)),
            )
        )
    specimen_states = tuple(specimen_states_list)

    figure_preferences_list: list[DataStudioFigurePreference] = []
    for item in _iter_objects(payload.get("figure_preferences")):
        item_map = _mapping(item)
        if item_map is None:
            continue
        family_id = str(item_map.get("family_id", "")).strip()
        if not family_id:
            continue
        raw_options = _mapping(item_map.get("options_by_template")) or {}
        options_by_template: dict[str, dict[str, object]] = {}
        for template_id, options in raw_options.items():
            normalized_template_id = _normalize_template_id(template_id)
            if normalized_template_id is None:
                continue
            options_by_template[normalized_template_id] = _normalize_render_options(options)
        raw_fit_options = _mapping(item_map.get("fit_options_by_template")) or {}
        fit_options_by_template: dict[str, dict[str, object]] = {}
        for template_id, fit_options in raw_fit_options.items():
            normalized_template_id = _normalize_template_id(template_id)
            if normalized_template_id is None:
                continue
            fit_options_by_template[normalized_template_id] = normalize_fit_options_payload(fit_options)
        figure_preferences_list.append(
            DataStudioFigurePreference(
                family_id=family_id,
                selected_template_id=_normalize_template_id(item_map.get("selected_template_id")),
                options_by_template=options_by_template,
                fit_options_by_template=fit_options_by_template,
            )
        )
    figure_preferences = tuple(figure_preferences_list)

    template_draft_path = payload.get("template_draft_path")
    return DataStudioSessionPayload(
        version=_int_value(payload.get("version", 1), 1),
        selected_template_id=(
            str(payload["selected_template_id"]) if payload.get("selected_template_id") is not None else None
        ),
        selected_workbook_id=(
            str(payload["selected_workbook_id"]) if payload.get("selected_workbook_id") is not None else None
        ),
        primary_workbook_id=(
            str(payload["primary_workbook_id"]) if payload.get("primary_workbook_id") is not None else None
        ),
        selected_recipe_id=_normalize_comparison_recipe_id(payload.get("selected_recipe_id")),
        workbook_paths=workbook_paths,
        comparison_recipe_ids=comparison_recipe_ids,
        selected_figure_family_id=(
            str(payload["selected_figure_family_id"])
            if payload.get("selected_figure_family_id") is not None
            else None
        ),
        selected_figure_template_id=(
            _normalize_template_id(payload.get("selected_figure_template_id"))
        ),
        group_states=group_states,
        specimen_states=specimen_states,
        figure_preferences=figure_preferences,
        imported_paths=imported_paths,
        template_draft_path=(
            str(Path(str(template_draft_path)).expanduser()) if template_draft_path is not None else None
        ),
    )


__all__ = ["normalize_session_payload"]
