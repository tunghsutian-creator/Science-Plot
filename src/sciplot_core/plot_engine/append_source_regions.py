"""Consume shared byte-bound physical blocks for source-append continuation."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.raw_tables import _original_text
from sciplot_core.data_mapping.original_tables import read_original_table, table_position
from sciplot_core.data_mapping.table_choice import select_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_inspection.rheology_evidence import instrument_candidate
from sciplot_core.source_inspection.semantic_evidence import _column
from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables

from .errors import EngineError


def _observed(snapshot: dict[str, Any]) -> dict[str, Any]:
    observed = inspect_semantic_tables(snapshot["source"], sheets=snapshot.get("observed_sheets"))
    if observed["sha256"] != snapshot["file_sha256"]:
        raise EngineError("managed_append_source_changed", "The original file changed while inspecting physical source blocks.")
    return observed


def append_source_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose each confirmed block's own metadata and region, never its arrays."""
    result = []
    for candidate in _observed(snapshot)["candidates"]:
        for block in candidate["blocks"]:
            selection = block.get("table_selection", candidate["table_selection"])
            selected = select_table(snapshot, selection)
            result.append({"candidate_id": candidate["candidate_id"], "block_id": block["block_id"],
                "table_selection": deepcopy(selection),
                **{key: deepcopy(block[key]) for key in ("test_name", "test_row", "result", "result_row", "source_interval") if key in block},
                "columns": [{key: column[key] for key in ("index", "header", "unit", "sample", "metadata_conflicts")}
                            for column in selected["columns"] if column["index"] in block["column_indices"]]})
    return result


def _same_start(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = ("sheet", "header_rows", "unit_row", "sample_row", "data_start_row")
    return (all(left.get(key) == right.get(key) for key in fields)
            and left.get("expand_merged_metadata", False) == right.get("expand_merged_metadata", False))


def _same_region(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _same_start(left, right) and left["data_end_row"] == right["data_end_row"]


def _physical_candidates(snapshot: dict[str, Any], sheet: str | None) -> list[dict[str, Any]]:
    """Use the shared instrument observer without re-inferring ordinary tables.

    An explicit ordinary region already has its metadata/data bounds. Generic
    discovery ambiguity elsewhere in that file cannot revoke this old route.
    Recognized unsupported instruments still raise the shared layout error.
    """
    path = Path(snapshot["source"])
    candidates = []
    for position, table in enumerate(snapshot["tables"]):
        if table["sheet"] != sheet:
            continue
        frame = read_original_table(path, table["sheet"], snapshot["file_sha256"])
        candidate = instrument_candidate(frame, sheet=table["sheet"], position=table_position(table, position),
                                         source=path, column_reader=_column)
        if candidate is not None:
            candidates.append(candidate)
    if file_sha256(path) != snapshot["file_sha256"]:
        raise EngineError("managed_append_source_changed", "The original file changed while confirming physical source blocks.")
    return candidates


def confirm_append_region(snapshot: dict[str, Any], source: dict[str, Any],
                          curves: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Confirm exact independently parsed Test regions; retain the old fallback.

    A different same-file region requires this proof in the existing identity
    guard. Ordinary explicit tables retain their established same-region route.
    """
    blocks = [(candidate, block) for candidate in _physical_candidates(snapshot, source["table_selection"]["sheet"])
              for block in candidate["blocks"]]
    matches = [(candidate, block) for candidate, block in blocks
               if _same_region(source["table_selection"], block["table_selection"])]
    complete = bool(matches)
    if not matches:
        # This is identity evidence only. A prefix cannot acquire permission to
        # add a different region; the old same-region guard still decides that.
        matches = [(candidate, block) for candidate, block in blocks
                   if _same_start(source["table_selection"], block["table_selection"])]
    if not matches:
        return None
    if len(matches) != 1:
        raise EngineError("managed_append_region_conflict", "The requested source region must identify exactly one observed physical block.")
    candidate, block = matches[0]
    if not source["table_selection"]["data_start_row"] < source["table_selection"]["data_end_row"] <= block["data_end_row"]:
        raise EngineError("managed_append_region_conflict", "An original Test prefix must stay within that Test's observed physical body.")
    if not block.get("test_name") or "test_row" not in block:
        return None
    for curve in curves:
        if curve["sample"] != block["test_name"]:
            raise EngineError("managed_append_sample_conflict", "The appended scientific sample must preserve this physical block's literal Test identity; use label for a display alias.")
        if any(curve[axis + "_column_index"] not in block["column_indices"] for axis in ("x", "y")):
            raise EngineError("managed_append_column_missing", "Bind original columns declared by the selected physical block.")
    proof = {"source_sha256": snapshot["file_sha256"], "table_id": candidate["candidate_id"],
             "block_id": block["block_id"], "table_selection": deepcopy(block["table_selection"]),
             **{key: deepcopy(block[key]) for key in ("test_name", "test_row", "result", "result_row", "source_interval") if key in block}}
    # Reuse the existing source-cell metadata contract so a later original
    # reload verifies Test identity as well as quantities, units and source SHA.
    frame = read_original_table(Path(source["path"]), source["table_selection"]["sheet"], source["sha256"])
    evidence = {"kind": "source_cell", "sheet": source["table_selection"]["sheet"],
                "row_index": block["test_row"], "column_index": 1,
                "text": _original_text(frame.iat[block["test_row"], 1])}
    confirmations = source.setdefault("metadata_confirmations", [])
    for index in sorted({curve[axis + "_column_index"] for curve in curves for axis in ("x", "y")}):
        item = {"source_sha256": source["sha256"], "sheet": source["table_selection"]["sheet"],
                "column_index": index, "field": "sample", "value": block["test_name"], "evidence": evidence}
        if item not in confirmations:
            confirmations.append(item)
    return proof if complete else None
