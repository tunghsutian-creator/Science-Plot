from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import file_sha256
from sciplot_core.publication_layouts import (
    COMPOSITE_CANVAS_WIDTH_MM,
    COMPOSITE_LAYOUT_KIND,
    COMPOSITE_LAYOUT_VERSION,
    COMPOSITE_NOMINAL_CONTENT_WIDTH_MM,
    build_composite_layout,
    composite_layout_ids,
    list_composite_layouts,
)

PUBLICATION_PROFILE_KIND = "sciplot_publication_profile"
PUBLICATION_PROFILE_VERSION = 1
PUBLICATION_INTENT_KIND = "sciplot_publication_intent"
PUBLICATION_INTENT_VERSION = 1
TRANSFORM_LEDGER_KIND = "sciplot_transform_ledger"
TRANSFORM_LEDGER_VERSION = 1
COMPOSITION_PLAN_KIND = "sciplot_publication_composition_plan"
COMPOSITION_PLAN_VERSION = 1

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
            "SciPlot composition strategy: a 183 mm figure canvas carries 180 mm of nominal panel "
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
            "panel tracks remain a SciPlot composition strategy, not an official Nature subdivision rule."
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
            "It is separate from the explicit 183 mm publication-composition contract and is not, "
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


def _composition_signature(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_legend_signature(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    fields = (
        "series_id",
        "label",
        "color",
        "marker",
        "line_style",
        "line_width_pt",
        "marker_fill_mode",
    )
    return [
        {key: deepcopy(item[key]) for key in fields if key in item}
        for item in value
        if isinstance(item, dict) and any(key in item for key in fields)
    ]


def _composition_axis_groups(
    modules: list[dict[str, Any]], axis: str
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        axis_signature = module.get("axis_signature")
        signature = (
            axis_signature.get(axis) if isinstance(axis_signature, dict) else None
        )
        if not isinstance(signature, dict) or not signature:
            continue
        grouped.setdefault(_composition_signature(signature), []).append(module)
    return [
        {
            "id": f"{axis}_axis_group_{index}",
            "axis": axis,
            "member_module_ids": [str(module["module_id"]) for module in members],
            "signature": deepcopy(members[0]["axis_signature"][axis]),
            "shared_scale_and_ticks_allowed": len(members) > 1,
            "late_bound_to_final_context": True,
        }
        for index, members in enumerate(grouped.values(), start=1)
        if len(members) > 1
    ]


def build_publication_composition_plan(
    layout_id: str,
    modules: Iterable[dict[str, Any]],
    *,
    canvas_height_mm: float = 55.0,
    legend_policy: str = "auto",
) -> dict[str, Any]:
    """Plan modular Veusz composition without mutating standalone VSZ files."""

    normalized_policy = str(legend_policy or "auto").strip().casefold()
    if normalized_policy not in {"auto", "shared_when_equivalent", "per_panel"}:
        raise ValueError(
            "Legend policy must be `auto`, `shared_when_equivalent`, or `per_panel`."
        )
    layout = build_composite_layout(layout_id, canvas_height_mm=canvas_height_mm)
    source_modules = [deepcopy(item) for item in modules if isinstance(item, dict)]
    slots = [item for item in layout["slots"] if isinstance(item, dict)]
    if len(source_modules) != len(slots):
        raise ValueError(
            f"Figure layout `{layout_id}` needs {len(slots)} explicit modules; "
            f"received {len(source_modules)}."
        )

    slot_by_id = {str(slot["id"]): slot for slot in slots}
    used_slots: set[str] = set()
    used_module_ids: set[str] = set()
    normalized_modules: list[dict[str, Any]] = []
    for index, (module, default_slot) in enumerate(
        zip(source_modules, slots, strict=True), start=1
    ):
        module_id = str(
            module.get("module_id") or module.get("id") or f"module_{index}"
        ).strip()
        if not module_id or module_id in used_module_ids:
            raise ValueError("Figure-layout module ids must be non-empty and unique.")
        slot_ref = str(module.get("slot_ref") or default_slot["id"]).strip()
        if slot_ref not in slot_by_id or slot_ref in used_slots:
            raise ValueError(
                "Figure-layout module slot refs must be unique ids from the "
                "selected layout."
            )
        used_module_ids.add(module_id)
        used_slots.add(slot_ref)
        slot = slot_by_id[slot_ref]
        axis_signature = (
            module.get("axis_signature")
            if isinstance(module.get("axis_signature"), dict)
            else {}
        )
        relationship_tags = module.get("relationship_tags")
        normalized_modules.append(
            {
                "module_id": module_id,
                "slot_ref": slot_ref,
                "panel_label": str(slot.get("panel_label") or ""),
                "target_size_mm": [float(slot["width_mm"]), float(slot["height_mm"])],
                "source_vsz": str(module.get("source_vsz") or "").strip() or None,
                "source_request_ref": str(
                    module.get("source_request_ref") or ""
                ).strip()
                or None,
                "legend_group": str(module.get("legend_group") or "").strip() or None,
                "legend_signature": _normalized_legend_signature(
                    module.get("legend_signature")
                ),
                "axis_signature": deepcopy(axis_signature),
                "relationship_tags": (
                    [str(item) for item in relationship_tags if str(item).strip()]
                    if isinstance(relationship_tags, list)
                    else []
                ),
                "standalone_document_policy": "preserve_unchanged",
            }
        )

    legend_buckets: dict[str, list[dict[str, Any]]] = {}
    for module in normalized_modules:
        explicit_group = module.get("legend_group")
        signature = module["legend_signature"]
        if explicit_group:
            bucket = f"declared:{explicit_group}"
        elif signature:
            bucket = f"signature:{_composition_signature(signature)}"
        else:
            bucket = f"module:{module['module_id']}"
        legend_buckets.setdefault(bucket, []).append(module)

    legend_groups: list[dict[str, Any]] = []
    legend_action_by_module: dict[str, str] = {}
    for index, members in enumerate(legend_buckets.values(), start=1):
        signatures = [
            _composition_signature(member["legend_signature"]) for member in members
        ]
        signatures_are_equivalent = (
            bool(members[0]["legend_signature"]) and len(set(signatures)) == 1
        )
        shared = (
            normalized_policy != "per_panel"
            and len(members) > 1
            and signatures_are_equivalent
        )
        mode = (
            "shared"
            if shared
            else ("per_panel_aligned" if len(members) > 1 else "per_panel")
        )
        group = {
            "id": f"legend_group_{index}",
            "mode": mode,
            "member_module_ids": [str(member["module_id"]) for member in members],
            "signature": deepcopy(members[0]["legend_signature"])
            if signatures_are_equivalent
            else [],
            "equivalence_rule": "exact_ordered_series_visual_signature",
            "merge_allowed": shared,
            "alignment_policy": "same_anchor_and_row_geometry_at_final_size",
        }
        if shared:
            group["host_policy"] = {
                "preferred": "safest_member_panel_key",
                "selection_stage": "after_final_panel_geometry_and_curve_footprints_are_known",
                "fallback": "dedicated_veusz_legend_host_graph",
            }
            action = "late_bound_shared_host"
        else:
            group["reason_not_shared"] = (
                "single_module"
                if len(members) == 1
                else "legend_signatures_differ_or_are_incomplete"
            )
            action = "keep_and_align"
        legend_groups.append(group)
        for member in members:
            legend_action_by_module[str(member["module_id"])] = action

    module_patches = [
        {
            "module_id": str(module["module_id"]),
            "slot_ref": str(module["slot_ref"]),
            "target_size_mm": list(module["target_size_mm"]),
            "legend_action": legend_action_by_module[str(module["module_id"])],
            "apply_to": "composition_variant_only",
            "preserve_source_vsz": True,
            "final_context_reflow_required": True,
        }
        for module in normalized_modules
    ]
    return {
        "kind": COMPOSITION_PLAN_KIND,
        "version": COMPOSITION_PLAN_VERSION,
        "layout": layout,
        "modules": normalized_modules,
        "legend_policy": normalized_policy,
        "legend_groups": legend_groups,
        "alignment_groups": {
            "plot_frames": {
                "member_module_ids": [
                    str(module["module_id"]) for module in normalized_modules
                ],
                "align_outer_frames": True,
                "synchronize_typography_and_strokes": True,
            },
            "x_axes": _composition_axis_groups(normalized_modules, "x"),
            "y_axes": _composition_axis_groups(normalized_modules, "y"),
        },
        "module_patches": module_patches,
        "renderer_plan": {
            "engine": "veusz",
            "python_role": "contract_orchestration_and_veusz_command_generation_only",
            "python_draws_or_composes_pixels": False,
            "matplotlib_allowed": False,
            "document_shape": "one_page_grid_native_graphs",
            "shared_legend_implementation": "member_key_or_dedicated_graph_with_proxy_plotters",
            "raster_panel_composition_allowed": False,
        },
        "authority_policy": {
            "standalone_vsz_files_remain_unchanged": True,
            "composition_variants_are_separate_artifacts": True,
            "composite_vsz_becomes_visual_authority_after_manual_save": True,
            "regeneration_must_archive_current_composite_vsz": True,
            "arbitrary_manual_child_vsz_merge_is_not_automatic": True,
        },
        "state": "planned_not_compiled",
    }


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


def _figure_height_mm(request: dict[str, Any]) -> float:
    options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    size = options.get("size")
    if isinstance(size, str) and "x" in size.casefold():
        try:
            return float(size.casefold().split("x", 1)[1])
        except ValueError:
            pass
    return 55.0


def _statistics_contract_for_figure(figure: dict[str, Any]) -> dict[str, Any]:
    template = str(figure.get("default_template") or "").casefold()
    figure_id = str(figure.get("id") or "").casefold()
    needs_method = template in {
        "bar",
        "box",
        "box_strip",
        "violin",
        "point_interval",
    } or ("statistics" in figure_id)
    return {
        "kind": "sciplot_statistics_method_contract",
        "version": 1,
        "status": "pending" if needs_method else "not_requested",
        "auto_inference_allowed": False,
        "significance_required": False,
        "method_id": None,
        "method_version": None,
        "n_definition": None,
        "center": None,
        "spread_or_interval": None,
        "test": None,
        "multiple_comparisons": None,
        "parameters": {},
    }


def _explicit_request_text(request: dict[str, Any], key: str) -> tuple[bool, str]:
    if key not in request:
        return False, ""
    return True, str(request.get(key) or "").strip()


def _merge_existing(
    defaults: dict[str, Any], existing: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge an existing contract additively, with existing values authoritative."""

    merged = deepcopy(defaults)
    if not isinstance(existing, dict):
        return merged
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_existing(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _merge_keyed_contracts(
    defaults: list[dict[str, Any]],
    existing: object,
    *,
    id_key: str,
) -> list[dict[str, Any]]:
    existing_items = (
        [deepcopy(item) for item in existing if isinstance(item, dict)]
        if isinstance(existing, list)
        else []
    )
    existing_by_id = {
        str(item.get(id_key)): item
        for item in existing_items
        if isinstance(item.get(id_key), str) and str(item[id_key]).strip()
    }
    merged: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for default in defaults:
        item_id = str(default.get(id_key) or "")
        prior = existing_by_id.get(item_id)
        merged.append(_merge_existing(default, prior))
        if prior is not None:
            consumed.add(item_id)
    merged.extend(
        item
        for item in existing_items
        if not isinstance(item.get(id_key), str)
        or str(item.get(id_key)) not in consumed
    )
    return merged


def _reference_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return deepcopy(value) if isinstance(value, list) else []


def _figure_contracts(
    study_model: dict[str, Any], existing: dict[str, Any]
) -> list[dict[str, Any]]:
    figures = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
    defaults: list[dict[str, Any]] = []
    for index, figure in enumerate(figures, start=1):
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("id") or f"figure_{index}")
        evidence = (
            figure.get("evidence_contract")
            if isinstance(figure.get("evidence_contract"), dict)
            else {}
        )
        defaults.append(
            {
                "figure_id": figure_id,
                "order": index,
                "title": str(figure.get("title") or ""),
                "role": "independent_figure_candidate",
                "question": "",
                "supported_claim_refs": _reference_list(evidence, "claim_refs"),
                "metric_refs": _reference_list(evidence, "metric_refs")
                or ([figure.get("metric")] if figure.get("metric") else []),
                "sample_refs": _reference_list(evidence, "sample_refs"),
                "source_refs": _reference_list(evidence, "source_refs"),
                "transform_step_refs": _reference_list(evidence, "transform_step_refs"),
                "confirmation_status": str(
                    evidence.get("confirmation_status") or "pending"
                ),
                "statistics_method": deepcopy(
                    figure.get("statistics_method")
                    if isinstance(figure.get("statistics_method"), dict)
                    else _statistics_contract_for_figure(figure)
                ),
            }
        )
    return _merge_keyed_contracts(
        defaults,
        existing.get("figure_contracts"),
        id_key="figure_id",
    )


def _panel_defaults_for_layout(
    layout: dict[str, Any] | None,
    existing_panels: object,
) -> list[dict[str, Any]]:
    if not isinstance(layout, dict):
        return []
    prior = (
        [item for item in existing_panels if isinstance(item, dict)]
        if isinstance(existing_panels, list)
        else []
    )
    defaults: list[dict[str, Any]] = []
    for index, slot in enumerate(layout.get("slots", []), start=1):
        if not isinstance(slot, dict):
            continue
        prior_id = prior[index - 1].get("panel_id") if index <= len(prior) else None
        panel_id = str(prior_id or slot.get("id") or f"panel_{index}")
        defaults.append(
            {
                "panel_id": panel_id,
                "order": index,
                "panel_label": str(
                    slot.get("panel_label") or chr(ord("a") + index - 1)
                ),
                "role": "primary_evidence" if index == 1 else "supporting_evidence",
                "slot_ref": str(slot.get("id") or ""),
                "question": "",
                "supported_claim_refs": [],
                "metric_refs": [],
                "sample_refs": [],
                "source_refs": [],
                "transform_step_refs": [],
                "confirmation_status": "pending",
                "statistics_method": _statistics_contract_for_figure({}),
            }
        )
    return defaults


def build_publication_intent(
    study_model: dict[str, Any],
    *,
    request: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = request if isinstance(request, dict) else {}
    existing = deepcopy(existing) if isinstance(existing, dict) else {}
    layout_is_explicit, explicit_layout = _explicit_request_text(
        request, "publication_layout"
    )
    if layout_is_explicit:
        layout_id = explicit_layout or None
        layout_status = "confirmed" if layout_id else "pending"
    else:
        layout_id = str(existing.get("layout_id") or "").strip() or None
        layout_status = str(
            existing.get("layout_status") or ("inferred" if layout_id else "pending")
        )
    layout = (
        build_composite_layout(layout_id, canvas_height_mm=_figure_height_mm(request))
        if layout_id
        else None
    )

    profile_is_explicit, explicit_profile = _explicit_request_text(
        request, "publication_profile"
    )
    existing_profile = str(existing.get("target_profile_id") or "").strip()
    existing_target_status = str(existing.get("target_status") or "").strip().casefold()
    if profile_is_explicit and explicit_profile:
        profile_id = explicit_profile
    elif existing_profile and existing_target_status == "confirmed":
        profile_id = existing_profile
    elif layout_id:
        profile_id = DEFAULT_COMPOSITE_PROFILE_ID
    elif existing_profile and existing_profile != DEFAULT_COMPOSITE_PROFILE_ID:
        profile_id = existing_profile
    else:
        # Older requests inferred the composite profile even when they had no
        # publication layout.  Migrate that unconfirmed default to the
        # ordinary single-panel contract; explicit or confirmed choices remain
        # authoritative.
        profile_id = DEFAULT_STANDALONE_PROFILE_ID
    profile = get_publication_profile(str(profile_id))

    question_is_explicit, explicit_question = _explicit_request_text(
        request, "scientific_question"
    )
    question = (
        explicit_question
        if question_is_explicit
        else str(existing.get("scientific_question") or "").strip()
    )
    question_status = (
        ("confirmed" if question else "pending")
        if question_is_explicit
        else str(
            existing.get("question_status") or ("inferred" if question else "pending")
        )
    )
    claim_is_explicit, explicit_claim = _explicit_request_text(request, "core_claim")
    claim = (
        explicit_claim
        if claim_is_explicit
        else str(existing.get("core_claim") or "").strip()
    )
    claim_status = (
        ("confirmed" if claim else "pending")
        if claim_is_explicit
        else str(existing.get("claim_status") or ("inferred" if claim else "pending"))
    )
    target_status = (
        "confirmed"
        if profile_is_explicit and explicit_profile
        else str(existing.get("target_status") or "inferred")
    )

    figure_contracts = _figure_contracts(study_model, existing)
    panel_defaults = _panel_defaults_for_layout(layout, existing.get("panels"))
    panel_contracts = _merge_keyed_contracts(
        panel_defaults,
        existing.get("panels"),
        id_key="panel_id",
    )
    caption_contract = _merge_existing(
        {
            "status": "pending",
            "define_symbols_and_colors": True,
            "define_n_and_error_representation": True,
            "state_data_transformations": True,
        },
        existing.get("caption_contract")
        if isinstance(existing.get("caption_contract"), dict)
        else None,
    )
    palette_policy = _merge_existing(
        {
            "palette_id": None,
            "non_color_distinction_required": True,
            "grayscale_review_required": True,
            "library_default_palette_allowed": False,
        },
        existing.get("palette_policy")
        if isinstance(existing.get("palette_policy"), dict)
        else None,
    )
    render_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    if "palette_preset" in render_options:
        palette_policy["palette_id"] = render_options.get("palette_preset")

    existing_composition = (
        existing.get("composition_plan")
        if isinstance(existing.get("composition_plan"), dict)
        else None
    )
    if "composition_modules" in request:
        composition_modules = request.get("composition_modules")
    elif existing_composition is not None:
        composition_modules = existing_composition.get("modules")
    else:
        composition_modules = None
    composition_plan = None
    if layout_id and isinstance(composition_modules, list) and composition_modules:
        composition_plan = build_publication_composition_plan(
            layout_id,
            composition_modules,
            canvas_height_mm=float(layout["canvas_height_mm"])
            if layout
            else _figure_height_mm(request),
            legend_policy=str(
                request.get("composition_legend_policy")
                or (existing_composition or {}).get("legend_policy")
                or "auto"
            ),
        )

    layout_slot_count = len(layout.get("slots", [])) if isinstance(layout, dict) else 0
    panel_count_mismatch = bool(layout and len(panel_contracts) != layout_slot_count)
    review_risk = {
        "status": "pending",
        "missing_question": not bool(question),
        "missing_claim": not bool(claim),
        "panel_count_mismatch": panel_count_mismatch,
        "pending_statistics_panels": [
            panel["panel_id"]
            for panel in panel_contracts
            if isinstance(panel.get("statistics_method"), dict)
            and panel["statistics_method"].get("status") == "pending"
        ],
        "pending_statistics_figures": [
            figure["figure_id"]
            for figure in figure_contracts
            if isinstance(figure.get("statistics_method"), dict)
            and figure["statistics_method"].get("status") == "pending"
        ],
    }
    for key, value in (
        existing.get("review_risk")
        if isinstance(existing.get("review_risk"), dict)
        else {}
    ).items():
        if key not in review_risk:
            review_risk[key] = deepcopy(value)

    payload = {
        "kind": PUBLICATION_INTENT_KIND,
        "version": PUBLICATION_INTENT_VERSION,
        "id": str(existing.get("id") or "publication_intent_1"),
        "status": str(existing.get("status") or "draft"),
        "scientific_question": question,
        "question_status": question_status,
        "core_claim": claim,
        "claim_status": claim_status,
        "target_profile_id": profile["id"],
        "target_status": target_status,
        "layout_id": layout_id,
        "layout_status": layout_status,
        "figure_layout": layout,
        "composition_plan": composition_plan,
        "figure_contracts": figure_contracts,
        "panels": panel_contracts,
        "exact_labels": deepcopy(existing.get("exact_labels") or {}),
        "caption_contract": caption_contract,
        "palette_policy": palette_policy,
        "integrity_policy": deepcopy(profile["integrity"]),
        "review_risk": review_risk,
    }
    for key, value in existing.items():
        if key not in payload:
            payload[key] = deepcopy(value)
    return payload


def _table_shape(path: Path) -> list[int] | None:
    if path.stat().st_size > 20 * 1024 * 1024:
        return None
    try:
        suffix = path.suffix.casefold()
        if suffix in {".xlsx", ".xls"}:
            frame = pd.read_excel(path, sheet_name=0, header=None)
        elif suffix == ".tsv":
            frame = pd.read_csv(path, sep="\t", header=None)
        elif suffix in {".csv", ".txt"}:
            frame = pd.read_csv(path, header=None)
        else:
            return None
    except Exception:
        return None
    return [int(frame.shape[0]), int(frame.shape[1])]


def artifact_record(path: str | Path, *, artifact_id: str, role: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {
            "id": artifact_id,
            "role": role,
            "path": str(resolved),
            "exists": False,
            "sha256": None,
        }
    if resolved.is_file():
        return {
            "id": artifact_id,
            "role": role,
            "kind": "file",
            "path": str(resolved),
            "exists": True,
            "size_bytes": resolved.stat().st_size,
            "sha256": file_sha256(resolved),
            "table_shape": _table_shape(resolved),
        }

    digest = hashlib.sha256()
    member_count = 0
    total_bytes = 0
    for member in sorted(path for path in resolved.rglob("*") if path.is_file()):
        relative = member.relative_to(resolved).as_posix()
        member_hash = file_sha256(member)
        digest.update(relative.encode("utf-8"))
        digest.update(member_hash.encode("ascii"))
        member_count += 1
        total_bytes += member.stat().st_size
    return {
        "id": artifact_id,
        "role": role,
        "kind": "directory",
        "path": str(resolved),
        "exists": True,
        "size_bytes": total_bytes,
        "sha256": digest.hexdigest(),
        "member_count": member_count,
        "table_shape": None,
    }


def build_transform_step(
    *,
    step_id: str,
    operation: str,
    input_path: str | Path,
    output_path: str | Path | None,
    implementation_ref: str,
    parameters: dict[str, Any] | None = None,
    additional_outputs: Iterable[str | Path] = (),
) -> dict[str, Any]:
    input_artifact = artifact_record(
        input_path, artifact_id=f"{step_id}_input", role="input"
    )
    output_artifacts: list[dict[str, Any]] = []
    if output_path is not None:
        output_artifacts.append(
            artifact_record(output_path, artifact_id=f"{step_id}_output", role="output")
        )
    for index, path in enumerate(additional_outputs, start=1):
        output_artifacts.append(
            artifact_record(
                path,
                artifact_id=f"{step_id}_output_{index + 1}",
                role="supporting_output",
            )
        )
    return {
        "id": step_id,
        "operation": operation,
        "implementation_ref": implementation_ref,
        "input_refs": [input_artifact["id"]],
        "output_refs": [artifact["id"] for artifact in output_artifacts],
        "input_artifacts": [input_artifact],
        "output_artifacts": output_artifacts,
        "parameters": deepcopy(parameters or {}),
        "input_shape": input_artifact.get("table_shape"),
        "output_shape": output_artifacts[0].get("table_shape")
        if output_artifacts
        else None,
        "confirmation_status": "runtime_recorded",
        "silent_omission_allowed": False,
        "outcome_strength_gate_applied": False,
    }


def build_transform_ledger(
    study_model: dict[str, Any],
    *,
    request: dict[str, Any] | None,
    input_path: str | Path,
    steps: Iterable[dict[str, Any]] = (),
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = request if isinstance(request, dict) else {}
    existing = deepcopy(existing) if isinstance(existing, dict) else {}
    recorded_steps = [deepcopy(step) for step in steps if isinstance(step, dict)]
    if not recorded_steps and isinstance(existing.get("steps"), list):
        recorded_steps = [
            deepcopy(step) for step in existing["steps"] if isinstance(step, dict)
        ]
    if not recorded_steps:
        recorded_steps = [
            build_transform_step(
                step_id="identity_source",
                operation="identity",
                input_path=input_path,
                output_path=input_path,
                implementation_ref="sciplot_core.workflow.run_request",
                parameters={
                    "reason": "No deterministic data transformation was applied before rendering."
                },
            )
        ]
    unresolved_step_ids = [
        str(step.get("id") or "")
        for step in recorded_steps
        if str(step.get("confirmation_status") or "runtime_recorded")
        not in {"runtime_recorded", "confirmed", "not_applicable"}
    ]
    first_step_inputs = (
        recorded_steps[0].get("input_artifacts")
        if isinstance(recorded_steps[0].get("input_artifacts"), list)
        else []
    )
    first_source_path = next(
        (
            str(artifact.get("path"))
            for artifact in first_step_inputs
            if isinstance(artifact, dict)
            and isinstance(artifact.get("path"), str)
            and str(artifact.get("path")).strip()
        ),
        str(Path(input_path).expanduser().resolve()),
    )
    payload = {
        "kind": TRANSFORM_LEDGER_KIND,
        "version": TRANSFORM_LEDGER_VERSION,
        "status": "needs_human_confirmation"
        if unresolved_step_ids
        else "runtime_recorded",
        "source_root": str(Path(first_source_path).expanduser().resolve()),
        "replicate_policy": deepcopy(study_model.get("replicate_policy") or {}),
        "column_confirmations": deepcopy(request.get("column_confirmations") or []),
        "steps": recorded_steps,
        "unresolved_step_ids": unresolved_step_ids,
        "policy": {
            "raw_sources_preserved": True,
            "silent_data_omission_allowed": False,
            "selection_must_be_recorded": True,
            "unit_conversion_must_be_recorded": True,
            "input_output_shape_preferred": True,
            "scientific_outcome_agnostic": True,
        },
    }
    for key, value in existing.items():
        if key not in payload:
            payload[key] = deepcopy(value)
    return payload


def publication_target_is_confirmed(intent: dict[str, Any] | None) -> bool:
    return bool(isinstance(intent, dict) and intent.get("target_status") == "confirmed")


def link_intent_to_transform_ledger(
    publication_intent: dict[str, Any],
    transform_ledger: dict[str, Any],
) -> dict[str, Any]:
    linked = deepcopy(publication_intent)
    step_refs = [
        str(step.get("id"))
        for step in transform_ledger.get("steps", [])
        if isinstance(step, dict) and step.get("id")
    ]
    valid_refs = set(step_refs)
    for contract_key in ("panels", "figure_contracts"):
        contracts = (
            linked.get(contract_key)
            if isinstance(linked.get(contract_key), list)
            else []
        )
        structured = [contract for contract in contracts if isinstance(contract, dict)]
        for contract in structured:
            existing_refs = contract.get("transform_step_refs")
            if isinstance(existing_refs, list) and existing_refs:
                contract["transform_step_refs"] = [
                    str(ref) for ref in existing_refs if str(ref) in valid_refs
                ]
                contract["transform_binding_status"] = (
                    "explicit_validated"
                    if contract["transform_step_refs"]
                    else "pending_explicit_binding"
                )
            elif len(structured) == 1 and step_refs:
                contract["transform_step_refs"] = step_refs
                contract["transform_binding_status"] = "single_figure_shared_source"
            else:
                contract["transform_step_refs"] = []
                contract["transform_binding_status"] = "pending_explicit_binding"
    linked["transform_ledger_ref"] = "transform_ledger.json"
    return linked


def write_publication_artifacts(
    output_dir: Path,
    *,
    publication_intent: dict[str, Any],
    transform_ledger: dict[str, Any],
    publication_profile: dict[str, Any],
    publication_qa: dict[str, Any] | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "publication_intent": output_dir / "publication_intent.json",
        "transform_ledger": output_dir / "transform_ledger.json",
        "journal_profile": output_dir / "journal_profile.json",
    }
    payloads = {
        "publication_intent": publication_intent,
        "transform_ledger": transform_ledger,
        "journal_profile": publication_profile,
    }
    if publication_qa is not None:
        artifacts["publication_qa"] = output_dir / "publication_qa.json"
        payloads["publication_qa"] = publication_qa
    for key, path in artifacts.items():
        path.write_text(
            json.dumps(payloads[key], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {key: str(path) for key, path in artifacts.items()}


__all__ = [
    "COMPOSITE_CANVAS_WIDTH_MM",
    "COMPOSITE_LAYOUT_KIND",
    "COMPOSITE_LAYOUT_VERSION",
    "COMPOSITE_NOMINAL_CONTENT_WIDTH_MM",
    "COMPOSITION_PLAN_KIND",
    "COMPOSITION_PLAN_VERSION",
    "PUBLICATION_INTENT_KIND",
    "PUBLICATION_INTENT_VERSION",
    "PUBLICATION_PROFILE_KIND",
    "PUBLICATION_PROFILE_VERSION",
    "TRANSFORM_LEDGER_KIND",
    "TRANSFORM_LEDGER_VERSION",
    "artifact_record",
    "build_composite_layout",
    "build_publication_composition_plan",
    "build_publication_intent",
    "build_transform_ledger",
    "build_transform_step",
    "get_publication_profile",
    "list_composite_layouts",
    "list_publication_profiles",
    "link_intent_to_transform_ledger",
    "publication_target_is_confirmed",
    "resolve_publication_profile",
    "write_publication_artifacts",
]
