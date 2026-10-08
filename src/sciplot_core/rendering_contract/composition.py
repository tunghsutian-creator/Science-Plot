"""New multi-panel policy, deliberately separate from legacy visual equivalence."""
from typing import Any

from .extraction import seal_contract

COMPOSITION_CONTRACT_ID = "sciplot-figure-composition-v1"
# These are new composition decisions, not extracted old renderer guarantees.
COMPOSITION_VALUES: dict[str, Any] = {
    "gap_x_mm": 6.0, "gap_y_mm": 6.0,
    "outer_margins_mm": {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0},
    "panel_width_mm": 60.0, "panel_height_mm": 55.0,
    "shared_decoration_policy": "explicit_resolution_groups",
    "panel_label_policy": "explicit_labels_in_reserved_top_margin",
    "dimension_policy": "fixed_panel_dimensions_plus_explicit_gaps",
}


def extract_composition_contract() -> dict[str, Any]:
    return seal_contract({
        "kind": "sciplot_rendering_style_contract", "schema_version": 1,
        "contract_id": COMPOSITION_CONTRACT_ID, "authority": "new_composition_policy",
        "properties": {key: {
            "status": "specified", "value": value,
            "source_file": "src/sciplot_core/rendering_contract/composition.py",
            "source_symbol": f"COMPOSITION_VALUES[{key}]",
            "notes": "New explicit composition policy; not a legacy multi-panel compatibility claim.",
        } for key, value in COMPOSITION_VALUES.items()},
    })
