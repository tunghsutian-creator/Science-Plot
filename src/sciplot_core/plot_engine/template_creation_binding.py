"""Bind a template to explicit original cells through the existing mapping owner."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.table_choice import select_table, table_choice_snapshot
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import instantiate_template
from sciplot_core.plot_document.errors import fail
from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.task_error_feedback import short_error_message


@with_table_reads
def prepare(request: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    template, binding = request["template_definition"], request["data_binding"]
    desired = instantiate_template(template, binding, plot_id="template-preparation", theme=request.get("theme"))
    for key in ("layout", "export_configuration", "theme"):
        if template["presentation"][key]:
            fail("template_unsupported_presentation", "This native template creator requires layout and export defaults, with an explicit separate theme.",
                 f"/template_definition/presentation/{key}", "native_template_scope")
    if binding["transforms"]:
        fail("template_transform_executor_required", "Template creation cannot invent or execute undeclared scientific transforms.",
             "/data_binding/transforms", "explicit_transform_executor")
    if binding["guards"]:
        fail("template_guard_executor_required", "Custom scientific guards require a named executor; source bytes, units and native numerical fidelity are always checked.",
             "/data_binding/guards", "named_guard_executor")
    sources = binding["data_sources"]
    if len(sources) != 1:
        fail("template_source_scope", "This native template creator requires exactly one original table source.",
             "/data_binding/data_sources", "one_original_table")
    source = sources[0]
    path = Path(source["path"])
    if not path.is_absolute() or not path.is_file() or file_sha256(path) != source["sha256"]:
        fail("template_source_changed", "Use the exact current hash and absolute path of the original source file.",
             "/data_binding/data_sources/0", "current_original_file")
    if "table_selection" not in source:
        fail("template_table_selection_required", "Supply original worksheet, metadata rows and explicit data row bounds.",
             "/data_binding/data_sources/0/table_selection", "explicit_original_region")
    try:
        snapshot = table_choice_snapshot(path, request["rule_id"])
    except ValueError as exc:
        fail("template_rule_unsupported", "The native mapping owner rejected the selected scientific rule.",
             "/rule_id", "supported_rule", detail=short_error_message(str(exc)))
    if snapshot is None:
        fail("template_source_scope", "The selected rule/source does not support original-table XY binding.",
             "/rule_id", "table_mapping_supported")
    try:
        selected = select_table(snapshot, source["table_selection"], source.get("metadata_confirmations"))
    except ValueError as exc:
        fail("template_table_rejected", "The original table region or metadata could not be bound.",
             "/data_binding/data_sources/0/table_selection", "original_table_selection", detail=short_error_message(str(exc)))
    columns = {item["index"]: item for item in selected["columns"]}
    pairs = []
    samples: set[str] = set()
    for name in template["series_slots"]:
        slot = binding["slots"][name]
        if slot["sample"] in samples:
            fail("template_duplicate_sample", "Each bound series requires an exact unique original sample identity.",
                 f"/data_binding/slots/{name}/sample", "unique_sample")
        samples.add(slot["sample"])
        pair: dict[str, Any] = {}
        for axis in ("x", "y"):
            coordinate = slot[axis]
            pointer = f"/data_binding/slots/{name}/{axis}"
            if coordinate["source_id"] != source["source_id"] or "column_index" not in coordinate:
                fail("template_column_binding_required", "Supply this source's original zero-based column index and literal resolved header.",
                     pointer, "original_column_index")
            index = coordinate["column_index"]
            column = columns.get(index)
            if column is None:
                fail("template_column_missing", "The selected original table does not contain this column.",
                     pointer + "/column_index", "existing_column", allowed=list(columns))
            if column["header"] != coordinate["column"] or column["unit"] != slot[axis + "_unit"]:
                fail("template_metadata_conflict", "The binding's quantity and unit must match the selected original metadata exactly.",
                     pointer, "original_metadata", expected_column=column["header"], expected_unit=column["unit"])
            if (axis == "y" and column["sample"] != slot["sample"]) or (axis == "x" and column["sample"] not in {"", slot["sample"]}):
                fail("template_sample_conflict", "Bound sample identity differs from the original column metadata.",
                     pointer, "original_sample", observed=column["sample"], expected=slot["sample"])
            if not column[axis + "_eligible"]:
                fail("template_column_rejected", "The selected original column cannot be used without changing or inventing data.",
                     pointer, "finite_source_column", reasons=column[axis + "_rejection_reasons"])
            pair[axis + "_column"] = index
        pairs.append(pair)
    if not pairs:
        fail("template_empty_binding", "Native template creation requires at least one explicitly bound series.",
             "/data_binding/slots", "nonempty_series")
    mapping = {"source_sha256": source["sha256"], "table_selection": deepcopy(source["table_selection"]),
               "column_mapping": {"pairs": pairs}}
    if "metadata_confirmations" in source:
        mapping["metadata_confirmations"] = deepcopy(source["metadata_confirmations"])
    task = {"version": 1, "action": "create", "source": str(path), "rule_id": request["rule_id"], "mapping": mapping}
    if "out" in request:
        task["out"] = request["out"]
    return path, task, desired


def presentation_changes(desired: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for identifier, obj in desired["presentation"]["objects"].items():
        target = actual["objects"].get(identifier)
        if target is None or target["kind"] != obj["kind"]:
            fail("template_native_object_unsupported", "The native figure does not advertise this template object.",
                 f"/template_definition/presentation/objects/{identifier}", "native_object")
        for prop, value in obj["properties"].items():
            if prop not in target["capabilities"]:
                fail("template_native_property_unsupported", "The native figure does not advertise this template property.",
                     f"/template_definition/presentation/objects/{identifier}/properties/{prop}", "native_capability")
            if type(value) is not type(target["properties"][prop]) or value != target["properties"][prop]:
                changes.append({"op": "set", "target": [identifier], "property": prop, "value": deepcopy(value)})
    return changes
