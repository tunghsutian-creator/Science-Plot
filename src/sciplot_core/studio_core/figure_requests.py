"""Build rheology and impact figure queues and per-figure render requests."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.materials_rules import (
    resolve_rule_template,
)
from sciplot_core.policy import (
    rheology_metric_axis_label,
)
from sciplot_core.study_model import (
    normalize_study_model,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)
from sciplot_core.studio_render.metric_columns import (
    _clean_metric_id,
)
from sciplot_core.studio_render.template_resolution import (
    _request_template,
)
from sciplot_core.studio_render.value_parsing import (
    _string_list,
)

from sciplot_core.studio_core.request_paths import (
    _resolve_request_input,
)

_RHEOLOGY_FREQUENCY_FIGURE_METRICS = {
    "storage_modulus",
    "loss_modulus",
    "loss_factor",
    "complex_viscosity",
}


def _rheology_frequency_figure_queue(
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the bounded, independent-document frequency-sweep queue."""

    if str(request.get("rule_id") or "").strip() != "rheology_frequency_sweep":
        return []
    study_model = normalize_study_model(
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {}
    )
    raw_queue = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    queue: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for value in raw_queue:
        if not isinstance(value, dict):
            continue
        figure_id = str(value.get("id") or "").strip()
        x_metric = _clean_metric_id(value.get("x_metric"))
        y_metric = _clean_metric_id(value.get("y_metric") or value.get("metric"))
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9_]*", figure_id)
            or figure_id in seen_ids
            or x_metric != "angular_frequency"
            or y_metric not in _RHEOLOGY_FREQUENCY_FIGURE_METRICS
        ):
            continue
        seen_ids.add(figure_id)
        queue.append(
            {
                **deepcopy(value),
                "id": figure_id,
                "x_metric": x_metric,
                "y_metric": y_metric,
                "metric": y_metric,
                "default_template": "point_line",
            }
        )
    if not any(item["y_metric"] == "storage_modulus" for item in queue):
        return []
    return queue


def _rheology_frequency_figure_request(
    request: dict[str, Any],
    figure: dict[str, Any],
) -> dict[str, Any]:
    figure_request = deepcopy(request)
    y_metric = str(figure["y_metric"])
    figure_request["x_metric"] = "angular_frequency"
    figure_request["y_metric"] = y_metric
    figure_request["template"] = "point_line"
    render_options = (
        dict(figure_request.get("render_options"))
        if isinstance(figure_request.get("render_options"), dict)
        else {}
    )
    render_options["size"] = "60x55"
    explicit_render_keys = {
        str(value)
        for value in (
            figure_request.get("explicit_render_option_keys")
            if isinstance(
                figure_request.get("explicit_render_option_keys"),
                list,
            )
            else []
        )
    }
    if y_metric == "loss_factor":
        if "yscale" not in explicit_render_keys:
            render_options["yscale"] = "linear"
        if (
            str(render_options.get("yscale") or "").casefold() != "log"
            and "y_tick_format" not in explicit_render_keys
        ):
            render_options.pop("y_tick_format", None)
    metric_label = rheology_metric_axis_label(y_metric)
    if y_metric == "complex_viscosity":
        metric_label = "|\\eta^{*}| (mPa·s)"
    if metric_label is not None:
        render_options["y_label_override"] = metric_label
    figure_request["render_options"] = render_options
    return figure_request


def _rheology_frequency_primary_request(
    request: dict[str, Any],
) -> dict[str, Any]:
    queue = _rheology_frequency_figure_queue(request)
    primary = next(
        (item for item in queue if item["y_metric"] == "storage_modulus"),
        None,
    )
    return (
        _rheology_frequency_figure_request(request, primary)
        if primary is not None
        else request
    )


def _impact_condition_figure_queue(
    request: dict[str, Any],
    *,
    base_dir: Path,
    project_dir: Path,
) -> list[dict[str, Any]]:
    """Materialize one canonical categorical source per workbook condition."""

    if str(request.get("rule_id") or "").strip() != "impact_metric":
        return []
    if _request_template(request) == "point_line":
        # The point-line alternative compares compatible workbook conditions
        # in one document instead of materializing one document per sheet.
        return []
    source = _resolve_request_input(request, base_dir=base_dir)
    if source is None:
        return []
    if source.is_dir():
        workbooks = sorted(
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
        )
        if len(workbooks) != 1:
            return []
        source = workbooks[0]
    if not source.is_file():
        return []
    from sciplot_core.semantic import read_impact_condition_payloads

    conditions = read_impact_condition_payloads(source)
    if len(conditions) <= 1:
        return []
    output_dir = project_dir / "studio" / "processed" / "impact_conditions"
    output_dir.mkdir(parents=True, exist_ok=True)
    queue: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for order, (condition, payload) in enumerate(conditions, start=1):
        token = (
            re.sub(
                r"[^a-z0-9]+",
                "_",
                str(condition).casefold(),
            ).strip("_")
            or f"condition_{order}"
        )
        figure_id = f"impact_{token}"
        suffix = 2
        while figure_id in used_ids:
            figure_id = f"impact_{token}_{suffix}"
            suffix += 1
        used_ids.add(figure_id)
        condition_source = output_dir / f"{figure_id}.csv"
        pd.DataFrame(payload.rows).to_csv(
            condition_source,
            header=False,
            index=False,
        )
        queue.append(
            {
                "id": figure_id,
                "title": f"Impact strength - {condition}",
                "condition": str(condition),
                "condition_source": str(condition_source),
                "sample_order": list(payload.samples),
                "replicate_counts": dict(
                    zip(payload.samples, payload.replicate_counts, strict=True)
                ),
                "x_metric": "sample",
                "y_metric": "impact_strength",
                "metric": "impact_strength",
                "default_template": "box_strip",
                "supported_templates": ["bar", "box", "box_strip", "point_line"],
                "presentation_data_shape": "categorical_replicates",
            }
        )
    return queue


def _impact_condition_figure_request(
    request: dict[str, Any],
    figure: dict[str, Any],
) -> dict[str, Any]:
    figure_request = deepcopy(request)
    figure_request["input"] = str(figure["condition_source"])
    figure_request["template"] = resolve_rule_template(
        "impact_metric",
        request.get("template")
        if isinstance(request.get("template"), str)
        else str(figure.get("default_template") or "box_strip"),
    )
    figure_request["x_metric"] = "sample"
    figure_request["y_metric"] = "impact_strength"
    figure_request["series_order"] = list(figure.get("sample_order") or [])
    return figure_request


def _impact_point_line_condition_order(
    request: dict[str, Any],
) -> list[str]:
    render_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    return _string_list(
        request.get("condition_order") or render_options.get("condition_order")
    )


def _impact_point_line_label_mapping(
    request: dict[str, Any],
) -> dict[str, str]:
    render_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    value = request.get("condition_label_mapping")
    if not isinstance(value, dict):
        value = render_options.get("condition_label_mapping")
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(label).strip()
        for key, label in value.items()
        if str(key).strip() and str(label).strip()
    }


def _impact_point_line_source(
    source: Path,
) -> Path:
    if source.is_file():
        return source
    workbooks = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
    )
    if len(workbooks) != 1:
        raise StudioPreparationBlocked(
            "impact_point_line_workbook_ambiguous",
            "Impact point-line comparison needs exactly one workbook source.",
        )
    return workbooks[0]
