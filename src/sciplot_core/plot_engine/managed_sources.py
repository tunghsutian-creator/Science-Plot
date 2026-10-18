"""Load explicit managed table bindings through the existing original-table owner."""

from pathlib import Path
from typing import Any
import math

from sciplot_core.data_mapping.table_choice import read_original_table, select_table, source_table_snapshot
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.plot_transforms import ordered_nodes

from .errors import EngineError


@with_table_reads
def load_sources(document: dict[str, Any], rule_id: str) -> dict[str, dict[str, Any]]:
    datasets: dict[str, dict[str, Any]] = {}
    samples: dict[str, dict[str, set[str]]] = {}
    for source in document["scientific"]["data_sources"]:
        path = Path(source["path"])
        if not path.is_absolute() or not path.is_file() or file_sha256(path) != source["sha256"]:
            raise EngineError("managed_source_changed", "Use the exact original source bytes or explicitly refresh their scientific binding.")
        if "table_selection" not in source:
            raise EngineError("managed_table_selection_required", "Managed data requires explicit original worksheet and row bounds.")
        # Managed bindings already declare exact original rows/columns. The
        # ordinary curve-discovery adapter gate cannot classify these bindings
        # (e.g. categorical tensile summaries) or rename their scientific rule.
        snapshot = source_table_snapshot(path, rule_id=rule_id)
        if snapshot is None:
            raise EngineError("managed_source_unsupported", "This source format does not support explicit original-table binding.")
        selected = select_table(snapshot, source["table_selection"], source.get("metadata_confirmations"))
        selection = selected["table_selection"]
        frame = read_original_table(path, selection["sheet"], source["sha256"])
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
                action="correct_binding", source_id=source["source_id"], source=str(path), issues=issues,
                allowed_changes=["binding_column", "binding_unit", "metadata_confirmation", "explicit_transform", "display_label"],
            )
            error.repair["message"] = "Correct the binding to the observed source metadata. Unit conversion requires an explicit scientific transform; display labels do not rename raw quantities."
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
