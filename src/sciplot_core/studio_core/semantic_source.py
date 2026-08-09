"""Prepare one semantic Studio source and retain its typed evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.studio_render.value_parsing import _string_list


_SOURCE_ATTESTED_RULE_IDS = MECHANICAL_RULE_IDS | frozenset(
    {"dma_temperature_sweep", "rheology_temperature_sweep"}
)


def _studio_source_for_request(
    source: Path,
    *,
    request: dict[str, Any],
    base_dir: Path,
) -> tuple[
    Path,
    list[dict[str, Any]],
    PreparationSourceAttestation | None,
]:
    """Prepare the requested rule once and project its terminal sample order."""

    rule_id = str(request.get("rule_id") or "").strip()
    if not rule_id:
        return source, [], None
    from sciplot_core.semantic import classify_source, prepare_semantic_source

    output_dir = base_dir / "studio"
    semantic = classify_source(source, requested_rule_id=rule_id)
    curation_value = request.get("curation")
    curation_path: Path | None = None
    if isinstance(curation_value, str) and curation_value.strip():
        curation_path = Path(curation_value).expanduser()
        if not curation_path.is_absolute():
            curation_path = (base_dir / curation_path).resolve()
    prepared = prepare_semantic_source(
        source,
        output_dir=output_dir,
        semantic=semantic,
        curation_path=curation_path,
        series_order=request.get("series_order"),
        column_confirmations=request.get("column_confirmations"),
        replicate_mode=request.get("replicate_mode"),
    )
    prepared_source = prepared.get("source")
    source_attestation_value = prepared.get("source_attestation")
    source_attestation = (
        source_attestation_value
        if isinstance(source_attestation_value, PreparationSourceAttestation)
        else None
    )
    if rule_id in _SOURCE_ATTESTED_RULE_IDS and source_attestation is None:
        reason_prefix = _source_attestation_reason_prefix(rule_id)
        raise StudioPreparationBlocked(
            f"{reason_prefix}_preparation_attestation_missing",
            f"{rule_id} Studio preparation did not retain its typed source attestation.",
        )
    transform_steps = [
        step for step in prepared.get("transform_steps", []) if isinstance(step, dict)
    ]
    terminal_series_order = _semantic_terminal_series_order(transform_steps)
    if terminal_series_order:
        current_order = _string_list(request.get("series_order"))
        if (
            rule_id in _SOURCE_ATTESTED_RULE_IDS
            and current_order
            and current_order != terminal_series_order
        ):
            reason_prefix = _source_attestation_reason_prefix(rule_id)
            raise StudioPreparationBlocked(
                f"{reason_prefix}_figure_plan_source_mismatch",
                f"The resolved {rule_id} FigureTask sample order diverges from "
                "semantic preparation.",
            )
        request["series_order"] = terminal_series_order
        render_options = request.get("render_options")
        if isinstance(render_options, dict) and "series_order" in render_options:
            request["render_options"] = {
                **render_options,
                "series_order": terminal_series_order,
            }
    if isinstance(prepared_source, str) and prepared_source.strip():
        prepared_path = Path(prepared_source).expanduser()
        if source_attestation is not None:
            source_attestation.verify_current(
                source_root=source,
                prepared_source=prepared_path,
            )
        return prepared_path, transform_steps, source_attestation
    return source, transform_steps, source_attestation


def _semantic_terminal_series_order(
    transform_steps: list[dict[str, Any]],
) -> list[str]:
    for step in reversed(transform_steps):
        parameters = step.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key in ("output_sample_labels", "series_order", "sample_order"):
            values = parameters.get(key)
            if not isinstance(values, list | tuple):
                continue
            result: list[str] = []
            for value in values:
                label = str(value).strip()
                if label and label not in result:
                    result.append(label)
            if result:
                return result
    return []


def _source_attestation_reason_prefix(rule_id: str) -> str:
    return "temperature" if rule_id == "rheology_temperature_sweep" else rule_id


__all__ = ["_studio_source_for_request"]
