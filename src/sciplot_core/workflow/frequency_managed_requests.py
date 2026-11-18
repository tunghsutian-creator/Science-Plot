"""Prepare one exact ordered frequency FigurePlan as Managed create candidates."""
from copy import deepcopy
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_transforms import builtin_executor, execute_node
from sciplot_core.policy.frame_export import DEFAULT_LINE_STYLE_SEQUENCE
from sciplot_core.policy.template_defaults import POINT_LINE_RENDER_OPTIONS
from sciplot_core.policy.visual_identity import DEFAULT_PALETTE_COLORS
from sciplot_core.semantic_sources.rheology_sweep_domain import ResolvedRheologySweepDomain
from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables
from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_figure import _compose
from sciplot_core.task_semantic_frequency import frequency_coordinate

from .frequency_managed_grouping import resolve_mean_group_blocks
from .frequency_managed_metrics import prepare_frequency_metric_group


class PreparedFrequencyRequests(NamedTuple):
    requests: list[dict[str, Any]]
    terminal_pairs: list[tuple[str, list[float | None], list[float | None]]]


def prepare_frequency_requests(
    domain: ResolvedRheologySweepDomain, plan: ResolvedFigurePlan, *, task_root: Path,
) -> PreparedFrequencyRequests:
    """Reuse semantic composition over the common measured/derived replicate DAG."""
    rule = domain.rule_id
    if source_tree_sha256(domain.source) != domain.source_sha256:
        _invalid("The selected original source tree no longer matches its exact plan.")
    markers = POINT_LINE_RENDER_OPTIONS["marker_sequence"]
    if plan.primary_figure_id is None or len(domain.prepared_samples) > len(markers):
        _unsupported("This automatic suite requires a primary figure and one distinct marker per condition.")
    observed = [{"path": str(path), "source_id": f"source:{index}", **inspect_semantic_tables(path, rule_id=rule)}
                for index, path in enumerate(domain.selected_sources)]
    groups = resolve_mean_group_blocks(domain, plan, observed)
    raw_by_region = {(str(sample.source.resolve()), sample.original_group_region): sample
                     for sample in domain.raw_samples}
    by_path = {item["path"]: item for item in observed}
    units = {task.y_metric: {sample.metric_units.get(task.y_metric) for sample in domain.prepared_samples}
             for task in plan.tasks if task.y_metric is not None}
    if any(len(values) != 1 or None in values for values in units.values()):
        _unsupported("Every selected frequency metric requires compatible units throughout the complete group.")
    if not all(task.x_metric == "angular_frequency" and task.y_metric in units and task.template == "point_line"
               for task in plan.tasks):
        _unsupported("This FigurePlan contains a non-Cartesian or unsupported frequency task.")
    nodes: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    aggregate = {}
    for name, references in groups.items():
        replicates = []
        for item in references:
            selection = item["table_selection"]
            region = (selection["header_rows"][0], selection["data_start_row"], selection["data_end_row"])
            sample = raw_by_region[(item["path"], region)]
            original = by_path[item["path"]]
            candidate = next(value for value in original["candidates"] if value["candidate_id"] == item["table_id"])
            block = next(value for value in candidate["blocks"] if value["block_id"] == item["block_id"])
            replicates.append((sample, item, block["columns"]))
        primary = next(task for task in plan.tasks if task.figure_id == plan.primary_figure_id)
        bound, endpoint = prepare_frequency_metric_group(replicates, metric=str(primary.y_metric), transforms=nodes)
        sources.extend(bound)
        aggregate[name] = endpoint
    raw = {"scientific": {"data_sources": sources, "mappings": {}, "transforms": nodes}}
    datasets = load_sources(raw, rule)
    for node in nodes:
        datasets[node["output"]], _ = execute_node(node, datasets)
    requests = []
    terminal_pairs = []
    for task in plan.tasks:
        metric = str(task.y_metric)
        unit = str(next(iter(units[metric])))
        intent = {"rule_id": rule, "x": {"quantity": "angular_frequency", "unit": "rad/s"},
                  "y": {"quantity": metric, "unit": unit}}
        recipes, values, records = deepcopy(nodes), datasets.copy(), []
        for index, sample in enumerate(domain.prepared_samples):
            dataset_id = aggregate[sample.sample]
            columns = values[dataset_id]["columns"]
            if (columns["x"]["values"] != [row["x"] for row in sample.rows]
                    or metric not in columns
                    or columns[metric]["values"] != [row.get(metric) for row in sample.rows]):
                _invalid("The candidate does not replay the selected original frequency arrays exactly.")
            if task.figure_id == plan.primary_figure_id:
                if metric != "storage_modulus" or unit != "Pa":
                    _invalid("Frequency terminal analysis requires a canonical primary storage-modulus task in Pa.")
                terminal_pairs.append((sample.sample, columns["x"]["values"], columns[metric]["values"]))
            final = f"frequency-figure-series:{index}"
            node = {"id": f"frequency-figure-mapping:{index}", "kind": "rename", "inputs": [dataset_id],
                    "output": final, "parameters": {"columns": {metric: {"id": "y", "label": metric}}},
                    "executor": builtin_executor("rename"), "determinism": "deterministic"}
            recipes.append(node)
            values[final], _ = execute_node(node, values)
            records.append({"source_id": final, "dataset_id": final, "sample": sample.sample, "stages": [],
                            "units": {"x": "rad/s", "y": unit}})
        axes = {role: frequency_coordinate(role, value, value["unit"]) for role, value in (("x", intent["x"]), ("y", intent["y"]))}
        for coordinate in axes.values():
            if coordinate["scale"] == "log":
                coordinate["empty_log_ticks"] = "extend_to_anchors_v1"
        state = {"request": {"intent": intent}, "intent_revision": 1, "task_dir": str(task_root / task.figure_id),
                 "semantic_plan": {"resolved_rule_id": rule, "resolved_axes": axes, "resolved_bindings": []}}
        request = _compose(state, records, sources, recipes, values, "")
        layers = request["template_definition"]["figure_spec"]["views"][0]["layers"]
        for index, layer in enumerate(layers):
            line, point = layer["marks"]
            color = DEFAULT_PALETTE_COLORS[index]
            line["style"].update(line_style=DEFAULT_LINE_STYLE_SEQUENCE[index], line_color=color)
            point["style"].update(marker=markers[index], marker_color=color)
        provenance = request["data_binding"]["provenance"]
        provenance["figure_task"] = task.to_payload()
        provenance["frequency_mean_original_blocks"] = {name: list(items) for name, items in groups.items()}
        requests.append(request)
    if source_tree_sha256(domain.source) != domain.source_sha256:
        _invalid("The original source tree changed during Managed candidate preparation.")
    return PreparedFrequencyRequests(requests, terminal_pairs)


def _invalid(message: str) -> NoReturn:
    raise TaskControlError("frequency_managed_replay_mismatch", message)


def _unsupported(message: str) -> NoReturn:
    raise TaskControlError("frequency_managed_candidates_unavailable", message)
