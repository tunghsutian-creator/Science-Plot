"""Load explicit managed table bindings through the existing original-table owner."""

from pathlib import Path
from typing import Any
import math

from sciplot_core.data_mapping.table_choice import _read, select_table, source_table_snapshot
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
        frame = _read(path, selection["sheet"], source["sha256"])
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
        for mapping in document["scientific"]["mappings"].values():
            for axis in ("x", "y"):
                coordinate = mapping.get(axis, {})
                if coordinate.get("source_id") != source["source_id"]:
                    continue
                index = coordinate.get("column_index")
                column = next((item for item in selected["columns"] if item["index"] == index), None)
                if column is None or column["header"] != coordinate["column"] or column["unit"] != mapping[axis + "_unit"]:
                    raise EngineError("managed_metadata_conflict", "Bindings must preserve exact original column quantities and units.")
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
