"""Build and audit declared annotations through native Veusz operations."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_core.annotation_contracts import PREFIX
from sciplot_core.studio_core.annotation_geometry import annotation_widgets
from sciplot_core.studio_core.annotation_batch import compile_annotation_operations
from sciplot_core.studio_core.document_edit_policy import validate_edit_science_policy
from sciplot_core.veusz_worker.document_edit import loaded_native_document, prepare_setting_batch, _preview
from sciplot_core.veusz_worker.widget_bindings import _dataset_setting_bindings


def audit_native_annotations(document: Any, spec: dict[str, Any]) -> set[str]:
    expected = {item["path"]: item for item in annotation_widgets(spec)}
    actual: dict[str, Any] = {}
    def collect(path: str, node: Any) -> None:
        if str(getattr(node, "name", "")).startswith(PREFIX):
            actual[path] = node
    document.walkNodes(collect, nodetypes=("widget",))
    if set(actual) != set(expected):
        raise ValueError("Managed annotation widget inventory differs from its declared contract.")
    for path, record in expected.items():
        widget = actual[path]
        bindings = _dataset_setting_bindings(widget.settings)
        if widget.typename != record["type"] or set(bindings) - set(record["settings"]):
            raise ValueError("Managed annotations cannot change widget types or bind arbitrary datasets.")
        if record["type"] == "label" and record["settings"]["label"] in document.data:
            raise ValueError("Literal annotation text must not name a native dataset.")
        for suffix, value in record["settings"].items():
            setting = document.resolveSettingPath(None, f"{path}/{suffix}")
            if json_safe(setting.get()) != json_safe(setting.normalize(value)):
                raise ValueError(f"Managed annotation setting differs from its declared contract: {path}/{suffix}")
    return set(expected)


def edit_native_annotations(
    document_path: Path, spec_path: Path, operations: Any, *, figure_id: str,
    output_document: Path, output_spec: Path, preview_png: Path,
) -> dict[str, Any]:
    document_path, spec_path = document_path.resolve(), spec_path.resolve()
    outputs = [path.resolve() for path in (output_document, output_spec, preview_png)]
    if len(set(outputs)) != 3 or any(path.exists() or path in {document_path, spec_path} for path in outputs):
        raise ValueError("Use three new, distinct candidate outputs outside the input files.")
    original = file_sha256(document_path)
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    styles, new_spec, actual = compile_annotation_operations(
        spec, operations, document_sha256=original, figure_id=figure_id)
    validate_edit_science_policy(styles, spec_path)
    with loaded_native_document(document_path) as loaded:
        audit_native_annotations(loaded, spec)
        native, style_actual = prepare_setting_batch(loaded, styles) if styles else ([], [])
        ops = import_module("veusz.document.operations")
        for widget in annotation_widgets(spec):
            native.append(ops.OperationWidgetDelete(loaded.resolveWidgetPath(None, widget["path"])))
        for widget in annotation_widgets(new_spec):
            parent = loaded.resolveWidgetPath(None, widget["parent"])
            if parent.typename != "graph":
                raise ValueError("Annotation parent must be the inspected graph.")
            for axis in ("x", "y"):
                for bound in ("min", "max"):
                    if loaded.resolveSettingPath(None, f"{parent.path}/{axis}/{bound}").get() != spec["axes"][axis][bound]:
                        raise ValueError("Annotation placement requires the prepared axis bounds; current native bounds differ.")
            native.append(ops.OperationWidgetAdd(parent, widget["type"], autoadd=False,
                                                name=widget["name"], index=0))
            native.extend(ops.OperationSettingSet(f"{widget['path']}/{suffix}", value)
                          for suffix, value in widget["settings"].items())
        loaded.applyOperation(ops.OperationMultiple(native, descr="SciPlot reviewed annotations"))
        audit_native_annotations(loaded, new_spec)
        try:
            output_document.parent.mkdir(parents=True, exist_ok=True)
            import_module("veusz.document").CommandInterface(loaded).Save(str(output_document))
            atomic_write_json(output_spec, new_spec)
            preview = _preview(loaded, preview_png)
            if file_sha256(document_path) != original or spec_path.read_bytes() != spec_bytes:
                raise ValueError("The saved figure changed during annotation preview.")
        except BaseException:
            for path in outputs:
                path.unlink(missing_ok=True)
            raise
    return {"kind": "sciplot_document_edit", "version": 2, "status": "passed",
            "document": {"path": str(document_path), "sha256": original},
            "candidate": {"path": str(output_document), "sha256": file_sha256(output_document)},
            "candidate_spec": {"path": str(output_spec), "sha256": file_sha256(output_spec)},
            "changes": [*style_actual, *actual], "preview": preview}
