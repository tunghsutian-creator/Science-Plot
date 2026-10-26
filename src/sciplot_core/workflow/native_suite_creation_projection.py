"""Project known host paths and verify complete private creation inventories."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

def _path(value: str, pairs: tuple[tuple[Path, Path], ...]) -> str:
    for before, after in pairs:
        if value == str(before) or value.startswith(str(before) + "/"):
            return str(after) + value[len(str(before)):]
    return value


def _remap(value: Any, pairs: tuple[tuple[Path, Path], ...]) -> Any:
    """Translate only declared native receipt/host path fields, never science."""
    fields = {"workspace", "delivery", "document", "export_dir", "native_audit_path", "spec_path",
              "path", "manual_edit", "plot", "out"}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in fields and isinstance(item, str):
                result[key] = _path(item, pairs)
            elif key == "exports" and isinstance(item, list) and all(isinstance(entry, str) for entry in item):
                result[key] = [_path(entry, pairs) for entry in item]
            else:
                result[key] = _remap(item, pairs)
        return result
    if isinstance(value, list):
        return [_remap(item, pairs) for item in value]
    return value


def creation_inventory(workspace: Path, delivery: Path, native: dict[str, Any],
                       delivery_files: dict[str, str], workspace_inputs: dict[str, Any], *,
                       suite_sha256: str | None = None) -> dict[str, str]:
    """Bind private creation bytes to known inputs and native export receipts."""
    from sciplot_core.workflow.rheology_tts_saved_state import _figure_folder
    expected = {str(delivery / name): digest for name, digest in delivery_files.items()}
    for name, value in workspace_inputs.items():
        data = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        expected[str(workspace / name)] = sha256(data).hexdigest()
    if suite_sha256:
        expected[str(workspace / "suite.json")] = suite_sha256
    else:
        expected[str(workspace / "suite.json")] = delivery_files["data/delivery_manifest.json"]
    for receipt in native["figures"]:
        for field, digest in (("document", "document_sha256"), ("spec_path", "spec_sha256")):
            expected[receipt[field]] = receipt[digest]
        audit = Path(receipt["native_audit_path"])
        data = audit.read_bytes()
        if json.loads(data) != receipt["native_audit"]:
            raise ValueError("Native creation audit bytes differ from its scientific receipt.")
        expected[str(audit)] = sha256(data).hexdigest()
        visible_native = str(delivery / "editable" / (receipt["id"] + ".vsz"))
        if expected[visible_native] != receipt["document_sha256"]:
            raise ValueError("Visible native bytes differ from the exact audited candidate.")
        for exported in receipt["exports"]:
            expected[exported["path"]] = exported["sha256"]
            visible = str(_figure_folder(delivery, receipt["id"]) / Path(exported["path"]).name)
            if expected[visible] != exported["sha256"]:
                raise ValueError("Visible export bytes differ from the exact audited export.")
    return expected
