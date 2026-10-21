"""Closed original-table categorical binding; no experimental or task authority."""

from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.mapping_contract.table_metadata import metadata_confirmations_schema
from sciplot_core.mapping_contract.table_selection import table_selection_schema


def categorical_binding_schema(*, complete: bool = False) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "\\S"}
    names = {"type": "array", "minItems": 1, "maxItems": 256,
             "uniqueItems": True, "items": text}
    value = {"type": "object", "additionalProperties": False,
             "properties": {"column_index": {"type": "integer", "minimum": 0},
                            "label": text}, "required": ["column_index"]}
    style: dict[str, Any] = {"type": "object", "additionalProperties": False,
             "properties": {"label": text, "series_id": text, "color": {"type": "string", "pattern": "^#[a-fA-F0-9]{6}$"},
                            "marker": {"enum": ["circle", "square", "diamond", "triangle", "none"]},
                            "marker_fill_mode": {"enum": ["open", "filled"]}},
             "required": ["label"]}
    summary_style = {"type": "object", "additionalProperties": False,
                     "properties": {key: style["properties"][key] for key in ("label", "series_id", "color")},
                     "required": ["label", "color"]}
    properties: dict[str, Any] = {
        "source_identity_version": {"type": "integer", "const": 1},
        "source_namespace": {"type": "string", "minLength": 1},
        "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "mode": {"enum": ["given_values", "mean_sample_sd", "mean_sample_sd_n"],
                 "description": "given_values draws each provided value without errors; mean_sample_sd uses the existing arithmetic mean and sample SD (ddof=1)."},
        "table_selection": table_selection_schema(),
        "metadata_confirmations": metadata_confirmations_schema(),
        "sample_column": {"type": "integer", "minimum": 0},
        "condition_column": {"type": ["integer", "null"], "minimum": 0},
        "value_columns": {"type": "array", "minItems": 1, "maxItems": 32, "items": value},
        "include_categories": {**names, "description": "Explicit original sample-ID subset; omission includes every sample in the selected rows."},
        "category_order": {**names, "description": "Exact order of all included original sample IDs; never implicitly excludes a category."},
        "condition_order": names,
        "category_aliases": {"type": "object", "maxProperties": 256,
                             "additionalProperties": text,
                             "description": "Display labels keyed by original sample ID; source identities remain unchanged."},
        "series_styles": {"type": "array", "maxItems": 64, "items": style,
                          "description": "Given-value point-lines accept color/marker/fill. Repeated-measurement bars accept only explicit color, targeting an existing series or condition label."},
        "yscale": {"enum": ["linear", "log"],
                   "description": "Given-value point-lines support linear or log yscale; repeated-measurement summary bars require linear yscale and a visible y=0 baseline."},
        "legend_position": {"enum": ["auto", "upper_left", "upper_right", "lower_left", "lower_right"],
                            "description": "Explicit corners apply only to given_values point-lines with a native key; summaries retain their existing fixed categorical legend."},
        "legend_columns": {"type": "integer", "minimum": 1, "maximum": 12,
                           "description": "Given-value point-line native key only; repeated-measurement bar legends do not have key columns."},
    }
    required = (["source_sha256", "mode", "table_selection", "sample_column", "value_columns"]
                if complete else [])
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": required,
            "allOf": [{"if": {"properties": {"mode": {"enum": ["mean_sample_sd", "mean_sample_sd_n"]}},
                               "required": ["mode"]},
                       "then": {"not": {"required": ["legend_columns"]},
                                "properties": {"yscale": {"const": "linear"},
                                               "legend_position": {"const": "auto"},
                                               "series_styles": {"items": summary_style}}}}]}



def validate_categorical_binding(value: Any, *, complete: bool = False) -> None:
    if (isinstance(value, dict) and value.get("mode") in ("mean_sample_sd", "mean_sample_sd_n")
            and value.get("yscale", "linear") != "linear"):
        raise ValueError("Repeated-measurement summary bars require linear yscale and a visible y=0 baseline. Log yscale requires given_values point-lines.")
    if (isinstance(value, dict) and value.get("mode") in ("mean_sample_sd", "mean_sample_sd_n")
            and isinstance(value.get("series_styles"), list)
            and any(isinstance(style, dict) and {"marker", "marker_fill_mode"}.intersection(style)
                    for style in value["series_styles"])):
        raise ValueError("Repeated-measurement summary bars support series_styles color only. Marker and marker_fill_mode require given_values point-lines; summary bars have no visible raw-point markers.")
    if (isinstance(value, dict) and value.get("mode") in ("mean_sample_sd", "mean_sample_sd_n")
            and ("legend_columns" in value or value.get("legend_position", "auto") != "auto")):
        raise ValueError("Explicit legend columns and corner placement require given_values point-lines with a native key. Repeated-measurement bars retain their existing fixed categorical legend.")
    errors = list(Draft202012Validator(categorical_binding_schema(complete=complete)).iter_errors(value))
    if errors:
        raise ValueError(f"Invalid categorical binding at {list(errors[0].absolute_path)}: {errors[0].message}")
    indices = [value[key] for key in ("sample_column", "condition_column") if value.get(key) is not None]
    indices.extend(item["column_index"] for item in value.get("value_columns", []))
    if any(type(index) is not int for index in indices):
        raise ValueError("Categorical column coordinates must be original integer indices, without boolean or decimal coercion.")


def validate_categorical_context(request: dict[str, Any]) -> None:
    if "categorical_binding" not in request:
        return
    validate_categorical_binding(request["categorical_binding"], complete=True)
    if request.get("rule_id") or any(request.get(key) for key in (
            "data_mapping", "data_mapping_execution", "data_mapping_proposal_id", "scientific_transform", "data_transforms")):
        raise ValueError("Original categorical bindings require an ordinary request without a registered experiment or scientific data transform.")
