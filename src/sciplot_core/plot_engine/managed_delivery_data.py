"""Lossless serialization of already sealed PlotIR tables; no scientific math."""

import csv
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_ir import validate_ir
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current


def project_data(ir_path: Path, root: Path, stem: str, *, expected: dict[str, str]) -> dict[str, Any]:
    snapshot = stable_file_snapshot(ir_path, label="Managed delivery exact PlotIR")
    ir = validate_ir(json.loads(snapshot["bytes"]))
    if any(ir[key] != value for key, value in expected.items()):
        raise EngineError("managed_delivery_ir_changed", "The sealed dataset snapshot differs from its selected PlotIR/scientific/presentation binding.")
    destination = root / "data" / "plotted" / stem
    destination.mkdir(parents=True)
    exact = destination / "plot-ir.json"
    exact.write_bytes(snapshot["bytes"])
    records = []
    for index, (identifier, dataset) in enumerate(ir["datasets"].items(), 1):
        columns = dataset["columns"]
        counts = {len(column["values"]) for column in columns.values()}
        if len(counts) != 1:
            raise EngineError("managed_delivery_ragged_columns", "A sealed dataset has inconsistent column lengths; CSV projection cannot pad or truncate it.")
        target = destination / f"{index:03d}.csv"
        with target.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow([column["label"] for column in columns.values()])
            # csv uses Python's round-trip float representation. Each dataset
            # retains its own exact length; None alone is an empty CSV cell.
            writer.writerows(zip(*(column["values"] for column in columns.values()), strict=True))
        pointer = "/datasets/" + identifier.replace("~", "~0").replace("/", "~1")
        records.append({"dataset_id": identifier, "path": str(target.relative_to(root)),
                        "sha256": file_sha256(target), "row_count": next(iter(counts)),
                        "column_ids": list(columns), "columns": [{"id": key, "label": value["label"], "unit": value["unit"]}
                                                                  for key, value in columns.items()],
                        "header_rows": 1, "null_encoding": "empty_cell", "provenance_pointer": pointer + "/provenance"})
    _assert_snapshot_current(snapshot, label="Managed delivery exact PlotIR")
    return {"ir": {"path": str(exact.relative_to(root)), "sha256": snapshot["sha256"],
                   "ir_hash": ir["ir_hash"], "schema_version": ir["schema_version"]},
            "datasets": records,
            "role_evidence": "Read the exact IR series/layers and dataset provenance to distinguish source, derived and reference data. CSV serialization performs no transforms or reference-value generation."}
