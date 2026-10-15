"""One deterministic compact intent port shared by CLI and MCP."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def _intent_operations_schema() -> dict[str, Any]:
    from .model import operation_capabilities

    schema: dict[str, Any] = deepcopy(operation_capabilities()["operations"])
    schema["maxItems"] = 128
    for branch in schema["items"]["oneOf"]:
        action = branch["properties"]["op"]["const"]
        if action == "add_panel":
            panel = branch["properties"]["panel"]
            panel["required"] = [key for key in panel["required"] if key not in {"row_span", "column_span", "label", "crop"}]
            source = panel["properties"]["source"]
        elif action == "replace_panel":
            source = branch["properties"]["source"]
        else:
            continue
        for reference in source["oneOf"]:
            reference["required"] = [key for key in reference["required"] if key != "binding"]
    return schema


def composition_request_schema() -> dict[str, Any]:
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    positive = {"type": "number", "exclusiveMinimum": 0}
    definitions: dict[str, tuple[dict[str, Any], list[str]]] = {
        "new": ({"rows": {"type": "integer", "minimum": 1}, "columns": {"type": "integer", "minimum": 1},
                 "width_mm": positive, "height_mm": positive}, []),
        "inspect": ({"check_sources": {"type": "boolean"}}, []),
        "apply": ({"expected_revision": {"type": "integer", "minimum": 0},
                   "operations": _intent_operations_schema()}, ["expected_revision", "operations"]),
        "export": ({"out": path, "dpi": {"type": "integer", "minimum": 72, "maximum": 1200}}, ["out"]),
    }
    return {"oneOf": [{"type": "object", "additionalProperties": False,
                       "properties": {"action": {"const": action}, "layout": path, **properties},
                       "required": ["action", "layout", *required]}
                      for action, (properties, required) in definitions.items()]}


def composition_capabilities() -> dict[str, Any]:
    return {"kind": "sciplot_composition_capabilities", "version": 1, "status": "ready",
            "request_schema": composition_request_schema(),
            "execution": "local deterministic layout operations; no model invocation",
            "authority": {"legacy": "exact saved VSZ", "managed": "semantic document, sources and transforms",
                          "assembly": "panel placement, image crop and frozen source references only"},
            "source_references": [
                {"kind": "project", "project": "/project", "figure_id": "selected"},
                {"kind": "managed", "project": "/project/.sciplot_documents/selected", "plot_id": "selected"},
                {"kind": "image", "path": "/original/image.tiff"}],
            "source_binding": "add/replace captures current authority locally; export rejects drift",
            "scientific_resizing": "supported native reflow at target millimetres; never scaled PDF text"}


def _summary(document: dict[str, Any], path: Path, *, sources_checked: bool = False) -> dict[str, Any]:
    from .model import resolve_document

    return {"kind": "sciplot_panel_assembly", "version": 1, "status": "ready",
            "layout_path": str(path), "revision": document["revision"], "layout": document["layout"],
            "panels": [{key: panel[key] for key in ("id", "row", "column", "row_span", "column_span", "label", "crop")}
                       | {"source_kind": panel["source"]["kind"]} for panel in document["panels"]],
            "resolved_layout": resolve_document(document),
            "source_validation": "current" if sources_checked else "deferred_until_export",
            "next_step": "compose open LAYOUT, or apply a layout intent at the returned revision"}


def _bind_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bound = deepcopy(operations)
    for operation in bound:
        if operation.get("op") not in {"add_panel", "replace_panel"}:
            continue
        holder = operation.get("panel") if operation["op"] == "add_panel" else operation
        if not isinstance(holder, dict) or not isinstance(holder.get("source"), dict):
            continue  # The model's complete batch validation owns the error.
        from .sources import assert_source_current, capture_source

        source = holder["source"]
        if "binding" in source:
            assert_source_current(source)
        else:
            holder["source"] = capture_source(source)
        if operation["op"] == "add_panel":
            for key, value in {"row_span": 1, "column_span": 1, "label": None, "crop": None}.items():
                holder.setdefault(key, value)
    return bound


def compose(request: dict[str, Any]) -> dict[str, Any]:
    from .errors import AssemblyError
    from .model import apply_operations, load_document, new_document, save_document

    try:
        json.dumps(request, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise AssemblyError("assembly_request_invalid", "Layout requests must contain finite JSON values.") from exc
    if not Draft202012Validator(composition_request_schema()).is_valid(request):
        raise AssemblyError("assembly_request_invalid", "Use one closed compose action and its advertised fields.")
    path = Path(request["layout"]).expanduser().absolute()
    action = request["action"]
    if action == "new":
        document = new_document(**{key: request[key] for key in ("rows", "columns", "width_mm", "height_mm") if key in request})
        save_document(document, path)
        return _summary(document, path)
    document = load_document(path)
    if action == "apply":
        if request["expected_revision"] != document["revision"]:
            raise AssemblyError("assembly_revision_conflict", "The layout changed. Inspect its current revision before applying.")
        updated = apply_operations(document, _bind_operations(request["operations"]))
        save_document(updated, path, expected_revision=document["revision"])
        return _summary(updated, path)
    if action == "export":
        from .export import export_document

        return export_document(document, Path(request["out"]).expanduser().resolve(), dpi=request.get("dpi", 300))
    checked = request.get("check_sources", False)
    if checked:
        from .sources import assert_source_current

        for panel in document["panels"]:
            assert_source_current(panel["source"])
    return _summary(document, path, sources_checked=checked)
