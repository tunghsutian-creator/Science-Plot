"""Lossless serialization of already sealed PlotIR tables; no scientific math."""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_ir import validate_ir
from sciplot_core.source_coverage.file_snapshots import _physical_file_snapshot


@dataclass(frozen=True)
class PlotData:
    snapshot: dict[str, Any]
    ir: dict[str, Any]


def capture_plot_data(ir_path: Path, *, expected: dict[str, str], sha256: str | None = None) -> PlotData:
    # Callers pass the audited publication's physical artifact, not an original source.
    snapshot = _physical_file_snapshot(ir_path, literal=ir_path, label="Managed delivery exact PlotIR", expected_sha256=sha256)
    ir = validate_ir(json.loads(snapshot["bytes"]))
    if any(ir[key] != value for key, value in expected.items()):
        raise EngineError("managed_delivery_ir_changed", "The sealed dataset snapshot differs from its selected PlotIR/scientific/presentation binding.")
    return PlotData(snapshot, ir)


def _write_dataset_csv(target: Path, columns: dict[str, Any]) -> dict[str, Any]:
    counts = {len(column["values"]) for column in columns.values()}
    if len(counts) != 1:
        raise EngineError("managed_delivery_ragged_columns", "A sealed dataset has inconsistent column lengths; CSV projection cannot pad or truncate it.")
    with target.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([column["label"] for column in columns.values()])
        # Round-trip numeric values, with None alone encoded as an empty cell.
        writer.writerows(zip(*(column["values"] for column in columns.values()), strict=True))
    return {"sha256": file_sha256(target), "row_count": next(iter(counts)), "column_ids": list(columns),
            "columns": [{"id": key, "label": value["label"], "unit": value["unit"]} for key, value in columns.items()],
            "header_rows": 1, "null_encoding": "empty_cell"}


def project_data(data: PlotData, root: Path, stem: str) -> dict[str, Any]:
    snapshot, ir = data.snapshot, data.ir
    destination = root / "data" / "plotted" / stem
    destination.mkdir(parents=True)
    exact = destination / "plot-ir.json"
    exact.write_bytes(snapshot["bytes"])
    records = []
    for index, (identifier, dataset) in enumerate(ir["datasets"].items(), 1):
        target = destination / f"{index:03d}.csv"
        pointer = "/datasets/" + identifier.replace("~", "~0").replace("/", "~1")
        records.append({"dataset_id": identifier, "path": str(target.relative_to(root)),
                        **_write_dataset_csv(target, dataset["columns"]), "provenance_pointer": pointer + "/provenance"})
    return {"ir": {"path": str(exact.relative_to(root)), "sha256": snapshot["sha256"],
                   "ir_hash": ir["ir_hash"], "schema_version": ir["schema_version"]},
            "datasets": records,
            "role_evidence": "Read the exact IR series/layers and dataset provenance to distinguish source, derived and reference data. CSV serialization performs no transforms or reference-value generation."}


def plotted_dataset_csvs(data: PlotData, directory: Path, samples: dict[str, str]) -> list[dict[str, Any]]:
    """Write the scientific coordinates feeding visible layers, without display-only offsets."""
    layer_bindings: dict[str, list[dict[str, Any]]] = {}
    for view in data.ir["views"]:
        for layer in view["layers"]:
            if not layer.get("visible", True):
                continue
            layer_id = layer["id"]
            evidence = {"view_id": view["id"], "layer_id": layer_id, "label": layer["label"], "role": layer["role"],
                        "mappings": layer["mappings"],
                        "display_curve": any(mark["id"] in data.ir.get("display_curves", {}) for mark in layer["marks"])}
            if layer_id in samples:
                evidence["sample"] = samples[layer_id]
            layer_bindings.setdefault(layer["dataset_id"], []).append(evidence)
    if not layer_bindings:
        raise EngineError("figure_handoff_no_plotted_data", "This figure has no visible plotted data layers.")
    records: list[dict[str, Any]] = []
    for identifier, dataset in data.ir["datasets"].items():
        if identifier not in layer_bindings:
            continue
        layers = layer_bindings[identifier]
        used = {key for item in layers for key in item["mappings"].values()}
        columns = {key: value for key, value in dataset["columns"].items() if key in used}
        target = directory / f"{len(records) + 1:03d}.csv"
        provenance = dataset["provenance"]
        sources = [{**{key: source[key] for key in ("source_id", "sha256", "table_selection", "column_indices")},
                    "row_count": len(source["rows"])} for source in provenance["sources"]]
        transforms = [{key: step[key] for key in ("node_id", "executor_hash", "input_hashes", "output_hash")}
                      for step in provenance["transforms"]]
        records.append({"format": "plotted_csv", "path": target.name, "dataset_id": identifier,
                        **_write_dataset_csv(target, columns), "layers": layers,
                        "provenance": {"sources": sources, "transforms": transforms}})
    return records
