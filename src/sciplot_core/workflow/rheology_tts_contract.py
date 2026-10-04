"""Discoverable, executable AI boundary for the explicit rheology suite."""

from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.semantic_sources.rheology_tts_corrected import CORRECTED_OPTIONS, LEGACY_OPTIONS


def creation_request_schema() -> dict:
    """The same closed schema is advertised and checked before any source I/O."""
    text = {"type": "string", "minLength": 1}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["version", "frequency_source", "reference_temperature_C", "frequency_temperature_C", "samples"],
        "properties": {
            "version": {"const": 1}, "frequency_source": text,
            "reference_temperature_C": {"type": "number", "exclusiveMinimum": -273.15},
            "frequency_temperature_C": {"type": "number", "exclusiveMinimum": -273.15},
            "figure_layout": {"enum": ["legacy", "separate_polymer_modulus"]},
            "out": text, "expected_contract_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "analysis_options": {"type": "object", "enum": [CORRECTED_OPTIONS, LEGACY_OPTIONS]},
            "samples": {"type": "array", "minItems": 1, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["sample_id", "polymer", "udc_wt_percent", "frequency_test"],
                "properties": {"sample_id": text, "polymer": {"enum": ["HDPE", "LDPE"]},
                    "udc_wt_percent": {"type": "number", "minimum": 0}, "frequency_test": text,
                    "tts_source": text, "tts_test": text},
                "dependentRequired": {"tts_source": ["tts_test"], "tts_test": ["tts_source"]},
            }},
        },
    }


def prepared_request_schema() -> dict:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["version", "prepared_plan"], "properties": {
            "version": {"const": 1}, "prepared_plan": {"type": "string", "minLength": 1},
            "out": {"type": "string", "minLength": 1},
            "expected_contract_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}


def presentation_update_contract() -> dict:
    return {"optional_argument": "--presentation-plan PATH",
        "input": "A complete caller-prepared figure plan with final display labels and legend positions.",
        "allowed_changes": ["series.label", "panel.legend"],
        "legend_positions": ["upper_left", "upper_right", "lower_left", "lower_right",
                             "top_left", "top_right", "bottom_left", "bottom_right"],
        "legend_visibility": "Reposition an existing legend only; widget visibility is preserved.",
        "program_owned": "Shared template governance; stable native series IDs and source coordinates.",
        "invariants": ["source_binding", "transform_ledger", "figure_and_panel_ids", "native_series_ids",
                       "coordinates_and_order", "axes_and_ticks", "layout", "titles", "notes", "reference_lines"],
        "temperature_labels": "The caller supplies final text. The program never rounds temperatures or derives labels from numerical values.",
        "binding": "The external plan path and SHA256 are frozen with baseline and candidate files, and checked before preview and apply."}


def rheology_capabilities() -> dict:
    from sciplot_core.rheology_tts_style import tts_presentation_capabilities

    contract = {"prepared_request_schema": prepared_request_schema(),
                "legacy_analysis_request_schema": creation_request_schema(),
                "presentation": tts_presentation_capabilities(),
                "presentation_update": presentation_update_contract()}
    return {"kind": "sciplot_rheology_capabilities", "version": 1, "status": "ready",
        "contract_sha256": canonical_json_sha256(contract), **deepcopy(contract),
        "model_configuration_required": False,
        "actions": {
            "plot_prepared": "rheology plot --request REQUEST.json --json",
            "resume_prepared": "rheology plot --request SAME_REQUEST.json --resume --json",
            "legacy_combined_analysis": "rheology tts --request REQUEST.json --json",
            "export": "rheology export WORKSPACE --json",
            "style_preview": "rheology style-preview WORKSPACE [--presentation-plan PLAN.json] --json",
            "style_apply": "rheology style-apply WORKSPACE --preview PREVIEW.json --json",
        },
        "responsibility": {
            "external_ai": "Own scientific processing, selections, fits, transformations, numerical coordinates, units and series roles; inspect native previews.",
            "program": "Validate prepared coordinates, resolve declared roles through shared templates, preserve values/order, audit saved native styles and export. The plot entry never fits or derives scientific data.",
            "style_exceptions": "Creation has no arbitrary appearance fields. Explicit user native edits remain authoritative on exact re-export.",
        },
        "scope": "Prepared numeric figure plans; no data discovery, fitting, implicit point removal or scientific interpretation in the plotting entry. The legacy combined analysis command retains its fixed UDC sample scope.",
        "style_update": "Preview binds sources, current suite, optional caller-prepared display-label/legend plan, native files and candidate exports. Apply publishes only that current preview with retained backups; no rounding or numerical processing occurs.",
    }


def validate_creation_request(request: object, *, prepared: bool = False) -> None:
    schema = prepared_request_schema() if prepared else creation_request_schema()
    errors = sorted(Draft202012Validator(schema).iter_errors(request),
                    key=lambda error: str(list(error.absolute_path)))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "request"
        raise ValueError(f"Invalid rheology request at {location}: {first.message}; read rheology capabilities --json.")
    expected = request.get("expected_contract_sha256")
    if expected and expected != rheology_capabilities()["contract_sha256"]:
        raise ValueError("Stale rheology capabilities; read the current contract before creating figures.")
