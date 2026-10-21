"""Bind explicit XY choices without replacing original samples with aliases."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from sciplot_core.data_mapping.output_files import _safe_output_name
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.mapping_contract.source_identity import source_view_id
from sciplot_core.materials_rules import get_rule


def pair_proposal_contents(snapshot: dict[str, Any], pairs: list[dict[str, Any]], *,
                           select_pair: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
                           structured_identity: bool = False) -> dict[str, Any]:
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 32:
        raise ValueError("Select 1–32 explicit x/y pairs.")
    source = Path(snapshot["source"])
    references: list[DataSourceReference] = []
    mappings: list[DataColumnMapping] = []
    labels: dict[str, str] = {}
    units: dict[str, str] = {}
    display_labels: dict[str, str] = {}
    selected_y: dict[tuple[str | None, int], list[tuple[int, int]]] = {}
    for index, pair in enumerate(pairs):
        selected = select_pair(snapshot, pair)
        selection = selected["table_selection"]
        columns = {column["index"]: column for column in selected["columns"]}
        if any(pair[key] not in columns for key in ("x_column", "y_column")):
            raise ValueError("Each pair needs original integer x_column/y_column indices.")
        x, y = columns[pair["x_column"]], columns[pair["y_column"]]
        if x["index"] == y["index"] or not x["x_eligible"] or not y["y_eligible"]:
            if get_rule(snapshot["rule_id"]).scientific_source_adapter == "stress_relaxation":
                from sciplot_core.semantic_sources.stress_relaxation_wide import StressSourceBindingError

                bad = x if not x["x_eligible"] else y
                raise StressSourceBindingError(f"series_{index:03}", bad["index"],
                    "explicit stress time/normalized-response identity, units, and complete selected rows",
                    {"header": bad["header"], "x": x["x_rejection_reasons"], "y": y["y_rejection_reasons"]})
            raise ValueError(f"Pair {index} in {selection['sheet']!r} needs explicit axis names, observed units, and finite numeric values; "
                             f"x_column={x['index']}: {x['x_rejection_reasons']}; y_column={y['index']}: {y['y_rejection_reasons']}.")
        y_identity = (selection["sheet"], y["index"])
        bounds = (selection["data_start_row"], selection["data_end_row"])
        if any(max(bounds[0], start) < min(bounds[1], end) for start, end in selected_y.get(y_identity, [])):
            raise ValueError("Overlapping rows of a response column cannot be assigned to multiple samples.")
        selected_y.setdefault(y_identity, []).append(bounds)
        sample = y["sample"] or x["sample"] or (source.stem if len(pairs) == 1 and selection.get("sample_row") is None else "")
        if not sample or (x["sample"] and x["sample"] != sample):
            raise ValueError("Selected columns belong to different samples or lack an original sample label; shared X requires an empty sample cell.")
        label = pair.get("label", sample)
        if structured_identity and label in display_labels.values():
            raise ValueError("XY display labels must be distinct; aliases do not change scientific samples.")
        if not structured_identity:
            sample = label
        if not structured_identity and sample in labels.values():
            raise ValueError("Duplicate sample labels require an explicit source correction; samples cannot be merged silently.")
        source_id = (source_view_id(str(source.resolve()), selection, [x["index"], y["index"]])
                     if structured_identity else f"series_{index:03}")
        display_labels[source_id] = label
        labels[source_id] = sample
        references.append(DataSourceReference(
            source_id, source.name, snapshot["file_sha256"], sheet=selection["sheet"], header_row=None,
            data_start_row=selection["data_start_row"], data_end_row=selection["data_end_row"],
            cell_evidence={**x["cell_evidence"], **y["cell_evidence"]},
            identity=({"version": 1, "source_namespace": str(source.resolve()), "category": sample,
                       "condition": None} if structured_identity else {}),
        ))
        for role, column in (("x", x), ("y", y)):
            mappings.append(DataColumnMapping(source_id, column["index"], column["output_header"], role,
                                              expected_header=f"column_{column['index']}"))
            if column["output_header"] in units and units[column["output_header"]] != column["unit"]:
                raise ValueError("Selected output headers have conflicting units.")
            units[column["output_header"]] = column["unit"]
    contents: dict[str, Any] = dict(sources=tuple(references), columns=tuple(mappings), sample_labels=labels, unit_overrides=units)
    if structured_identity:
        contents["display_labels"] = display_labels
    else:
        proposal = DataMappingProposal(base_request_sha256="0" * 64, **contents, provider="explicit_table_choice")
        used: set[str] = set()
        for reference in references:
            if Path(_safe_output_name(reference, proposal, used=used)).stem != labels[reference.source_id]:
                raise ValueError("The selected sample label cannot be preserved exactly in the mapped output filename.")
    if file_sha256(source) != snapshot["file_sha256"]:
        raise ValueError("Table-choice source changed while creating the proposal.")
    return contents
