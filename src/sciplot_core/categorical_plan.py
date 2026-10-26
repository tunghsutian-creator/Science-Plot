"""Preflight ordinary source-bound categories in the existing plan envelope."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plan_identity import preview_identity_for
from sciplot_core.plan_preview_contract import PlanPreviewPayload, _preview_base
from sciplot_core.mapping_contract.categorical import validate_categorical_binding
from sciplot_core.studio_render.categorical_bindings import read_categorical_frame
from sciplot_core.studio_render.frame_series import _series_from_frame_records
from sciplot_core.studio_render.models import StudioPreparationBlocked


def categorical_render_options(binding: dict[str, Any]) -> dict[str, Any]:
    return {"legend_position": "auto", **{key: deepcopy(binding[key]) for key in
            ("series_styles", "yscale", "legend_position") if key in binding}}


def categorical_source_options(binding: dict[str, Any], *, missing_values: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {"categorical_binding": deepcopy(binding),
                               "render_options": categorical_render_options(binding)}
    if missing_values is not None:
        options["missing_values"] = missing_values
    if binding["mode"] != "given_values":
        options["summary_statistic"] = binding["mode"]
    return options


def build_categorical_preview(source: Path, *, request: dict[str, Any], current_identity: bool = True) -> PlanPreviewPayload:
    """Validate exact coordinates before project creation; no rule is inferred."""
    if request.get("rule_id"):
        raise StudioPreparationBlocked("categorical_rule_conflict", "An ordinary categorical binding does not declare a registered experiment.")
    binding = deepcopy(request["categorical_binding"])
    if current_identity:
        binding.setdefault("source_identity_version", 1)
        binding["source_namespace"] = str(source.resolve())
    validate_categorical_binding(binding, complete=True)
    template = "point_line" if binding.get("mode") == "given_values" else "bar"
    if request.get("template", template) != template:
        raise StudioPreparationBlocked("categorical_template_mismatch", "The selected mode determines the existing point_line or mean/sample-SD bar template.")
    options = categorical_source_options(binding, missing_values=request.get("missing_values"))
    expected_summary = "raw_only" if binding["mode"] == "given_values" else binding["mode"]
    if request.get("summary_statistic", expected_summary) != expected_summary:
        raise StudioPreparationBlocked("categorical_summary_mismatch", "The requested statistic conflicts with the declared categorical mode.")
    if "render_options" in request and request["render_options"] != options["render_options"]:
        raise StudioPreparationBlocked("categorical_display_binding_mismatch", "Render options must match the declared categorical display choices.")
    frame = read_categorical_frame(source, binding)
    if binding.get("source_identity_version") == 1:
        from sciplot_core.studio_render.categorical_bound_series import bound_categorical_series
        from sciplot_core.studio_render.categorical_source_identity import freeze_categorical_styles

        series, info = bound_categorical_series([frame], missing_values=request.get("missing_values"))
        binding = freeze_categorical_styles(binding, series=series, identities=info["source_bindings"], allow_labels=current_identity)
        frame.frame.attrs["categorical_binding"] = binding
        options = categorical_source_options(binding, missing_values=request.get("missing_values"))
    render_request = {"template": template, **options}
    _series_from_frame_records(render_request, frames=[frame])
    if binding["mode"] == "mean_sample_sd_n":
        from sciplot_core.categorical_disclosure import categorical_disclosure

        disclosure = categorical_disclosure(source, binding, policy=request.get("missing_values"))
        if ("replicate_summary_disclosure" in request and
                canonical_json_sha256(request["replicate_summary_disclosure"], allow_nan=False)
                != canonical_json_sha256(disclosure, allow_nan=False)):
            raise StudioPreparationBlocked("categorical_disclosure_changed", "The categorical count disclosure differs from the selected original cells.")
        options["replicate_summary_disclosure"] = disclosure
    elif "replicate_summary_disclosure" in request:
        raise StudioPreparationBlocked("categorical_disclosure_invalid", "A delivered valid-n disclosure requires mean_sample_sd_n mode.")
    digest = source_tree_sha256(source, expected_file_sha256=binding["source_sha256"])
    if digest is None:
        raise StudioPreparationBlocked("categorical_source_changed", "The categorical source disappeared during preflight.")
    payload: PlanPreviewPayload = {**_preview_base(source=source, rule_id=None, template=template),
        "status": "not_applicable", "resolved_figure_plan": None,
        "scientific_transform": None, "blocker": None,
        "source_options": options}
    if file_sha256(source) != binding["source_sha256"]:
        raise StudioPreparationBlocked("categorical_source_changed", "The categorical source changed during preflight.")
    payload["preview_identity"] = preview_identity_for(dict(payload), source_sha256=digest)
    return payload


def categorical_preview(source: Path, *, request: dict[str, Any], current_identity: bool = True) -> PlanPreviewPayload:
    from sciplot_core.plan_preview_contract import _blocked_preview

    try:
        return build_categorical_preview(source, request=request, current_identity=current_identity)
    except (OSError, ValueError) as exc:
        binding = request.get("categorical_binding")
        given = isinstance(binding, dict) and binding.get("mode") == "given_values"
        return _blocked_preview(source=source, rule_id=None,
            template="point_line" if given else "bar",
            reason_code=getattr(exc, "reason_code", "categorical_binding_invalid"), message=str(exc))
