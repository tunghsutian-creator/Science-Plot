"""Import actual saved presentation while retaining the complete legacy baseline."""

from collections import Counter
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_backends.veusz_identity import changed_error, require_current
from sciplot_core.plot_backends.veusz_semantic_import import axis_properties, legend_properties, managed_annotation
from sciplot_core.source_coverage.managed_documents import _source_records
from sciplot_core.studio_core.annotation_operations import require_edit_source_current
from sciplot_core.studio_core.document_edit_state import audit_edited_document
from sciplot_core.studio_core.project_query import inspect_project


def _object(kind: str, label: str) -> dict[str, Any]:
    return {"kind": kind, "label": label, "properties": {}, "capabilities": {}}


def _identifier(kind: str, label: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", label):
        return kind + ":" + label
    readable = re.sub(r"[^A-Za-z0-9_.:-]", "_", label)[:70] or "unnamed"
    return kind + ":" + readable + ":" + hashlib.sha256(label.encode()).hexdigest()[:12]


def _setting(obj: dict[str, Any], target: dict[str, Any], fields: dict[str, Any],
             prop: str, setting: str, value_type: str, *, risk: str = "presentation") -> None:
    field = fields.get(setting)
    if field is None:
        return
    obj["properties"][prop] = field["current_value"]
    obj["capabilities"][prop] = {"type": value_type, "risk": risk}
    target["properties"][prop] = {"kind": "setting", "setting_path": setting,
                                  "current_value": field["current_value"]}


def _presentation(selected: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    widgets = selected["objects"]
    objects: dict[str, Any] = {}
    targets: dict[str, Any] = {}
    labels = Counter(str(item.get("label", "")) for item in spec.get("series", []))
    seen: Counter[str] = Counter()
    managed = {item["id"]: item for item in selected.get("annotations", [])}
    for series in spec.get("series", []):
        path = f"/page1/graph1/{series['name']}"
        widget = widgets.get(path)
        if widget is None:
            raise DocumentError("backend_import_mismatch", "A declared series is missing from the saved document.")
        label = str(series.get("label", ""))
        seen[label] += 1
        identifier = _identifier("series", label) + (f":{seen[label]}" if labels[label] > 1 else "")
        while identifier in objects:
            identifier += ":duplicate"
        obj, target = _object("series", label), {"object_path": path, "properties": {}}
        fields = {field["setting_path"]: field for field in widget["editable_fields"]}
        _setting(obj, target, fields, "style.line.width", path + "/PlotLine/width", "physical_size")
        _setting(obj, target, fields, "style.line.color", path + "/PlotLine/color", "color")
        if obj["properties"]:
            objects[identifier], targets[identifier] = obj, target
    for path, widget in widgets.items():
        kind = widget["type"]
        if kind not in {"axis", "key", "label"}:
            continue
        fields = {field["setting_path"]: field for field in widget["editable_fields"]}
        if kind == "axis":
            identifier = _identifier("axis", widget["name"])
            obj, target = _object("axis", widget["name"]), {"object_path": path, "properties": {}}
            _setting(obj, target, fields, "font.size", path + "/Label/size", "physical_size")
            axis_properties(obj, target, widget, spec)
        elif kind == "key":
            identifier = _identifier("legend", widget["name"])
            obj, target = _object("legend", widget["name"]), {"object_path": path, "properties": {}}
            _setting(obj, target, fields, "font.size", path + "/Text/size", "physical_size")
            legend_properties(obj, target, widget, spec)
        else:
            annotation_id = widget["name"].removeprefix("sciplot_annotation_")
            record = managed.get(annotation_id)
            if record is not None:
                imported = managed_annotation(record, path)
                if imported is None:
                    continue
                obj, target = imported
                identifier = obj["kind"] + ":" + annotation_id
            else:
                identifier = _identifier("annotation", widget["name"])
                obj, target = _object("annotation", widget["name"]), {"object_path": path, "properties": {}}
                _setting(obj, target, fields, "font.size", path + "/Text/size", "physical_size")
        if obj["properties"]:
            if identifier in objects:
                raise DocumentError("backend_import_ambiguous", "Native objects need an unambiguous semantic identity.")
            objects[identifier], targets[identifier] = obj, target
    return objects, targets


def import_project(project: Path, figure_id: str | None, plot_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    query = inspect_project(project, figure_id=figure_id, native=True, include_annotations=True)
    require_edit_source_current(query)
    selected = query["selected_figure"]
    root = Path(query["project"])
    spec_path, document_path = Path(selected["spec"]), Path(selected["document"])
    spec_bytes = spec_path.read_bytes()
    if file_sha256(spec_path) != selected["spec_sha256"]:
        raise changed_error("The specification changed during import.", [str(spec_path)])
    spec = json.loads(spec_bytes)
    request = json.loads((root / "plot_request.json").read_text())
    files: dict[str, Any] = {str(path): digest for path, digest in _source_records(spec).items()}
    for sample in (request.get("study_model") or {}).get("samples", []):
        for replicate in sample.get("replicates", []):
            source = replicate.get("source_file") or {}
            if source.get("raw_path") and source.get("sha256"):
                files[source["raw_path"]] = source["sha256"]
    sources = [{"path": path, "sha256": digest, "kind": "recorded_file"}
               for path, digest in sorted(files.items())]
    files.update({str(document_path): selected["document_sha256"],
                  str(spec_path): selected["spec_sha256"],
                  str(root / "plot_request.json"): query["request_sha256"]})
    for figure in query.get("figures", []):
        for field in ("document", "spec"):
            files[figure[field]] = figure[field + "_sha256"]
    registry = root / "studio" / "figure_set.json"
    files[str(registry)] = file_sha256(registry) if registry.is_file() else None
    input_source = (query.get("source") or {}).get("input") or {}
    source_trees = {input_source["path"]: input_source["sha256"]} if input_source.get("path") else {}
    objects, targets = _presentation(selected, spec)
    audit = audit_edited_document(document_path, spec_path)
    binding: dict[str, Any] = {
        "kind": "sciplot_veusz_binding", "version": 1, "project": str(root),
        "figure_id": selected["figure_id"], "document": str(document_path), "spec": str(spec_path),
        "files": files, "source_trees": source_trees, "targets": targets,
        "source_status_at_import": query["source"], "native_audit_at_import": audit,
        "font_configuration": {
            "kind": "native_requested_font_families",
            "families": sorted({value for widget in selected["objects"].values()
                                for key, value in widget.get("settings", {}).items()
                                if key.endswith("/font") and isinstance(value, str) and value}),
            "resolved_font_files_evaluated": False,
        },
    }
    binding["fingerprint"] = {"files": deepcopy(files), "source_trees": deepcopy(source_trees)}
    require_current(binding)
    document = {
        "kind": "sciplot_document", "schema_version": 1, "plot_id": plot_id or uuid4().hex,
        "revision": 0,
        "scientific": {"data_sources": sources,
                       "transforms": deepcopy((request.get("transform_ledger") or {}).get("steps", [])),
                       "mappings": {"figure_id": selected["figure_id"]},
                       "guards": {"source_status_at_import": query["source"]["status"],
                                  "native_data_audit_required": True},
                       "provenance": {"imported_specification": spec,
                                      "imported_request": request}},
        "presentation": {"objects": objects, "layout": {}, "theme": {},
                         "export_configuration": {"formats": ["pdf", "tiff_300"]}},
        "coverage": {"mode": "legacy_shadow", "limitations": [
            "Only advertised semantic properties are editable; remaining native content is preserved opaquely.",
            "Compilation applies a delta to the exact imported native baseline, not a lossless full-document regeneration.",
            "Scientific provenance retains the initial specification and request; their presentation defaults are historical.",
            "Source-change detection covers recorded source paths; legacy imports cannot infer an unrecorded original external file.",
            "Axis limits preserve ticks, direction and units and reject clipping; only ordinary linear axes without existing clipping are advertised.",
            "Legend null position preserves the imported native preset; manual positions use relative graph coordinates.",
            "Managed ordinary text annotations preserve coordinate mode, units and arrow anchors; peak-bound and opaque labels are not inferred.",
        ]},
        "backend": {"name": "veusz", "binding_version": 1},
    }
    return seal_document(document), binding
