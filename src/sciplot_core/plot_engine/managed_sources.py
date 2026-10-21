"""Load explicit managed table bindings through the existing original-table owner."""

from pathlib import Path
from typing import Any
import math

from sciplot_core.data_mapping.original_tables import read_original_table, source_table_snapshot
from sciplot_core.data_mapping.table_choice import select_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.plot_transforms import ordered_nodes

from .errors import EngineError


def _selected_original_columns(document: dict[str, Any], source_id: str) -> set[str] | None:
    """Only an exclusively selecting source boundary may omit unrelated columns."""
    if any(mapping[axis]["source_id"] == source_id for mapping in document["scientific"]["mappings"].values() for axis in ("x", "y")):
        return None
    consumers = [node for node in document["scientific"]["transforms"] if source_id in node["inputs"]]
    if not consumers or any(node["kind"] != "select" or node["inputs"] != [source_id] for node in consumers):
        return None
    # Validate the original typed nodes, including executor descriptors, before
    # treating their declared columns as a source loading restriction.
    from sciplot_core.plot_transforms import builtin_executor, validate_node

    for node in consumers:
        validate_node(node)
        if node["executor"] != builtin_executor() or node["determinism"] != "deterministic":
            raise EngineError("managed_source_select_invalid", "Original column selection requires the current deterministic builtin executor.")
    return {name for node in consumers for name in node["parameters"]["columns"]}


@with_table_reads
def _selected_source(source: dict[str, Any], rule_id: str) -> dict[str, Any]:
    path = Path(source["path"])
    if not path.is_absolute() or not path.is_file() or file_sha256(path) != source["sha256"]:
        raise EngineError("managed_source_changed", "Use the exact original source bytes or explicitly refresh their scientific binding.")
    if "table_selection" not in source:
        raise EngineError("managed_table_selection_required", "Managed data requires explicit original worksheet and row bounds.")
    snapshot = source_table_snapshot(path, rule_id=rule_id, sheets=[source["table_selection"]["sheet"]])
    if snapshot is None:
        raise EngineError("managed_source_unsupported", "This source format does not support explicit original-table binding.")
    selected = select_table(snapshot, source["table_selection"], source.get("metadata_confirmations"))
    selected["table_id"] = next(table["table_id"] for table in snapshot["tables"] if table["sheet"] == source["table_selection"]["sheet"])
    return selected


def _column_facts(selected: dict[str, Any]) -> dict[str, Any]:
    return {f"column:{column['index']}": {"raw_metadata": dict(column["raw_metadata"]),
            "header": column["header"], "unit": column["unit"]} for column in selected["columns"]}


@with_table_reads
def load_source_facts(document: dict[str, Any], rule_id: str) -> dict[str, dict[str, Any]]:
    """Project scoped source metadata without decoding persisted dataset arrays.

    The original-table reader parses the selected worksheet, including numeric
    cells; this port only returns its column metadata.
    """
    return {source["source_id"]: _column_facts(_selected_source(source, rule_id))
            for source in document["scientific"]["data_sources"]}


@with_table_reads
def load_sources(document: dict[str, Any], rule_id: str, *,
                 column_facts: dict[str, dict[str, Any]] | None = None,
                 source_frames: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    datasets: dict[str, dict[str, Any]] = {}
    samples: dict[str, dict[str, set[str]]] = {}
    for source in document["scientific"]["data_sources"]:
        path = Path(source["path"])
        selected = _selected_source(source, rule_id)
        if column_facts is not None:
            column_facts[source["source_id"]] = _column_facts(selected)
        required_columns = _selected_original_columns(document, source["source_id"])
        if required_columns is not None:
            available = {f"column:{column['index']}" for column in selected["columns"]}
            if not required_columns <= available:
                raise EngineError("managed_source_select_invalid", "An original column selection references an absent source column.")
            selected["columns"] = [column for column in selected["columns"] if f"column:{column['index']}" in required_columns]
        selection = selected["table_selection"]
        frame = read_original_table(path, selection["sheet"], source["sha256"])
        if source_frames is not None:
            source_frames[source["source_id"]] = {"frame": frame, "table_id": selected["table_id"]}
        start, end = selection["data_start_row"], selection["data_end_row"]
        columns: dict[str, Any] = {}
        for column in selected["columns"]:
            values: list[float | None] = []
            for raw in frame.iloc[start:end, column["index"]]:
                if raw is None or str(raw).strip() in {"", "nan"}:
                    values.append(None)
                    continue
                try:
                    number = float(raw)
                except (TypeError, ValueError) as exc:
                    raise EngineError("managed_source_nonnumeric", "Managed datasets currently require numeric columns in the explicit region.") from exc
                if not math.isfinite(number):
                    raise EngineError("managed_source_nonfinite", "Infinite numeric values cannot be represented as finite managed data.")
                values.append(number)
            columns[f"column:{column['index']}"] = {"label": column["header"], "unit": column["unit"], "values": values}
        issues: list[dict[str, Any]] = []
        for column in selected["columns"]:
            for problem in column["metadata_conflicts"]:
                field = problem["field"]
                original = column["raw_metadata"]["header" if field == "quantity" else field]
                issues.append({"source_id": source["source_id"], "source": str(path), "sheet": selection["sheet"],
                               "column_index": column["index"], "field": field,
                               "expected": problem.get("original", original),
                               "actual": problem.get("declared", problem.get("values", problem)),
                               "code": problem["code"], "cell_evidence": column["cell_evidence"]})
        for mapping_id, mapping in document["scientific"]["mappings"].items():
            for axis in ("x", "y"):
                coordinate = mapping.get(axis, {})
                if coordinate.get("source_id") != source["source_id"]:
                    continue
                index = coordinate.get("column_index")
                column = next((item for item in selected["columns"] if item["index"] == index), None)
                context = {"source_id": source["source_id"], "source": str(path), "sheet": selection["sheet"],
                           "mapping_id": mapping_id, "coordinate": axis, "column_index": index}
                if column is None:
                    issues.append({**context, "field": "column_index", "expected": [item["index"] for item in selected["columns"]],
                                   "actual": index})
                    continue
                for field, expected, actual in (("column", column["header"], coordinate["column"]),
                                                ("unit", column["unit"], mapping[axis + "_unit"])):
                    if expected != actual:
                        issues.append({**context, "field": field, "expected": expected, "actual": actual,
                                       "cell_evidence": column["cell_evidence"]})
        if issues:
            error = EngineError(
                "managed_metadata_conflict", "Bindings must preserve exact original column quantities and units.",
                action="plot.describe", description={"scope": "edit", "target": "source:" + source["source_id"], "property": "source.sha256"},
                target="source:" + source["source_id"],
                property="source.sha256", source_id=source["source_id"], source=str(path), issues=issues,
                allowed_changes=["source.sha256"],
            )
            error.repair["message"] = "Inspect the current source reconfirmation contract. A conversion requires an existing explicit scientific transform; incompatible column remapping requires a new explicit binding, and display labels do not rename raw quantities."
            error.issues = issues
            raise error
        if file_sha256(path) != source["sha256"]:
            raise EngineError("managed_source_changed", "The source changed during original-table reading.")
        identifier = source["source_id"]
        samples[identifier] = {f"column:{column['index']}": {column["sample"]} if column["sample"] else set()
                               for column in selected["columns"]}
        datasets[identifier] = {"id": identifier, "columns": columns, "provenance": {"sources": [{
            "source_id": identifier, "sha256": source["sha256"], "table_selection": selection,
            "column_indices": {f"column:{item['index']}": item["index"] for item in selected["columns"]},
            "rows": list(range(start, end))}], "transforms": []}}
    _require_sample_lineage(document, samples)
    return datasets


def _require_sample_lineage(document: dict[str, Any], raw: dict[str, dict[str, set[str]]]) -> None:
    """Carry original sample evidence through declared column-preserving operations."""
    known = {name: dict(columns) for name, columns in raw.items()}
    unknown: dict[str, set[str]] = {}
    for node in ordered_nodes(document["scientific"]["transforms"], list(raw)):
        source, output = node["inputs"][0], node["output"]
        columns = dict(known.get(source, {}))
        unresolved = unknown.get(source)
        if node["kind"] == "concat_time":
            inputs = node["inputs"]
            if any(name in unknown for name in inputs):
                unknown[output] = set().union(*(unknown[name] if name in unknown else
                                               set().union(*known[name].values()) for name in inputs))
                known[output] = {}
                continue
            if any(set(known[name]) != set(columns) for name in inputs):
                raise EngineError("managed_column_lineage_missing", "Every concatenated stage must preserve the same original column identities.")
            known[output] = {column: set().union(*(known[name][column] for name in inputs)) for column in columns}
            continue
        if node["kind"] == "external":
            # An arbitrary fixed executor has no declared column lineage. A
            # unique original sample remains unambiguous; mixed samples cannot
            # be assigned to its output columns by position or label guessing.
            unknown[output] = (set(unresolved) if unresolved is not None else
                               set().union(*columns.values()))
            known[output] = {}
            continue
        if unresolved is not None:
            unknown[output] = set(unresolved)
            known[output] = {}
            continue
        if node["kind"] == "select":
            if any(name not in columns for name in node["parameters"]["columns"]):
                raise EngineError("managed_column_lineage_missing", "A transform selects an absent original column.")
            columns = {name: columns[name] for name in node["parameters"]["columns"]}
        elif node["kind"] == "rheology_complex_viscosity":
            parameters = node["parameters"]
            inputs = [parameters[role + "_column"] for role in ("frequency", "storage", "loss")]
            if any(name not in columns for name in inputs):
                raise EngineError("managed_column_lineage_missing", "Viscosity derivation requires each original input column.")
            columns[parameters["output_column"]] = set().union(*(columns[name] for name in inputs))
        elif node["kind"] == "rename":
            renames = node["parameters"]["columns"]
            if any(name not in columns for name in renames):
                raise EngineError("managed_column_lineage_missing", "A transform renames an absent original column.")
            renamed = {renames[name]["id"] if name in renames else name: sample for name, sample in columns.items()}
            if len(renamed) != len(columns):
                raise EngineError("managed_column_lineage_collision", "Renaming cannot overwrite another original column.")
            columns = renamed
        known[output] = columns
    for mapping in document["scientific"]["mappings"].values():
        for axis in ("x", "y"):
            coordinate = mapping[axis]
            source = coordinate["source_id"]
            if source in unknown:
                expected = unknown[source]
                if len(expected) > 1:
                    raise EngineError("managed_sample_lineage_unknown", "An external transform of mixed samples has no explicit column lineage; select one original sample before execution.")
            else:
                column = ("column:" + str(coordinate["column_index"]) if "column_index" in coordinate else coordinate["column"])
                if column not in known.get(source, {}):
                    raise EngineError("managed_column_lineage_missing", "The scientific mapping references an absent original or transformed column.")
                expected = known[source][column]
            if expected and expected != {mapping["sample"]}:
                raise EngineError("managed_sample_conflict", "The bound sample must preserve its original metadata through every scientific transform.")
