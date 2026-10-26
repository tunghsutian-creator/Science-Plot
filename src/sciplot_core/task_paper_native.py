"""A secure native Save of a selected copy, preserving opaque Veusz state."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current, _write_private_snapshot
from sciplot_core.studio_core.persistence import atomic_save_veusz_document
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.veusz_numeric_persistence import ensure_veusz_numeric_precision
from sciplot_core.veusz_worker.document_edit import loaded_native_document
from sciplot_core.veusz_worker.numeric_evidence import _numeric_payload


def _state(document: Any) -> str:
    definitions = io.StringIO()
    document.evaluate.saveCustomDefinitions(definitions)
    datasets = {}
    for name, dataset in sorted(document.data.items()):
        saved = io.StringIO()
        dataset.saveToFile(saved, name)
        values = {key: _numeric_payload(getattr(dataset, key)) for key in ("data", "serr", "perr", "nerr")
                  if getattr(dataset, key, None) is not None and getattr(dataset, "datatype", "numeric") == "numeric"}
        if getattr(dataset, "datatype", "numeric") != "numeric":
            values["text"] = list(dataset.data)
        linked = getattr(dataset, "linked", None)
        parameters = ({key: value for key, value in vars(linked.params).items() if key != "filename"}
                      if linked is not None else None)
        datasets[name] = {"saved": saved.getvalue(), "values": values, "tags": sorted(dataset.tags),
                          "type": type(dataset).__name__, "dimensions": dataset.dimensions,
                          "linked_parameters": parameters}
    return canonical_json_sha256({"widgets": document.basewidget.getSaveText(),
                                 "definitions": definitions.getvalue(), "datasets": datasets,
                                 "compatlevel": document.compatlevel}, allow_nan=False)


def save_portable_copy(source: Path, target: Path, *, imports: Path) -> dict[str, Any]:
    source, target, imports = canonical_path(source), canonical_path(target), canonical_path(imports)
    original = stable_file_snapshot(source, label="paper selected VSZ")
    if target.exists() or imports.exists():
        raise ValueError("Portable native staging targets must be new.")
    target.parent.mkdir(parents=True, exist_ok=True)
    imports.mkdir(parents=True)
    imported = []
    with loaded_native_document(source) as document:
        ensure_veusz_numeric_precision()
        before = _state(document)
        linked_files = {id(dataset.linked): dataset.linked for dataset in document.data.values()
                        if getattr(dataset, "linked", None) is not None}
        for index, linked in enumerate(linked_files.values(), 1):
            path = canonical_path(Path(linked.params.filename))
            snapshot = stable_file_snapshot(path, label="paper linked native source")
            destination = imports / f"{index:03d}_{snapshot['sha256'][:16]}{path.suffix.lower()}"
            _write_private_snapshot(destination, snapshot["bytes"])
            linked.params.filename = str(destination)
            _assert_snapshot_current(snapshot, label="paper linked native source", expected_sha256=snapshot["sha256"])
            imported.append({"source": str(path), "sha256": snapshot["sha256"],
                             "relative_path": str(destination.relative_to(target.parent.parent))})
        saved = atomic_save_veusz_document(document, target)
        if saved["ready_for_export"] is not True:
            raise ValueError("Portable VSZ did not securely reopen.")
    with loaded_native_document(target) as reopened:
        after = _state(reopened)
        for dataset in reopened.data.values():
            linked = getattr(dataset, "linked", None)
            if linked is not None and not canonical_path(Path(linked.params.filename)).is_relative_to(imports):
                raise ValueError("Portable VSZ still imports outside its selected data directory.")
    _assert_snapshot_current(original, label="paper selected VSZ", expected_sha256=original["sha256"])
    if before != after:
        raise ValueError("Native Save changed the selected document's complete state.")
    return {"kind": "sciplot_paper_portable_native", "version": 1, "status": "passed",
            "original_sha256": original["sha256"], "portable_sha256": saved["sha256"],
            "native_state_sha256": before, "reopened_native_state_sha256": after, "imports": imported}


def inspect_linked_sources(source: Path) -> list[dict[str, Any]]:
    """Read actual native imports, including those absent from generated specs."""
    source = canonical_path(source)
    original = stable_file_snapshot(source, label="paper selected VSZ")
    records = {}
    with loaded_native_document(source) as document:
        for dataset in document.data.values():
            linked = getattr(dataset, "linked", None)
            if linked is not None:
                path = canonical_path(Path(linked.params.filename))
                snapshot = stable_file_snapshot(path, label="paper linked native source")
                _assert_snapshot_current(snapshot, label="paper linked native source", expected_sha256=snapshot["sha256"])
                records[str(path)] = {"path": str(path), "sha256": snapshot["sha256"]}
    _assert_snapshot_current(original, label="paper selected VSZ", expected_sha256=original["sha256"])
    return [records[key] for key in sorted(records)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    save = actions.add_parser("save")
    save.add_argument("source", type=Path)
    save.add_argument("target", type=Path)
    save.add_argument("--imports", type=Path, required=True)
    inspect = actions.add_parser("inspect")
    inspect.add_argument("source", type=Path)
    args = parser.parse_args()
    result = (save_portable_copy(args.source, args.target, imports=args.imports) if args.action == "save"
              else inspect_linked_sources(args.source))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
