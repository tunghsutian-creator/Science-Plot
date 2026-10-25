"""Bind immutable prepared creation requests and private input files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.source_update_commit import reject_symlink_path

CHECKPOINT = "creation_checkpoint.json"

def _input_file(path: Path, value: dict[str, Any], *, create: bool = True) -> None:
    expected = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    reject_symlink_path(path)
    if path.exists():
        if path.read_bytes() != expected:
            raise ValueError(f"Prepared creation input evidence changed: {path}")
    elif create:
        atomic_write_json(path, value)


def _publication_files(identifiers: list[str]) -> set[str]:
    names = {"index.html", "README.txt", "Open_in_SciPlot.command", "Update_exports.command",
             "data/figure_plan.json", "data/delivery_manifest.json"}
    for identifier in identifiers:
        folder = "" if identifier.startswith("Figure_X") else ("SI/" if identifier.startswith("SI_") else "panels/")
        names.update({f"editable/{identifier}.vsz", f"editable/Open_{identifier}.command", f"data/{identifier}.csv"})
        names.update(f"{folder}{identifier}{suffix}" for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png"))
    return names


def _creation_binding(request: dict[str, Any], spec: dict[str, Any], compiled: dict[str, Any], delivery: Path,
                      workspace: Path, contract_sha256: str) -> dict[str, Any]:
    return {"request": {**request, "prepared_plan": spec["source_binding"]["prepared_plan"]["path"],
                            "out": str(delivery)},
        "delivery": str(delivery), "workspace": str(workspace),
        "prepared_input": {k: spec["source_binding"]["prepared_plan"][k] for k in ("path", "sha256")},
        "sources": spec["source_binding"]["sources"], "contract_sha256": contract_sha256,
        "compiled_sha256": canonical_json_sha256(compiled), "figure_ids": [f["id"] for f in compiled["figures"]]}

