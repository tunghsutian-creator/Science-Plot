"""Declare and resolve source-backed publication profiles."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.publication_layouts import (
    composite_layout_ids,
)


PUBLICATION_PROFILE_KIND = "sciplot_publication_profile"


PUBLICATION_PROFILE_VERSION = 1


PUBLICATION_INTENT_KIND = "sciplot_publication_intent"


PUBLICATION_INTENT_VERSION = 1


TRANSFORM_LEDGER_KIND = "sciplot_transform_ledger"


TRANSFORM_LEDGER_VERSION = 1


DEFAULT_STANDALONE_PROFILE_ID = "sciplot_single_panel_v1"


DEFAULT_COMPOSITE_PROFILE_ID = "sciplot_composite_183_v1"


_NATURE_FIGURE_GUIDE = "https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/"


_NATURE_INITIAL_SUBMISSION = (
    "https://www.nature.com/nature/for-authors/initial-submission"
)


_NATURE_FINAL_SUBMISSION = "https://www.nature.com/nature/for-authors/final-submission"


_PUBLICATION_PROFILES: dict[str, dict[str, Any]] = {
    "sciplot_composite_183_v1": {
        "kind": PUBLICATION_PROFILE_KIND,
        "version": PUBLICATION_PROFILE_VERSION,
        "id": "sciplot_composite_183_v1",
        "label": "SciPlot 183 mm composite",
        "compliance_status": "house_profile",
        "description": (
            "SciPlot multi-panel layout: a 183 mm figure frame carries 180 mm of nominal panel "
            "width plus 3 mm of gutters or outer margin. It is not, by itself, proof of journal compliance."
        ),
        "checked_at": "2026-07-12",
        "source_urls": [],
        "required_formats": ["pdf", "tiff_300"],
        "page": {
            "allowed_widths_mm": [180.0, 183.0],
            "width_tolerance_mm": 0.6,
            "maximum_height_mm": 170.0,
        },
        "typography": {
            "allowed_font_families": ["Arial", "Helvetica", "Liberation Sans"],
            "minimum_text_size_pt": 5.0,
            "minimum_math_script_size_pt": 4.0,
            "recommended_minimum_text_size_pt": 6.0,
            "maximum_text_size_pt": 8.0,
            "require_embedded_fonts": True,
            "require_text_objects": True,
        },
        "strokes": {
            "minimum_width_pt": 0.25,
            "maximum_width_pt": 1.6,
            "artifact_coverage": "pdf_plus_exact_current_vsz",
        },
        "raster": {"minimum_effective_dpi": 300.0},
        "accessibility": {
            "non_color_distinction_required": True,
            "grayscale_review_required": True,
            "avoid_rainbow_palette": True,
            "minimum_simulated_delta_e": 10.0,
            "minimum_grayscale_luminance_delta": 0.08,
            "minimum_colormap_step_delta_e": 2.0,
            "minimum_colormap_luminance_range": 0.3,
            "maximum_colormap_luminance_turns": 1,
            "threshold_authority": "sciplot_internal_operational_gate",
        },
        "integrity": {
            "scientific_outcome_agnostic": True,
            "significance_required": False,
            "silent_data_omission_allowed": False,
            "statistics_must_be_explicit": True,
        },
        "composite_layout_ids": list(composite_layout_ids()),
    },
    "nature_flagship_research_2026_v1": {
        "kind": PUBLICATION_PROFILE_KIND,
        "version": PUBLICATION_PROFILE_VERSION,
        "id": "nature_flagship_research_2026_v1",
        "label": "Nature flagship research figure (checked 2026-07-12)",
        "compliance_status": "official_source_checked",
        "description": (
            "Source-checked profile for Nature flagship primary-research figures. Internal 60/90/120/180 mm "
            "panel tracks remain a SciPlot house layout, not an official Nature subdivision rule."
        ),
        "checked_at": "2026-07-12",
        "source_urls": [
            _NATURE_FIGURE_GUIDE,
            _NATURE_INITIAL_SUBMISSION,
            _NATURE_FINAL_SUBMISSION,
        ],
        "required_formats": ["pdf", "tiff_300"],
        "page": {
            "allowed_widths_mm": [89.0, 183.0],
            "width_tolerance_mm": 0.6,
            "maximum_height_mm": 170.0,
        },
        "typography": {
            "allowed_font_families": ["Arial", "Helvetica"],
            "minimum_text_size_pt": 5.0,
            "minimum_math_script_size_pt": 4.0,
            "recommended_minimum_text_size_pt": 5.0,
            # Nature's final-submission guidance uses 5--7 pt for ordinary
            # figure text, but explicitly calls for 8 pt bold panel labels in
            # multipart figures. Confirmed panel labels are matched to final
            # PDF spans, while the broad artifact envelope remains 5--8 pt.
            "maximum_text_size_pt": 8.0,
            "ordinary_text_minimum_size_pt": 5.0,
            "ordinary_text_maximum_size_pt": 7.0,
            "panel_label": {
                "size_pt": 8.0,
                "weight": "bold",
                "style": "upright",
                "sequence": "lowercase_alphabetical",
                "applies_to": "multipart_figures",
            },
            "role_aware_validation": {
                "status": "exact_label_inventory_required",
                "reason": (
                    "The 8 pt exception is validated only when confirmed panel labels can be matched "
                    "to final PDF text spans."
                ),
            },
            "require_embedded_fonts": True,
            "require_text_objects": True,
        },
        "strokes": {
            "minimum_width_pt": 0.25,
            "maximum_width_pt": 1.0,
            "artifact_coverage": "pdf_plus_exact_current_vsz",
        },
        "raster": {"minimum_effective_dpi": 300.0},
        "accessibility": {
            "non_color_distinction_required": True,
            "grayscale_review_required": True,
            "avoid_rainbow_palette": True,
            "avoid_colored_text": True,
            "minimum_simulated_delta_e": 10.0,
            "minimum_grayscale_luminance_delta": 0.08,
            "minimum_colormap_step_delta_e": 2.0,
            "minimum_colormap_luminance_range": 0.3,
            "maximum_colormap_luminance_turns": 1,
            "threshold_authority": "sciplot_internal_operational_gate_not_official_nature_threshold",
        },
        "integrity": {
            "scientific_outcome_agnostic": True,
            "significance_required": False,
            "silent_data_omission_allowed": False,
            "statistics_must_be_explicit": True,
        },
        "composite_layout_ids": list(composite_layout_ids()),
    },
}


_standalone_profile = deepcopy(_PUBLICATION_PROFILES[DEFAULT_COMPOSITE_PROFILE_ID])
_standalone_profile.update(
    {
        "id": DEFAULT_STANDALONE_PROFILE_ID,
        "label": "SciPlot ordinary single-panel figure",
        "description": (
            "SciPlot house profile for ordinary independent 60, 120, or 180 mm figures. "
            "It is separate from the explicit 183 mm multi-panel layout contract and is not, "
            "by itself, proof of journal compliance."
        ),
        "page": {
            "allowed_widths_mm": [60.0, 120.0, 180.0],
            "width_tolerance_mm": 0.6,
            "maximum_height_mm": 111.0,
        },
        "composite_layout_ids": [],
    }
)
_PUBLICATION_PROFILES[DEFAULT_STANDALONE_PROFILE_ID] = _standalone_profile


def list_publication_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": profile["id"],
            "label": profile["label"],
            "compliance_status": profile["compliance_status"],
            "checked_at": profile["checked_at"],
            "allowed_widths_mm": list(profile["page"]["allowed_widths_mm"]),
            "source_urls": list(profile["source_urls"]),
        }
        for profile in _PUBLICATION_PROFILES.values()
    ]


def get_publication_profile(profile_id: str) -> dict[str, Any]:
    if profile_id not in _PUBLICATION_PROFILES:
        known = ", ".join(sorted(_PUBLICATION_PROFILES))
        raise ValueError(
            f"Unknown publication profile `{profile_id}`. Available: {known}."
        )
    return deepcopy(_PUBLICATION_PROFILES[profile_id])


def resolve_publication_profile(
    value: str | Path | dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        profile = deepcopy(value)
    else:
        candidate = Path(value).expanduser()
        if candidate.exists():
            profile = json.loads(candidate.read_text(encoding="utf-8"))
        else:
            return get_publication_profile(str(value))
    if not isinstance(profile, dict):
        raise ValueError("Publication profile must be a JSON object.")
    if profile.get("kind") != PUBLICATION_PROFILE_KIND:
        raise ValueError(
            f"Publication profile kind must be `{PUBLICATION_PROFILE_KIND}`."
        )
    if not isinstance(profile.get("id"), str) or not str(profile["id"]).strip():
        raise ValueError("Publication profile needs a non-empty `id`.")
    return profile
