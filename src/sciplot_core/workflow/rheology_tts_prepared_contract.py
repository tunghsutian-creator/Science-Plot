"""Pure prepared-plan provenance and disclosure contract shared by live owners."""

from __future__ import annotations

from jsonschema import Draft202012Validator


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
