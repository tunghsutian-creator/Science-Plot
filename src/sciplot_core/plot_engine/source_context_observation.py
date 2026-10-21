"""Re-observe literal semantic facts from the current loader's original frame."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_transforms import builtin_executor, validate_node
from sciplot_core.source_inspection.rheology_evidence import instrument_candidate
from sciplot_core.source_inspection.semantic_evidence import _column
from sciplot_core.task_semantic_coordinates import resolved_binding
from sciplot_core.task_semantic_figure import _select_column
from sciplot_core.task_semantic_frequency import frequency_condition, frequency_derivation

from .errors import EngineError
from .managed_source_groups import physical_path
from .original_coordinate import Origin, _region_matches, coordinate_origins


def observe_binding(observed: dict[str, Any], source: dict[str, Any], binding: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frame = observed["frame"]
    region = binding["table_selection"]
    if binding["table_id"] != observed["table_id"]:
        raise EngineError("managed_source_reconfirmation_required", "The source context must retain its original worksheet identity.")
    candidate = instrument_candidate(frame, sheet=region["sheet"], position=int(observed["table_id"].removeprefix("table:")),
                                     source=Path(physical_path(source["path"])), column_reader=_column)
    if candidate is None:
        columns = [_column(frame.iloc[:region["data_end_row"]], index, region["header_rows"][-1],
                           region.get("unit_row"), region["data_start_row"]) for index in range(frame.shape[1])]
        block = {"block_id": binding["block_id"], "table_selection": region, "columns": columns}
        candidate = {"candidate_id": binding["table_id"], "columns": columns, "blocks": [block]}
    blocks = [block for block in candidate["blocks"] if block["block_id"] == binding["block_id"]
              and block["table_selection"] == region]
    if len(blocks) != 1:
        raise EngineError("managed_source_reconfirmation_required", "The original physical block no longer matches its source binding.")
    block = blocks[0]
    comparable = {**binding, "source_path": physical_path(binding["source_path"])}
    resolved_binding([comparable], {"path": physical_path(source["path"]), "sha256": source["sha256"]}, candidate, block)
    if binding["condition"] != frequency_condition(block):
        raise EngineError("managed_source_reconfirmation_required", "Original Test/Result/interval condition changed; the existing scientific intent cannot be silently relabelled.")
    return candidate, block


def literal_coordinates(coordinate: dict[str, Any], *, candidate: dict[str, Any], block: dict[str, Any],
                        role: str) -> list[tuple[str, dict[str, Any]]]:
    """Use the semantic owner's original-column comparator for every derivation input."""
    if "derivation" not in coordinate:
        _select_column(candidate, block, coordinate, role)
        return [(role, coordinate)]
    observed = frequency_derivation(block.get("columns", candidate["columns"]), coordinate)
    derived = coordinate["derivation"]
    if (observed is None or any(derived.get(key) != observed[key] for key in ("quantity", "method", "formula"))
            or set(derived["inputs"]) != set(observed["inputs"])):
        raise EngineError("managed_source_reconfirmation_required", "The current derivation requires its exact registered original physical quantities.")
    result = []
    for quantity, item in derived["inputs"].items():
        if item["quantity"] != quantity:
            raise EngineError("managed_source_reconfirmation_required", "A derivation input cannot inherit its output quantity.")
        result.extend(literal_coordinates(item, candidate=candidate, block=block, role=quantity))
    return result


def mapped_derivations(document: dict[str, Any], dataset: str, column: str) -> list[dict[str, Any]]:
    """Locate only the fixed typed derivation on this current public mapping path."""
    nodes = {node["output"]: node for node in document["scientific"]["transforms"]}

    def walk(name: str, key: str, seen: frozenset[str]) -> list[dict[str, Any]]:
        if name not in nodes:
            return []
        if name in seen:
            raise EngineError("managed_source_reconfirmation_required", "A source derivation requires an acyclic current graph.")
        node = validate_node(nodes[name])
        if node["executor"] != builtin_executor() or node["determinism"] != "deterministic":
            return []
        params = node["parameters"]
        if node["kind"] == "rheology_complex_viscosity" and key == params["output_column"]:
            return [node]
        if node["kind"] == "rename":
            key = next((original for original, renamed in params["columns"].items() if renamed["id"] == key), key)
        return [item for input_id in node["inputs"] for item in walk(input_id, key, seen | {name})]

    return walk(dataset, column, frozenset())


def require_derivation_origins(document: dict[str, Any], binding: dict[str, Any], semantic: dict[str, Any],
                               leaves: list[tuple[str, dict[str, Any]]], nodes: list[dict[str, Any]], *,
                               datasets: dict[str, dict[str, Any]], column_facts: dict[str, dict[str, Any]]) -> None:
    """Each typed role must execute the same literal input that its binding proves."""
    fields = {"angular_frequency": "frequency_column", "storage_modulus": "storage_column", "loss_modulus": "loss_column"}
    matched = False
    for node in {item["id"]: item for item in nodes}.values():
        origins: dict[str, list[Origin]] = {}
        for quantity, leaf in leaves:
            origins[quantity] = [origin for origin in coordinate_origins(
                document, node["inputs"][0], node["parameters"][fields[quantity]], leaf["unit"], quantity=quantity,
                datasets=datasets, column_facts=column_facts, binding_sources=set())
                if physical_path(origin[0]["path"]) == physical_path(binding["source_path"])
                and _region_matches(origin[0], binding, semantic)]
        if not any(origins.values()):
            continue
        matched = True
        previous_domain = None
        for quantity, leaf in leaves:
            domain = []
            for source, index, start, end, _context, _operations in origins[quantity]:
                region = source["table_selection"]
                if (source["sha256"] != binding["source_sha256"] or not _region_matches(source, binding, semantic)
                        or index != leaf["column_index"] or leaf["column_id"] != "column:" + str(index)
                        or leaf["quantity"] != quantity or not region["data_start_row"] <= start < end <= region["data_end_row"]):
                    raise EngineError("managed_source_reconfirmation_required", "The typed derivation role differs from its frozen original source, physical column or row region.")
                domain.append((source["source_id"], physical_path(source["path"]), source["sha256"], start, end))
            if not domain or previous_domain is not None and domain != previous_domain:
                raise EngineError("managed_source_reconfirmation_required", "Every typed derivation input must retain the same original physical row domain.")
            previous_domain = domain
    if not matched:
        raise EngineError("managed_source_reconfirmation_required", "The source binding has no matching current typed derivation input.")


def validate_stage_intervals(semantic: dict[str, Any], source: dict[str, Any], binding: dict[str, Any],
                             block: dict[str, Any]) -> None:
    for stages in semantic.get("stages", {}).values():
        for stage in stages:
            if stage.get("source_id") != source["source_id"] or stage["block_id"] != binding["block_id"]:
                continue
            if "source_interval" in stage:
                expected = frequency_condition(block).get("source_interval", block.get("source_interval"))
                if stage["source_interval"] != expected:
                    raise EngineError("managed_source_reconfirmation_required", "The original stage Test/Result/interval evidence changed; retain the source and create an explicit new scientific binding.")
