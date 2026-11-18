"""Exact raw instrument region bindings for a resolved mean FigurePlan."""
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation
from sciplot_core.foundation.text_values import clean_text
from sciplot_core.semantic_sources.rheology_sweep_domain import FREQUENCY_RULE_ID, ResolvedRheologySweepDomain
from sciplot_core.task_errors import TaskControlError


def resolve_mean_group_blocks(
    domain: ResolvedRheologySweepDomain,
    plan: ResolvedFigurePlan,
    sources: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Bind the legacy grouping authority by original file, header and row window."""
    if (domain.replicate_mode != "mean" or domain.rule_id != FREQUENCY_RULE_ID or plan.rule_id != FREQUENCY_RULE_ID
            or plan.source_sha256 != domain.source_sha256
            or any(task.replicate_counts != domain.facts.replicate_counts for task in plan.tasks)):
        _unbound("The selected FigurePlan must belong to the exact prepared frequency domain.")
    available: dict[tuple[Path, int, int, int], list[dict[str, Any]]] = {}
    for source in sources:
        path = Path(source["path"]).resolve()
        for candidate in source["candidates"]:
            for block in candidate["blocks"]:
                selection = block["table_selection"]
                headers = selection["header_rows"]
                if len(headers) != 1:
                    continue
                region = (path, headers[0], selection["data_start_row"], selection["data_end_row"])
                available.setdefault(region, []).append({"source_id": source["source_id"],
                    "table_id": candidate["candidate_id"], "block_id": block["block_id"], "path": str(path),
                    "sha256": source["sha256"], "table_selection": deepcopy(selection),
                    "result": block.get("result"), "result_row": block.get("result_row")})
    observed: dict[str, list[dict[str, Any]]] = {}
    used: set[tuple[Path, int, int, int]] = set()
    for sample in domain.raw_samples:
        if sample.original_group_region is None:
            _unbound("Each prepared replicate must bind one physical original instrument interval.")
        region = (sample.source.resolve(), *sample.original_group_region)
        candidates = available.get(region, [])
        if len(candidates) != 1 or region in used:
            _unbound("A selected frequency replicate did not match one distinct original block.")
        group = clean_text(sample.sample) or sample.source.stem
        prepared = next(item for item in domain.prepared_samples if item.sample == group)
        observed.setdefault(group, []).append({**candidates[0], "x_unit": prepared.x_unit,
                                               "metric_units": deepcopy(prepared.metric_units)})
        used.add(region)
    if set(observed) != {sample for sample, _ in domain.facts.replicate_counts}:
        _unbound("The resolved mean groups do not account for every original replicate.")
    result = {}
    for group, count in domain.facts.replicate_counts:
        if len(observed[group]) != count:
            _unbound("A resolved mean group disagrees with its original replicate count.")
        result[group] = tuple(observed[group])
    return result


def group_frequency_request(
    request: dict[str, Any], task: FigureTask, blocks: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    """Group exact source-bound curve datasets; never match a displayed label."""
    value = deepcopy(request)
    binding = value["data_binding"]
    figure = value["template_definition"]["figure_spec"]
    view = figure["views"][0]
    scales = {scale["dimension"]: scale for scale in figure["scales"]}
    if (value["rule_id"] != FREQUENCY_RULE_ID or task.x_metric != "angular_frequency"
            or scales["x"]["quantity"] != task.x_metric or scales["y"]["quantity"] != task.y_metric):
        _unbound("The Managed coordinate quantities must match the selected FigureTask metrics.")
    raw = {item["source_id"]: item for item in binding["data_sources"]}
    nodes = {item["output"]: item for item in binding["transforms"]}
    by_origin = {}
    for layer in view["layers"]:
        pending, origins = [layer["dataset_id"]], set()
        while pending:
            name = pending.pop()
            if name in raw:
                origins.add(name)
            else:
                pending.extend(nodes[name]["inputs"])
        if len(origins) != 1:
            _unbound("Each original frequency curve needs one distinct physical source interval.")
        key = _origin(raw[next(iter(origins))])
        if key in by_origin:
            _unbound("Each original frequency curve needs one distinct physical source interval.")
        by_origin[key] = layer
    retained, slots = [], {}
    for index, (condition, count) in enumerate(task.replicate_counts):
        references = blocks.get(condition, ())
        if any(not _same_unit(scales["x"]["unit"], item["x_unit"])
               or not _same_unit(scales["y"]["unit"], item["metric_units"].get(task.y_metric)) for item in references):
            _unbound("The Managed coordinate units must match the selected FigureTask metrics.")
        identifiers = [_origin(item) for item in references]
        members = [by_origin.pop(item) for item in identifiers if item in by_origin]
        if len(members) != count:
            _unbound("The Managed metric dataset must cover every exact selected original interval.")
        layer = members[0]
        slot = binding["slots"][layer["id"]]
        layer["label"] = layer["legend"]["label"] = slot["sample"] = condition
        if count > 1:
            kind = "rheology_mean_exact_x"
            output = "frequency-group:" + str(index)
            binding["transforms"].append({"id": "frequency-mean:" + str(index), "kind": kind,
                "inputs": [item["dataset_id"] for item in members], "output": output,
                "parameters": {"x_column": "x"}, "executor": builtin_executor(kind), "determinism": "deterministic"})
            layer["dataset_id"] = output
            slot["x"]["source_id"] = slot["y"]["source_id"] = output
        retained.append(layer)
        slots[layer["id"]] = slot
    if by_origin:
        _unbound("The metric includes an original interval outside the exact mean FigurePlan.")
    view["layers"] = retained
    binding["slots"] = slots
    binding["provenance"]["figure_task"] = task.to_payload()
    binding["provenance"]["frequency_mean_original_blocks"] = {group: list(items) for group, items in blocks.items()}
    return value


def _same_unit(actual: str, expected: str | None) -> bool:
    if expected is None:
        return False
    try:
        return resolve_unit_relation(actual, expected)["kind"] == "identity"
    except DocumentError:
        return False


def _origin(value: dict[str, Any]) -> tuple[Any, ...]:
    selection = value["table_selection"]
    return (str(Path(value["path"]).resolve()), value["sha256"], selection["sheet"],
            tuple(selection["header_rows"]), selection["data_start_row"], selection["data_end_row"],
            selection.get("unit_row"), selection.get("sample_row"))


def _unbound(message: str) -> NoReturn:
    raise TaskControlError("frequency_managed_group_origin_unavailable", message)
