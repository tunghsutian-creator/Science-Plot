"""Build one normalized publication intent."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from sciplot_core.publication_layouts import (
    build_composite_layout,
)

from sciplot_core.publication.profiles import (
    PUBLICATION_INTENT_KIND,
    PUBLICATION_INTENT_VERSION,
    DEFAULT_STANDALONE_PROFILE_ID,
    DEFAULT_COMPOSITE_PROFILE_ID,
    get_publication_profile,
)

from sciplot_core.publication.intent_helpers import (
    _figure_height_mm,
    _explicit_request_text,
    _merge_existing,
    _merge_keyed_contracts,
    _figure_contracts,
    _panel_defaults_for_layout,
)


def build_publication_intent(
    study_model: dict[str, Any],
    *,
    request: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = request if isinstance(request, dict) else {}
    existing = deepcopy(existing) if isinstance(existing, dict) else {}
    removed_keys = sorted(
        key
        for key in ("composition_modules", "composition_legend_policy")
        if key in request
    )
    if removed_keys:
        raise ValueError(
            "Removed publication Composition request key(s): "
            f"{', '.join(removed_keys)}. Assemble multi-panel figures in native "
            "Veusz and use `publication_layout` only as metadata/QA intent."
        )
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
        "figure_contracts": figure_contracts,
        "panels": panel_contracts,
        "exact_labels": deepcopy(existing.get("exact_labels") or {}),
        "caption_contract": caption_contract,
        "palette_policy": palette_policy,
        "integrity_policy": deepcopy(profile["integrity"]),
        "review_risk": review_risk,
    }
    for key, value in existing.items():
        if key not in payload and key != "composition_plan":
            payload[key] = deepcopy(value)
    return payload
