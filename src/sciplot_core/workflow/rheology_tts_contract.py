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


def prepared_plan_provenance_schema() -> dict:
    """The existing prepared input boundary, shared by discovery and validation."""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "required": ["source_binding", "transform_ledger"],
        "properties": {
            "source_binding": {"type": "object", "required": ["sources"], "properties": {
                "sources": {"type": "array", "minItems": 1, "items": {
                    "type": "object", "additionalProperties": False, "required": ["path", "sha256"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "pattern": "^/",
                                 "description": "Absolute original local source path; symlinks are rejected."},
                        "sha256": {"type": "string", "minLength": 1,
                                   "description": "Exact lowercase SHA256 of that file's unchanged bytes; checked before drawing."}}}}}},
            # Historical plans may disclose transformations as text or a list.
            # Advertise their actual nonempty boundary without imposing a new ledger vocabulary.
            "transform_ledger": {"not": {"enum": [None, False, 0, "", [], {}]},
                "description": "Nonempty caller disclosure of transformations, or an explicit declaration of none; retained verbatim."},
        }}


def prepared_plan_contract() -> dict:
    return {"required": ["version", "source_binding", "transform_ledger", "figures"],
        "provenance_schema": prepared_plan_provenance_schema(),
        "validation": "The provenance schema is enforced before source checks or native creation; shared presentation and coordinate validators then check the figures. This is not a complete figure-style schema.",
        "source_binding": "sources is a nonempty ordered array. Each record contains exactly path and sha256. Bind all inputs actually used, including processed tables and processing evidence; the program adds its prepared_plan binding itself.",
        "output": "Omit out to create <first-source-stem>_Prepared_SciPlot beside the first bound source. An explicit out must be a dedicated sibling folder, or a new revision inside an existing source-bound sibling suite. Never relocate source bindings just to bypass this rule.",
        "transform_ledger": "A structured object is recommended: describe operations or explicitly none, source fields/rows, selections and exclusions, quantities, units, scientific decisions and limitations. Existing nonempty text/list declarations remain accepted; there is no mandatory new ledger vocabulary.",
        "units": {
            "declaration": "Put final axis units in panel x_label/y_label and disclose source/output units and any conversions in transform_ledger, keyed by figure/series when units differ. Units are not separate series fields.",
            "quantity_identity": "Complex-viscosity magnitude |eta*|, real viscosity and imaginary viscosity are distinct quantities. A component cannot be relabelled as magnitude; disclose any magnitude derivation and its unit evidence before supplying coordinates.",
            "validation_scope": "The plotting entry preserves declared units, labels, ledger and coordinates; it does not infer units, convert values, validate scientific calculations or certify a TTS model.",
        },
        "example_scope": "Synthetic final coordinates only. Replace the absolute source path, its SHA256 and all scientific declarations with actual caller evidence; the example performs no TTS calculation.",
        "example": {"version": 1, "figure_layout": "prepared",
            "source_binding": {"sources": [{"path": "/absolute/caller-values.csv", "sha256": "0" * 64}]},
            "transform_ledger": {"operation": "Identity; final coordinates supplied by caller, no local processing.",
                "quantity": "complex_viscosity_magnitude", "units": {"x": "rad/s", "y": "Pa s"},
                "source_fields": {"x": "omega", "y": "eta_magnitude"}},
            "figures": [{"id": "Caller_viscosity", "panels": [{"id": "a",
                "x_label": "Angular frequency (rad/s)", "y_label": "|eta*| (Pa s)",
                "series": [{"role": "measured_curve", "label": "Caller-supplied temperature",
                            "x": [10, 1], "y": [12.5, 80.25]}]}]}]},
    }


def validate_prepared_plan_provenance(plan: object) -> None:
    errors = sorted(Draft202012Validator(prepared_plan_provenance_schema()).iter_errors(plan),
                    key=lambda error: str(list(error.absolute_path)))
    if errors:
        first = errors[0]
        parts = list(first.absolute_path)
        # A missing top-level disclosure needs its field name, not just "prepared_plan".
        if first.validator == "required" and not parts:
            parts = [field for field in first.validator_value if field not in plan][:1]
        location = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts).lstrip(".") or "prepared_plan"
        raise ValueError(f"Invalid prepared plan at {location}: {first.message}; read rheology capabilities --json (prepared_plan).")


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
                "prepared_plan": prepared_plan_contract(),
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
