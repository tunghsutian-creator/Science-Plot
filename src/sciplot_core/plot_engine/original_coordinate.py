"""Original column/unit evidence through declared deterministic graph edges."""

from typing import Any, NoReturn

from sciplot_core.plot_transforms import require_builtin
from sciplot_core.plot_transforms.schema import validate_node
from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation

from .errors import EngineError
from .managed_source_groups import physical_path


Origin = tuple[dict[str, Any], int, int, int, dict[str, Any], list[str]]


def _unsupported() -> NoReturn:
    raise EngineError("managed_unit_lineage_unsupported", "The coordinate lacks an exact supported original-column unit lineage.")


def _region_matches(source: dict[str, Any], binding: dict[str, Any], semantic: dict[str, Any]) -> bool:
    region, recorded = source["table_selection"], binding["table_selection"]
    if region == recorded:
        return True
    bounds = {"data_start_row", "data_end_row"}
    if {key: value for key, value in region.items() if key not in bounds} != {
            key: value for key, value in recorded.items() if key not in bounds}:
        return False
    # An explicitly recorded stage may narrow its parent block. A numerical
    # subset alone is not evidence of a selected acquisition stage.
    return any(source["source_id"] == stage.get("source_id")
               and stage["block_id"] == binding["block_id"] and stage["table_selection"] == recorded
               and all(stage[key] == region[key] for key in bounds)
               and recorded["data_start_row"] <= region["data_start_row"] < region["data_end_row"] <= recorded["data_end_row"]
               and type(stage.get("point_count")) is int and stage["point_count"] == region["data_end_row"] - region["data_start_row"]
               for stages in semantic.get("stages", {}).values() for stage in stages)


def _unit_context(document: dict[str, Any], source: dict[str, Any], key: str,
                  observed: dict[str, Any] | None, unit: str, quantity: str | None, *,
                  fact: dict[str, Any] | None, bound_quantities: dict[tuple[str, str], str]) -> dict[str, Any]:
    from sciplot_core.source_inspection.semantic_evidence import _quantity

    header = fact["raw_metadata"]["header"] if fact is not None else observed["label"] if observed is not None else None
    source_quantity = _quantity(header) if header is not None else None
    bound = bound_quantities.get((source["source_id"], key))
    context: dict[str, Any] = {"quantity": quantity or bound or source_quantity, "observed_quantity": source_quantity,
                               "explicit_quantity_binding": bound is not None}
    # create_managed_document stores Binding provenance under this owner. Graph
    # renames, layer labels and other top-level provenance are not source facts.
    semantic = document["scientific"]["provenance"].get("binding", {}).get("semantic_task", {})
    coordinates = [coordinate for binding in semantic.get("resolution", {}).get("bindings", [])
                   if physical_path(binding["source_path"]) == physical_path(source["path"])
                   and binding["source_sha256"] == source.get("sha256")
                   and _region_matches(source, binding, semantic)
                   for coordinate in binding["coordinates"].values() if coordinate.get("column_id") == key]
    if coordinates and any("unit_context" in coordinate for coordinate in coordinates):
        contexts = [coordinate.get("unit_context") for coordinate in coordinates]
        proof = contexts[0]
        if (not isinstance(proof, dict) or any(item != proof for item in contexts)
                or proof.get("version") != 1 or type(proof.get("explicit_quantity_binding")) is not bool
                or header is not None and proof.get("observed_quantity") != source_quantity
                or quantity is not None and quantity != proof.get("quantity")):
            _unsupported()
        if any(coordinate["source_unit"] != unit or header is not None and coordinate["header"] != header
               or any(proof.get(field) != coordinate.get(name) for field, name in (
                   ("quantity", "quantity"), ("observed_quantity", "observed_quantity"), ("source_header", "header")))
               for coordinate in coordinates):
            _unsupported()
        context = {"quantity": proof["quantity"], "observed_quantity": proof["observed_quantity"],
                   "explicit_quantity_binding": proof["explicit_quantity_binding"]}
    if fact is not None:
        # A spelling confirmation cannot erase the original physical unit cell.
        original = fact["raw_metadata"]["unit"]
        if original and original != unit:
            resolve_unit_relation(original, unit, **context)
    return context


def coordinate_origins(document: dict[str, Any], dataset: str, column: str, unit: str, *,
                       quantity: str | None = None,
                       datasets: dict[str, dict[str, Any]] | None = None,
                       column_facts: dict[str, dict[str, Any]] | None = None,
                       bound_quantities: dict[tuple[str, str], str] | None = None,
                       explicit_quantity_binding: bool = False,
                       binding_sources: set[str] | None = None) -> list[Origin]:
    """Trace only supported, typed unit/column identities; never execute science.

    Numeric scale operations retain unit evidence. Normalization and rheology
    derivation may only be crossed for a column they leave untouched. Every
    returned physical range remains explicit, including concatenated stages.
    """
    science = document["scientific"]
    sources = {source["source_id"]: source for source in science["data_sources"]}
    nodes = {node["output"]: node for node in science["transforms"]}
    if len(nodes) != len(science["transforms"]) or sources.keys() & nodes.keys():
        _unsupported()
    raw = datasets if datasets is not None else science["provenance"].get("datasets", {})

    def walk(name: str, key: str, expected: str, visiting: frozenset[str]) -> list[Origin]:
        if name in visiting:
            _unsupported()
        if name in sources:
            source, region = sources[name], sources[name]["table_selection"]
            if not key.startswith("column:") or not key.removeprefix("column:").isdigit():
                _unsupported()
            observed = raw.get(name, {}).get("columns", {}).get(key)
            fact = (column_facts or {}).get(name, {}).get(key)
            if observed is not None and observed["unit"] != expected or fact is not None and fact["unit"] != expected:
                _unsupported()
            bindings = dict(bound_quantities or {})
            if explicit_quantity_binding and quantity is not None and (binding_sources is None or name in binding_sources):
                bindings[(name, key)] = quantity
            context = _unit_context(document, source, key, observed, expected, quantity,
                                    fact=fact, bound_quantities=bindings)
            resolve_unit_relation(expected, expected, **context)
            return [(source, int(key.removeprefix("column:")), region["data_start_row"], region["data_end_row"], context, [])]
        if name not in nodes:
            _unsupported()
        node = validate_node(nodes[name])
        kind, params = node["kind"], node["parameters"]
        if node["determinism"] != "deterministic" or node["kind"] == "external":
            _unsupported()
        try:
            require_builtin(node)
        except ValueError:
            _unsupported()
        if kind == "select" and key not in params["columns"]:
            _unsupported()
        if kind == "rename":
            reverse = {renamed["id"]: original for original, renamed in params["columns"].items()}
            if len(reverse) != len(params["columns"]) or key in params["columns"] and key not in reverse:
                _unsupported()
            key = reverse.get(key, key)
        projected = kind == "convert_unit" and key in params["columns"]
        if projected:
            if expected != params["to_unit"]:
                _unsupported()
            expected = params["from_unit"]
        if (kind == "normalize" and key in params["columns"]
                or kind == "rheology_complex_viscosity" and key == params["output_column"]
                or kind not in {"select", "row_slice", "rename", "convert_unit", "scale", "normalize",
                                "time_offset", "rheology_complex_viscosity", "concat_time"}):
            _unsupported()
        origins = [origin for input_name in node["inputs"]
                   for origin in walk(input_name, key, expected, visiting | {name})]
        if projected:
            for origin in origins:
                resolve_unit_relation(params["from_unit"], params["to_unit"], **origin[4])
        if kind == "row_slice":
            first, last = params["start"], params["end"]
            if not 0 <= first < last <= sum(end - start for _, _, start, end, _, _ in origins):
                _unsupported()
            selected = []
            offset = 0
            for source, index, start, end, context, operations in origins:
                low, high = max(0, first - offset), min(end - start, last - offset)
                if low < high:
                    selected.append((source, index, start + low, start + high, context, operations))
                offset += end - start
            origins = selected
        return [(source, index, start, end, context, [*operations, kind])
                for source, index, start, end, context, operations in origins]

    return walk(dataset, column, unit, frozenset())
