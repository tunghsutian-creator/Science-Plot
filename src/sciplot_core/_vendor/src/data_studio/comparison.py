from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd

from src.data_loader import CurveSeries, ReplicateGroup, load_curve_table, load_replicate_table
from src.data_studio.builtin import tensile as tensile_builtin
from src.data_studio.io_utils import list_sheet_names
from src.data_studio.models import (
    ComparisonRecipe,
    ComparisonSet,
    DataStudioFigureOutput,
    DataStudioFilteredWorkbookOutput,
    DataStudioGroupState,
    DataStudioSpecimenState,
    WorkbookMetricSummary,
    serialize_model,
)
from src.data_studio.workbooks import (
    export_filtered_workbook_from_context,
    import_workbook,
    load_filtered_workbook_context,
    load_workbook_specimen_bundle,
)
from src.infrastructure.persistence.data_studio_comparison_contexts import (
    prepare_managed_data_studio_comparison_context_dir,
)
from src.infrastructure.runtime_cache import LRUCache
from src.plot_contract import template_contract
from src.plot_style import DEFAULT_PALETTE_PRESET, DEFAULT_STYLE_PRESET, normalize_style_preset
from src.rendering.render_service import build_rendered_plots, close_rendered_plots, export_rendered_plots
from src.rendering.template_lifecycle import resolve_template_id
from src.text_normalization import slugify_label

_COMPARISON_PREVIEW_PDF_CACHE = LRUCache[str, str](maxsize=64)
_METRIC_COMPARISON_TEMPLATE_IDS = ("bar", "box", "box_strip", "violin", "point_error")
_CURVE_COMPARISON_TEMPLATE_IDS = ("curve", "point_line", "scatter")


@dataclass(frozen=True)
class LoadedComparisonWorkbook:
    workbook_path: Path
    label: str
    sheet_names: tuple[str, ...]
    representative_curve: CurveSeries | None
    metric_summaries: tuple[WorkbookMetricSummary, ...]
    replicate_groups: dict[str, ReplicateGroup]


@dataclass(frozen=True)
class ResolvedComparisonGroup:
    workbook_path: Path
    display_name: str
    sort_order: int
    loaded: LoadedComparisonWorkbook


@dataclass(frozen=True)
class MaterializedComparisonContext:
    comparison_set: ComparisonSet
    cache_key: str
    materialized_at: str


def _comparison_preview_pdf_cache_key(
    *,
    context_cache_key: str,
    recipe: ComparisonRecipe,
) -> str:
    payload = json.dumps(
        {
            "context_cache_key": context_cache_key,
            "recipe_id": recipe.id,
            "template_id": recipe.template_id,
            "sheet_name": recipe.sheet_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_curve() -> CurveSeries:
    return CurveSeries(
        sample="",
        x_label="X",
        y_label="Y",
        x_unit="",
        y_unit="",
        data=pd.DataFrame({"x": [], "y": []}),
    )


def _context_manifest_path(context_root: Path) -> Path:
    return context_root / "context_manifest.json"


def _comparison_set_from_payload(payload: dict[str, object]) -> ComparisonSet:
    recipes_payload = payload.get("recipes", [])
    recipes = tuple(
        ComparisonRecipe(
            id=str(item.get("id", "")),
            label=str(item.get("label", "")),
            category=str(item.get("category", "")),
            template_id=str(item.get("template_id", "")),
            sheet_name=str(item.get("sheet_name", "")),
            metric_id=(str(item["metric_id"]) if item.get("metric_id") is not None else None),
            enabled_by_default=bool(item.get("enabled_by_default", True)),
            supported=bool(item.get("supported", True)),
            support_reason=str(item.get("support_reason", "")),
        )
        for item in recipes_payload
        if isinstance(item, dict)
    )
    workbook_paths = tuple(Path(str(item)).expanduser() for item in payload.get("workbook_paths", []))
    workbook_labels = tuple(str(item) for item in payload.get("workbook_labels", []))
    return ComparisonSet(
        id=str(payload.get("id", "")),
        label=str(payload.get("label", "")),
        workbook_paths=workbook_paths,
        workbook_labels=workbook_labels,
        comparison_workbook_path=Path(str(payload.get("comparison_workbook_path", ""))).expanduser(),
        recipes=recipes,
    )


def _load_materialized_context_from_manifest(
    context_root: Path,
    *,
    cache_key: str,
) -> MaterializedComparisonContext | None:
    manifest_path = _context_manifest_path(context_root)
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    manifest_cache_key = payload.get("cache_key")
    if isinstance(manifest_cache_key, str) and manifest_cache_key and manifest_cache_key != cache_key:
        return None
    try:
        comparison_set = _comparison_set_from_payload(dict(payload.get("comparison_set", {})))
        materialized_at = str(payload.get("materialized_at", ""))
    except Exception:
        return None
    if not comparison_set.comparison_workbook_path.exists():
        return None
    if not materialized_at:
        materialized_at = datetime.fromtimestamp(
            comparison_set.comparison_workbook_path.stat().st_mtime,
            tz=UTC,
        ).isoformat()
    return MaterializedComparisonContext(
        comparison_set=comparison_set,
        cache_key=cache_key,
        materialized_at=materialized_at,
    )


def _write_materialized_context_manifest(
    *,
    context_root: Path,
    context: MaterializedComparisonContext,
) -> None:
    manifest_path = _context_manifest_path(context_root)
    payload = {
        "cache_key": context.cache_key,
        "materialized_at": context.materialized_at,
        "comparison_set": serialize_model(context.comparison_set),
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_comparison_workbook(
    path: str | Path,
    *,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
) -> LoadedComparisonWorkbook:
    workbook = import_workbook(path)
    specimen_bundle = load_workbook_specimen_bundle(path, workbook=workbook)
    if specimen_bundle.supported:
        filtered = load_filtered_workbook_context(
            path,
            specimen_states=specimen_states,
            bundle=specimen_bundle,
        )
        if filtered.representative_curve is None:
            raise ValueError(
                f"{workbook.workbook_path.name} needs at least one included specimen with a representative curve."
            )
        return LoadedComparisonWorkbook(
            workbook_path=workbook.workbook_path,
            label=workbook.label,
            sheet_names=workbook.sheet_names,
            representative_curve=filtered.representative_curve,
            metric_summaries=filtered.metric_summaries,
            replicate_groups=filtered.replicate_groups,
        )

    workbook_sheet_names = tuple(list_sheet_names(workbook.workbook_path))
    representative_curve: CurveSeries | None = None
    if tensile_builtin.REPRESENTATIVE_CURVE_SHEET in workbook_sheet_names:
        representative_curves = load_curve_table(
            workbook.workbook_path,
            sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
        )
        if len(representative_curves) != 1:
            raise ValueError(
                f"{workbook.workbook_path.name} must contain exactly one representative curve in "
                f"{tensile_builtin.REPRESENTATIVE_CURVE_SHEET}."
            )
        representative_curve = representative_curves[0]
    replicate_groups: dict[str, ReplicateGroup] = {}
    for sheet_name in workbook_sheet_names:
        if not sheet_name.endswith("_Replicates"):
            continue
        groups = load_replicate_table(workbook.workbook_path, sheet_name=sheet_name)
        if len(groups) != 1:
            raise ValueError(f"{workbook.workbook_path.name} must contain exactly one replicate group in {sheet_name}.")
        group = groups[0]
        replicate_groups[group.value_label] = group
    return LoadedComparisonWorkbook(
        workbook_path=workbook.workbook_path,
        label=workbook.label,
        sheet_names=workbook_sheet_names,
        representative_curve=representative_curve,
        metric_summaries=workbook.metrics,
        replicate_groups=replicate_groups,
    )


def comparison_recipes_for_workbooks(
    workbook_paths: list[str | Path],
    *,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None = None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
) -> tuple[ComparisonRecipe, ...]:
    resolved_groups = _resolve_comparison_groups(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    return _comparison_recipes_for_loaded_workbooks([group.loaded for group in resolved_groups])


def _comparison_recipes_for_loaded_workbooks(
    loaded: list[LoadedComparisonWorkbook],
) -> tuple[ComparisonRecipe, ...]:
    if not loaded:
        raise ValueError("Data Studio needs at least one included workbook group.")
    metric_ids = [metric.label for metric in loaded[0].metric_summaries]
    recipes: list[ComparisonRecipe] = []
    if all(workbook.representative_curve is not None for workbook in loaded):
        recipes.append(
            ComparisonRecipe(
                id="representative_curve",
                label="Representative Curve Compare",
                category="curve",
                template_id="curve",
                sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
            )
        )
        for template_id in _CURVE_COMPARISON_TEMPLATE_IDS[1:]:
            recipes.append(
                ComparisonRecipe(
                    id=f"representative_{template_id}",
                    label=f"Representative {template_contract(template_id).label} Compare",
                    category="curve",
                    template_id=template_id,
                    sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
                )
            )
    else:
        recipes.append(
            ComparisonRecipe(
                id="representative_curve",
                label="Representative Curve Compare",
                category="curve",
                template_id="curve",
                sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
                enabled_by_default=False,
                supported=False,
                support_reason="The selected workbook shape does not include representative curves.",
            )
        )
    for metric_id in metric_ids:
        for template_id in _METRIC_COMPARISON_TEMPLATE_IDS:
            recipes.append(
                ComparisonRecipe(
                    id=f"{metric_id.lower()}_{template_id}",
                    label=f"{metric_id} {template_contract(template_id).label} Compare",
                    category="metric",
                    template_id=template_id,
                    sheet_name=f"{metric_id}_Replicates",
                    metric_id=metric_id,
                )
            )
    if not metric_ids:
        recipes.append(
            ComparisonRecipe(
                id="metric_bar",
                label="Metric Compare",
                category="metric",
                template_id="bar",
                sheet_name="Metric_Replicates",
                enabled_by_default=False,
                supported=False,
                support_reason="The selected workbook shape does not include comparable metric replicate tables.",
            )
        )
    return tuple(recipes)


def build_comparison_set(
    workbook_paths: list[str | Path],
    output_dir: str | Path,
    *,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None = None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
) -> ComparisonSet:
    resolved_groups = _resolve_comparison_groups(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    loaded = [group.loaded for group in resolved_groups]
    if len(loaded) < 1:
        raise ValueError("Data Studio comparison requires at least one included workbook group.")
    _validate_loaded_workbooks(loaded)
    labels = tensile_builtin.dedupe_labels(group.display_name for group in resolved_groups)
    bundle_dir = Path(output_dir).expanduser() / tensile_builtin.bundle_dir_name(labels)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    comparison_workbook_path = bundle_dir / f"{bundle_dir.name}.xlsx"
    with pd.ExcelWriter(comparison_workbook_path) as writer:
        curve_loaded = [workbook for workbook in loaded if workbook.representative_curve is not None]
        if len(curve_loaded) == len(loaded):
            tensile_builtin.representative_curve_dataframe(
                [
                    tensile_builtin.LoadedTensileWorkbookData(
                        workbook_path=workbook.workbook_path,
                        base_label=workbook.label,
                        sheet_names=workbook.sheet_names,
                        sample_count=0,
                        representative_filename=workbook.representative_curve.sample,
                        representative_curve=workbook.representative_curve,
                        metrics=tuple(
                            tensile_builtin.TensileMetricSummary(
                                label=metric.label,
                                unit=metric.unit,
                                mean=metric.mean,
                                std=metric.std,
                            )
                            for metric in workbook.metric_summaries
                        ),
                        replicate_groups=workbook.replicate_groups,
                        warnings=(),
                        source_files=(),
                    )
                    for workbook in curve_loaded
                    if workbook.representative_curve is not None
                ],
                labels,
            ).to_excel(writer, sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET, header=False, index=False)
        for metric_id in [metric.label for metric in loaded[0].metric_summaries]:
            unit = _metric_unit(loaded, metric_id)
            tensile_builtin.comparison_replicate_dataframe(
                metric_id,
                unit,
                [
                    tensile_builtin.LoadedTensileWorkbookData(
                        workbook_path=workbook.workbook_path,
                        base_label=workbook.label,
                        sheet_names=workbook.sheet_names,
                        sample_count=0,
                        representative_filename=(
                            workbook.representative_curve.sample if workbook.representative_curve is not None else ""
                        ),
                        representative_curve=workbook.representative_curve or _empty_curve(),
                        metrics=tuple(
                            tensile_builtin.TensileMetricSummary(
                                label=metric.label,
                                unit=metric.unit,
                                mean=metric.mean,
                                std=metric.std,
                            )
                            for metric in workbook.metric_summaries
                        ),
                        replicate_groups=workbook.replicate_groups,
                        warnings=(),
                        source_files=(),
                    )
                    for workbook in loaded
                ],
                labels,
            ).to_excel(writer, sheet_name=f"{metric_id}_Replicates", header=False, index=False)
        _comparison_summary_dataframe(loaded, labels).to_excel(
            writer,
            sheet_name=tensile_builtin.SUMMARY_SHEET,
            header=False,
            index=False,
        )
        pd.DataFrame(
            [
                ["label", " vs ".join(labels)],
                ["template_id", "data_studio/comparison"],
                ["source_files", " | ".join(str(group.workbook_path) for group in resolved_groups)],
            ]
        ).to_excel(writer, sheet_name=tensile_builtin.METADATA_SHEET, header=False, index=False)
    recipes = _comparison_recipes_for_loaded_workbooks(loaded)
    return ComparisonSet(
        id=bundle_dir.name,
        label=" vs ".join(labels),
        workbook_paths=tuple(group.workbook_path for group in resolved_groups),
        workbook_labels=tuple(labels),
        comparison_workbook_path=comparison_workbook_path,
        recipes=recipes,
    )


def preview_comparison_recipe(
    workbook_paths: list[str | Path],
    recipe_id: str,
    *,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None = None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
) -> tuple[ComparisonSet, ComparisonRecipe, str]:
    materialized = materialize_comparison_context(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    comparison_set = materialized.comparison_set
    recipe = _find_recipe(comparison_set.recipes, recipe_id)
    preview_cache_key = _comparison_preview_pdf_cache_key(
        context_cache_key=materialized.cache_key,
        recipe=recipe,
    )
    cached_pdf_base64 = _COMPARISON_PREVIEW_PDF_CACHE.get(preview_cache_key)
    if cached_pdf_base64 is not None:
        return comparison_set, recipe, cached_pdf_base64
    rendered = build_rendered_plots(
        recipe.template_id,
        comparison_set.comparison_workbook_path,
        recipe.sheet_name,
        style_preset=DEFAULT_STYLE_PRESET,
        palette_preset=DEFAULT_PALETTE_PRESET,
    )
    try:
        if not rendered:
            raise ValueError("The selected comparison recipe did not render any previews.")
        buffer = BytesIO()
        rendered[0].figure.savefig(buffer, format="pdf", facecolor="white", bbox_inches=None)
        pdf_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        _COMPARISON_PREVIEW_PDF_CACHE.set(preview_cache_key, pdf_base64)
    finally:
        close_rendered_plots(rendered)
    return comparison_set, recipe, pdf_base64


def materialize_comparison_context(
    workbook_paths: list[str | Path],
    *,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None = None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
) -> MaterializedComparisonContext:
    cache_key, context_root = prepare_managed_data_studio_comparison_context_dir(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    cached = _load_materialized_context_from_manifest(context_root, cache_key=cache_key)
    if cached is not None:
        return cached

    comparison_set = build_comparison_set(
        workbook_paths,
        context_root,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    materialized_at = datetime.fromtimestamp(
        comparison_set.comparison_workbook_path.stat().st_mtime,
        tz=UTC,
    ).isoformat()
    materialized = MaterializedComparisonContext(
        comparison_set=comparison_set,
        cache_key=cache_key,
        materialized_at=materialized_at,
    )
    _write_materialized_context_manifest(context_root=context_root, context=materialized)
    return materialized


def export_comparison_bundle(
    workbook_paths: list[str | Path],
    output_dir: str | Path,
    *,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None = None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
    selected_recipe_ids: list[str] | None = None,
    figure_options_by_recipe_id: dict[str, dict[str, object]] | None = None,
    figure_fit_options_by_recipe_id: dict[str, dict[str, object]] | None = None,
) -> tuple[ComparisonSet, tuple[DataStudioFigureOutput, ...], tuple[DataStudioFilteredWorkbookOutput, ...]]:
    comparison_set = build_comparison_set(
        workbook_paths,
        output_dir,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    selected_ids = set(
        selected_recipe_ids or [recipe.id for recipe in comparison_set.recipes if recipe.enabled_by_default]
    )
    figure_options_by_recipe_id = figure_options_by_recipe_id or {}
    figure_fit_options_by_recipe_id = figure_fit_options_by_recipe_id or {}
    figure_outputs: list[DataStudioFigureOutput] = []
    bundle_dir = comparison_set.comparison_workbook_path.parent
    for recipe in comparison_set.recipes:
        if recipe.id not in selected_ids or not recipe.supported:
            continue
        render_kwargs = _render_kwargs_from_payload(
            figure_options_by_recipe_id.get(recipe.id),
            template_id=recipe.template_id,
        )
        rendered = build_rendered_plots(
            recipe.template_id,
            comparison_set.comparison_workbook_path,
            recipe.sheet_name,
            fit_options=figure_fit_options_by_recipe_id.get(recipe.id),
            **render_kwargs,
        )
        try:
            output_paths = export_rendered_plots(rendered, bundle_dir, close=False)
            for output_path, _rendered_plot in zip(output_paths, rendered, strict=True):
                figure_outputs.append(
                    DataStudioFigureOutput(
                        path=output_path,
                        label=recipe.label,
                        category=recipe.category,
                        template_id=recipe.template_id,
                        sheet_name=recipe.sheet_name,
                        metric_id=recipe.metric_id,
                        recipe_id=recipe.id,
                    )
                )
        finally:
            close_rendered_plots(rendered)
    filtered_workbooks = _export_filtered_workbooks(
        comparison_set=comparison_set,
        workbook_paths=workbook_paths,
        bundle_dir=bundle_dir,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    return comparison_set, tuple(figure_outputs), filtered_workbooks


def _find_recipe(recipes: tuple[ComparisonRecipe, ...], recipe_id: str) -> ComparisonRecipe:
    for recipe in recipes:
        if recipe.id == recipe_id:
            if not recipe.supported:
                raise ValueError(recipe.support_reason or f"The recipe {recipe.label!r} is not available.")
            return recipe
    raise ValueError(f"Unknown comparison recipe: {recipe_id}")


def _export_filtered_workbooks(
    *,
    comparison_set: ComparisonSet,
    workbook_paths: list[str | Path],
    bundle_dir: Path,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None,
) -> tuple[DataStudioFilteredWorkbookOutput, ...]:
    filtered_dir = bundle_dir / "filtered_workbooks"
    filtered_dir.mkdir(parents=True, exist_ok=True)
    resolved_groups = _resolve_comparison_groups(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    labels = list(comparison_set.workbook_labels)
    if len(labels) != len(resolved_groups):
        labels = tensile_builtin.dedupe_labels(group.display_name for group in resolved_groups)
    file_stems = _dedupe_export_file_stems(labels)
    exported: list[DataStudioFilteredWorkbookOutput] = []
    for group, label, file_stem in zip(resolved_groups, labels, file_stems, strict=True):
        try:
            filtered = load_filtered_workbook_context(
                group.workbook_path,
                specimen_states=specimen_states,
            )
        except ValueError:
            continue
        workbook = export_filtered_workbook_from_context(
            filtered,
            filtered_dir / f"{file_stem}.xlsx",
            label=label,
            source_workbook_path=group.workbook_path,
        )
        exported.append(
            DataStudioFilteredWorkbookOutput(
                path=workbook.workbook_path,
                label=workbook.label,
                source_workbook_path=group.workbook_path,
                representative_filename=workbook.representative_filename,
            )
        )
    return tuple(exported)


def _dedupe_export_file_stems(labels: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    stems: list[str] = []
    for label in labels:
        base = slugify_label(label).strip("_") or "filtered_workbook"
        counts[base] = counts.get(base, 0) + 1
        suffix = counts[base]
        stems.append(f"{base}_{suffix}" if suffix > 1 else base)
    return stems


def _resolve_comparison_groups(
    workbook_paths: list[str | Path],
    *,
    group_states: list[DataStudioGroupState] | tuple[DataStudioGroupState, ...] | None = None,
    specimen_states: list[DataStudioSpecimenState] | tuple[DataStudioSpecimenState, ...] | None = None,
) -> list[ResolvedComparisonGroup]:
    expanded_paths = [Path(path).expanduser() for path in workbook_paths]
    if not expanded_paths:
        return []

    state_by_path = {
        str(Path(state.workbook_path).expanduser()): state
        for state in (group_states or ())
    }
    ordered_candidates: list[tuple[int, int, Path]] = []
    for index, path in enumerate(expanded_paths):
        state = state_by_path.get(str(path))
        sort_order = state.sort_order if state is not None else index
        ordered_candidates.append((sort_order, index, path))
    ordered_candidates.sort(key=lambda item: (item[0], item[1], str(item[2])))

    resolved: list[ResolvedComparisonGroup] = []
    for fallback_index, (_, _, path) in enumerate(ordered_candidates):
        state = state_by_path.get(str(path))
        if state is not None and not state.include_in_compare:
            continue
        loaded = load_comparison_workbook(path, specimen_states=specimen_states)
        display_name = (
            state.display_name.strip()
            if state is not None and state.display_name.strip()
            else loaded.label
        )
        resolved.append(
            ResolvedComparisonGroup(
                workbook_path=path,
                display_name=display_name,
                sort_order=state.sort_order if state is not None else fallback_index,
                loaded=loaded,
            )
        )
    return resolved


def _metric_unit(loaded: list[LoadedComparisonWorkbook], metric_id: str) -> str:
    units = {metric.unit for workbook in loaded for metric in workbook.metric_summaries if metric.label == metric_id}
    if len(units) != 1:
        raise ValueError(f"{metric_id} does not share a single comparable unit.")
    return units.pop()


def _validate_loaded_workbooks(loaded: list[LoadedComparisonWorkbook]) -> None:
    first_curve = loaded[0].representative_curve
    first_metric_ids = {metric.label: metric.unit for metric in loaded[0].metric_summaries}
    for workbook in loaded[1:]:
        curve = workbook.representative_curve
        if first_curve is not None or curve is not None:
            if first_curve is None or curve is None:
                raise ValueError("All compared workbooks must either provide representative curves or omit them.")
            if (
                curve.x_label != first_curve.x_label
                or curve.y_label != first_curve.y_label
                or curve.x_unit != first_curve.x_unit
                or curve.y_unit != first_curve.y_unit
            ):
                raise ValueError("Representative curve axes do not match across the selected workbooks.")
        metric_map = {metric.label: metric.unit for metric in workbook.metric_summaries}
        if metric_map != first_metric_ids:
            raise ValueError("Workbook metric labels or units do not match across the comparison set.")


def _comparison_summary_dataframe(
    loaded: list[LoadedComparisonWorkbook],
    labels: list[str],
) -> pd.DataFrame:
    rows: list[list[object]] = [["Label", "Workbook Path", "Representative File"]]
    metric_ids = [metric.label for metric in loaded[0].metric_summaries]
    header_row = rows[0]
    for metric_id in metric_ids:
        unit = _metric_unit(loaded, metric_id)
        header_row.extend([f"{metric_id} Mean ({unit})", f"{metric_id} Std ({unit})"])
    for label, workbook in zip(labels, loaded, strict=True):
        representative = workbook.representative_curve.sample if workbook.representative_curve is not None else ""
        row: list[object] = [label, str(workbook.workbook_path), representative]
        metric_map = {metric.label: metric for metric in workbook.metric_summaries}
        for metric_id in metric_ids:
            metric = metric_map[metric_id]
            row.extend([metric.mean, metric.std])
        rows.append(row)
    return pd.DataFrame(rows)


def _render_kwargs_from_payload(
    payload: dict[str, object] | None,
    *,
    template_id: str,
) -> dict[str, object]:
    resolved_template_id = resolve_template_id(template_id)
    template_spec = template_contract(resolved_template_id)
    size = payload.get("size") if payload else None
    if not isinstance(size, str) or size not in template_spec.allowed_sizes:
        size = template_spec.default_size

    style_preset = normalize_style_preset((payload or {}).get("style_preset")) if payload else DEFAULT_STYLE_PRESET
    if style_preset not in template_spec.available_styles:
        style_preset = template_spec.available_styles[0] if template_spec.available_styles else DEFAULT_STYLE_PRESET

    palette_preset = (payload or {}).get("palette_preset") if payload else DEFAULT_PALETTE_PRESET
    if not isinstance(palette_preset, str) or palette_preset not in template_spec.available_palettes:
        palette_preset = (
            template_spec.available_palettes[0] if template_spec.available_palettes else DEFAULT_PALETTE_PRESET
        )

    if not payload:
        return {
            "size": size,
            "style_preset": style_preset,
            "palette_preset": palette_preset,
        }
    resolved = {
        "size": size,
        "xscale": payload.get("xscale"),
        "yscale": payload.get("yscale"),
        "reverse_x": payload.get("reverse_x", False),
        "x_min": payload.get("x_min"),
        "x_max": payload.get("x_max"),
        "y_min": payload.get("y_min"),
        "y_max": payload.get("y_max"),
        "x_tick_density": payload.get("x_tick_density"),
        "y_tick_density": payload.get("y_tick_density"),
        "x_tick_edge_labels": payload.get("x_tick_edge_labels"),
        "y_tick_edge_labels": payload.get("y_tick_edge_labels"),
        "series_order": payload.get("series_order"),
        "series_label_mode": payload.get("series_label_mode"),
        "x_label_override": payload.get("x_label_override"),
        "y_label_override": payload.get("y_label_override"),
        "baseline": payload.get("baseline"),
        "show_colorbar": payload.get("show_colorbar"),
        "style_preset": style_preset,
        "palette_preset": palette_preset,
        "use_sidecar": payload.get("use_sidecar"),
        "visual_theme_id": payload.get("visual_theme_id"),
        "reference_guides": payload.get("reference_guides"),
        "text_annotations": payload.get("text_annotations"),
    }
    return {key: value for key, value in resolved.items() if value is not None or key == "reverse_x"}


__all__ = [
    "build_comparison_set",
    "comparison_recipes_for_workbooks",
    "export_comparison_bundle",
    "load_comparison_workbook",
    "preview_comparison_recipe",
]
