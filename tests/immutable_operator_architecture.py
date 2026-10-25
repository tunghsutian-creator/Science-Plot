"""Finite retained-v1 copies, bound to immutable bytes rather than a folder skip."""

import ast
import hashlib
from pathlib import Path


PREFIX = "src/sciplot_core/plot_transforms/versions/v1/"
PINS = {
    "hashing.py": "df8925e9dbe054e13cfe6ff95133cf57a09c6214bdefcb0139053fec7e333658",
    "json_values.py": "576a66e558d148b4b23d3bf8ba704feadb63f30816164e8aeceaa7477362483f",
    "selection.py": "34c07aa09447eaddf9c9338c1d51c34f30c8b126e69d1a0ca406ecb366deaf31",
    "unit_conversion.py": "0c0df625c0fdc57068fbfb611cdc04220d3a8c14c9454ba64fadbdaae105a436",
    "unit_formatting.py": "8a46f3989c63cf71ce79e9fb3644308bec1f1305a9c5ee01cbd7dfae9532e06e",
    "wire.py": "5e1d32287a115d1c7e1b5e0b87ed0d5d59764e8c110f81cc1f4e5a3743235d33",
    "rheology_metrics.py": "67130272954dfcb1fa672e3cad8215b65782998bd862dc0943434bbd61639f9a",
    "rheology_units.py": "00122ba6a69a410f31deea21df6646f08e0f294331cc5436052b214b844049fd",
}


def permitted_pairs() -> set[frozenset[str]]:
    declarations = [
        ("foundation/json_hashing.py", "hashing.py", ["canonical_json_sha256"]),
        ("foundation/json_values.py", "json_values.py", ["json_safe"]),
        ("mapping_contract/table_selection.py", "selection.py", ["table_selection_schema"]),
        ("materials_rules/unit_conversion.py", "unit_conversion.py", ["convert_value"]),
        ("materials_rules/unit_formatting.py", "unit_formatting.py", [
            "_looks_like_unit_solidus_expression", "looks_like_unit_expression", "format_unit_label",
            "_split_unit_factor_exponent", "_format_unit_factor", "_format_existing_unit_product", "_is_known_unit_symbol"]),
        ("plot_document/validation.py", "wire.py", ["finite_json", "validate_wire"]),
        ("semantic_sources/rheology_frequency_metrics.py", "rheology_metrics.py", [
            "_viscosity_from_modulus", "validate_complex_viscosity_units", "derive_complex_viscosity"]),
        ("semantic_sources/rheology_units.py", "rheology_units.py", ["_unit_conversion"]),
    ]
    return {frozenset(("src/sciplot_core/" + current + ":" + name, PREFIX + retained + ":" + name))
            for current, retained, names in declarations for name in names}


def pinned_duplicate_locations(root: Path) -> set[frozenset[str]]:
    for filename, expected in PINS.items():
        assert hashlib.sha256((root / PREFIX / filename).read_bytes()).hexdigest() == expected, (
            "Retained scientific version bytes changed; add an immutable new version: " + filename)
    locations = {}
    for identity in {item for pair in permitted_pairs() for item in pair}:
        relative, name = identity.rsplit(":", 1)
        nodes = [node for node in ast.parse((root / relative).read_text()).body
                 if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name]
        assert len(nodes) == 1, "An exact retained/current owner disappeared: " + identity
        locations[identity] = f"{relative}:{nodes[0].lineno}"
    return {frozenset(locations[item] for item in pair) for pair in permitted_pairs()}
