"""Exact raw instrument region bindings for a resolved mean FigurePlan."""
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.foundation.text_values import clean_text
from sciplot_core.semantic_sources.rheology_sweep_domain import FREQUENCY_RULE_ID, ResolvedRheologySweepDomain
from sciplot_core.task_errors import TaskControlError


def resolve_mean_group_blocks(
    domain: ResolvedRheologySweepDomain,
    plan: ResolvedFigurePlan,
    sources: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, str], ...]]:
    """Bind the legacy grouping authority by original file, header and row window."""
    if (domain.replicate_mode != "mean" or domain.rule_id != FREQUENCY_RULE_ID or plan.rule_id != FREQUENCY_RULE_ID
            or plan.source_sha256 != domain.source_sha256
            or any(task.replicate_counts != domain.facts.replicate_counts for task in plan.tasks)):
        _unbound("The selected FigurePlan must belong to the exact prepared frequency domain.")
    available: dict[tuple[Path, int, int, int], list[dict[str, str]]] = {}
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
                    "table_id": candidate["candidate_id"], "block_id": block["block_id"]})
    observed: dict[str, list[dict[str, str]]] = {}
    used: set[tuple[Path, int, int, int]] = set()
    for sample in domain.raw_samples:
        if sample.original_group_region is None:
            _unbound("Each prepared replicate must bind one physical original instrument interval.")
        region = (sample.source.resolve(), *sample.original_group_region)
        candidates = available.get(region, [])
        if len(candidates) != 1 or region in used:
            _unbound("A selected frequency replicate did not match one distinct original block.")
        group = clean_text(sample.sample) or sample.source.stem
        observed.setdefault(group, []).append(candidates[0])
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
    request: dict[str, Any], task: FigureTask, blocks: dict[str, tuple[dict[str, str], ...]],
) -> dict[str, Any]:
    """Group exact source-bound curve datasets; never match a displayed label."""
    value = deepcopy(request)
    binding = value["data_binding"]
    view = value["template_definition"]["figure_spec"]["views"][0]
    raw = {item["source_id"] for item in binding["data_sources"]}
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
        if len(origins) != 1 or next(iter(origins)) in by_origin:
            _unbound("Each original frequency curve needs one distinct physical source interval.")
        by_origin[next(iter(origins))] = layer
    retained, slots = [], {}
    for index, (condition, count) in enumerate(task.replicate_counts):
        identifiers = [item["source_id"] + ":" + item["block_id"] for item in blocks.get(condition, ())]
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


def _unbound(message: str) -> NoReturn:
    raise TaskControlError("frequency_managed_group_origin_unavailable", message)
