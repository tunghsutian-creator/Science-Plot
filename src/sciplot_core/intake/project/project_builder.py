"""Build one portable confirmed intake project."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import reserve_unique_directory, slug
from sciplot_core.figure_plan import sync_figure_plan_projection
from sciplot_core.materials_rules import get_rule, resolve_rule_template
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY
from sciplot_core.publication import (
    build_publication_intent,
    build_transform_ledger,
    get_publication_profile,
)
from sciplot_core.project_manifest import commit_intake_project_manifest
from sciplot_core.study_model import build_study_model

from ..catalog import _catalog_item, converge_material_review_notes
from ..config import _DEFAULT_OUTPUT_ROOT
from ..models import IntakeGroupInput
from ..packaging import (
    _apply_launcher_contract_to_manifest,
    _read_json_if_exists,
    _write_zip,
    converge_intake_project_launchers,
)
from ..session import (
    _experiment_render_options,
    _experiment_template,
    _resolve_plot_output,
    _selected_column_confirmations,
    _selected_exports,
    _selected_render_options,
    _selected_replicate_mode,
)
from ..table_preview import _duplicate_source_warnings
from .source_materialization import materialize_intake_groups


def create_intake_project(
    *,
    project_name: str,
    data_type_id: str,
    experiment_type_id: str,
    groups: list[IntakeGroupInput],
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    plot_output: str | Path | None = None,
    exports: list[str] | tuple[str, ...] | None = None,
    render_options: dict[str, Any] | None = None,
    column_confirmations: list[dict[str, Any]] | None = None,
    replicate_mode: str | None = None,
    recognition: dict[str, Any] | None = None,
    template: str | None = None,
    delivery_root: Path | None = None,
    group_order_is_explicit: bool = True,
    studio_preparer: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    _, experiment = _catalog_item(data_type_id, experiment_type_id)
    cleaned_groups = [group for group in groups if group.sample.strip() and group.files]
    if not cleaned_groups:
        raise ValueError("At least one named sample group with files is required.")
    project_slug = slug(
        project_name
        or f"{experiment['label']}_{'_'.join(group.sample for group in cleaned_groups)}"
    )
    resolved_output_root = output_root.expanduser().resolve()
    project_dir = reserve_unique_directory(resolved_output_root, project_slug)
    try:
        return _create_intake_project_in_reserved_directory(
            project_name=project_name,
            data_type_id=data_type_id,
            experiment_type_id=experiment_type_id,
            groups=cleaned_groups,
            output_root=resolved_output_root,
            plot_output=plot_output,
            exports=exports,
            render_options=render_options,
            column_confirmations=column_confirmations,
            replicate_mode=replicate_mode,
            recognition=recognition,
            template=template,
            delivery_root=delivery_root,
            group_order_is_explicit=group_order_is_explicit,
            studio_preparer=studio_preparer,
            project_dir=project_dir,
        )
    except BaseException:
        shutil.rmtree(project_dir)
        raise


def _create_intake_project_in_reserved_directory(
    *,
    project_name: str,
    data_type_id: str,
    experiment_type_id: str,
    groups: list[IntakeGroupInput],
    output_root: Path,
    plot_output: str | Path | None,
    exports: list[str] | tuple[str, ...] | None,
    render_options: dict[str, Any] | None,
    column_confirmations: list[dict[str, Any]] | None,
    replicate_mode: str | None,
    recognition: dict[str, Any] | None,
    template: str | None,
    delivery_root: Path | None,
    group_order_is_explicit: bool,
    studio_preparer: Callable[[Path], dict[str, Any]],
    project_dir: Path,
) -> dict[str, Any]:
    data_type, experiment = _catalog_item(data_type_id, experiment_type_id)
    cleaned_groups = [group for group in groups if group.sample.strip() and group.files]
    if not cleaned_groups:
        raise ValueError("At least one named sample group with files is required.")

    group_series_order = (
        [group.sample.strip() for group in cleaned_groups]
        if group_order_is_explicit
        else []
    )
    project_slug = project_dir.name
    source_dir, runs_dir, manifest_groups = materialize_intake_groups(
        project_dir=project_dir,
        groups=cleaned_groups,
    )

    rule_id = experiment.get("rule_id")
    recognition_payload = dict(recognition) if isinstance(recognition, dict) else {}
    if isinstance(rule_id, str) and rule_id.strip():
        rule_payload = get_rule(rule_id).to_payload()
        recognition_payload = {
            "semantic_family": rule_payload.get("semantic_family"),
            "rule_id": rule_payload.get("rule_id"),
            "fixture_status": rule_payload.get("fixture_status"),
            "template": rule_payload.get("template"),
            "render_options": dict(rule_payload.get("render_options") or {}),
            "axis_plan": dict(rule_payload.get("axis_plan") or {}),
            **recognition_payload,
        }
    recognition_payload.setdefault("semantic_family", experiment_type_id)
    recognition_payload.setdefault("rule_id", rule_id)
    recognition_payload.setdefault("fixture_status", "ready" if rule_id else "unknown")
    selected_output = _resolve_plot_output(
        plot_output,
        project_dir=project_dir,
        default_output=runs_dir / "run_001",
    )
    selected_exports = _selected_exports(exports)
    requested_template = str(template or "").strip() or None
    selected_template = _experiment_template(experiment)
    if selected_template is None:
        semantic_template = recognition_payload.get("template")
        if isinstance(semantic_template, str) and semantic_template.strip():
            selected_template = semantic_template.strip()
    selected_template = requested_template or selected_template
    effective_rule_id = str(rule_id or recognition_payload.get("rule_id") or "").strip()
    if effective_rule_id:
        selected_template = resolve_rule_template(
            get_rule(effective_rule_id),
            selected_template,
        )
    selected_experiment = dict(experiment)
    selected_experiment["rule_id"] = effective_rule_id or None
    if selected_template is not None:
        selected_experiment["template"] = selected_template
        selected_experiment["chart"] = selected_template
    contract_template = selected_template
    if contract_template is None and isinstance(experiment.get("chart"), str):
        contract_template = str(experiment.get("chart") or "").strip() or None
    semantic_render_options = (
        dict(recognition_payload.get("render_options"))
        if isinstance(recognition_payload.get("render_options"), dict)
        else {}
    )
    explicit_user_render_options = _selected_render_options(
        render_options, template=contract_template
    )
    selected_user_render_options = _selected_render_options(
        {
            **_experiment_render_options(experiment),
            **explicit_user_render_options,
        },
        template=contract_template,
    )
    selected_render_options = {
        **semantic_render_options,
        **selected_user_render_options,
    }
    axis_plan = (
        recognition_payload.get("axis_plan")
        if isinstance(recognition_payload.get("axis_plan"), dict)
        else {}
    )
    for axis_name, option_name in (
        ("x", "x_label_override"),
        ("y", "y_label_override"),
    ):
        axis_payload = (
            axis_plan.get(axis_name)
            if isinstance(axis_plan.get(axis_name), dict)
            else {}
        )
        display_label = axis_payload.get("display_label")
        if isinstance(display_label, str) and display_label.strip():
            selected_render_options.setdefault(option_name, display_label.strip())
    if group_series_order:
        selected_render_options.setdefault("series_order", group_series_order)
    render_series_order = selected_render_options.get("series_order")
    series_order = (
        [str(value).strip() for value in render_series_order if str(value).strip()]
        if isinstance(render_series_order, list | tuple)
        else []
    )
    selected_column_confirmations = _selected_column_confirmations(column_confirmations)
    selected_replicate_mode = _selected_replicate_mode(
        replicate_mode
        if replicate_mode is not None
        else experiment.get("default_replicate_mode")
    )
    plot_request = {
        "recipe": "auto",
        "input": str(source_dir),
        "output": str(selected_output),
        "exports": selected_exports,
        "replicate_mode": selected_replicate_mode,
        "review_notes": ["Prepared by SciPlot from the selected data mapping."],
    }
    if series_order:
        plot_request["series_order"] = series_order
    if selected_render_options:
        plot_request["render_options"] = selected_render_options
    plot_request["explicit_render_option_keys"] = sorted(explicit_user_render_options)
    if selected_template:
        plot_request["template"] = selected_template
    if requested_template:
        plot_request["explicit_template_selection"] = True
    if effective_rule_id:
        plot_request["rule_id"] = effective_rule_id
    if recognition_payload.get("pending_rule_review") is True:
        plot_request["pending_rule_review"] = True
    if delivery_root is not None:
        plot_request[REQUEST_DELIVERY_ROOT_KEY] = str(
            delivery_root.expanduser().resolve()
        )
    converge_material_review_notes(plot_request)
    if selected_column_confirmations:
        plot_request["column_confirmations"] = selected_column_confirmations

    created_at = utc_now_iso()
    warnings = _duplicate_source_warnings(manifest_groups)
    if warnings:
        plot_request["review_notes"].extend(str(item["message"]) for item in warnings)
    study_model = build_study_model(
        data_type=data_type,
        experiment=selected_experiment,
        groups=manifest_groups,
        replicate_mode=selected_replicate_mode,
        render_options=selected_render_options,
        column_confirmations=selected_column_confirmations,
    )
    plot_request["study_model"] = study_model
    publication_intent = build_publication_intent(study_model, request=plot_request)
    transform_ledger = build_transform_ledger(
        study_model,
        request=plot_request,
        input_path=source_dir,
    )
    # Intake has only planned the deterministic run. It must not claim that an
    # identity transform (or any other transform) has already occurred.
    transform_ledger["status"] = "pending_runtime"
    transform_ledger["steps"] = []
    transform_ledger["pending_reason"] = (
        "Runtime transform steps are recorded when SciPlot prepares the Veusz document or executes the request."
    )
    plot_request["publication_intent"] = publication_intent
    plot_request["transform_ledger"] = transform_ledger
    manifest = {
        "kind": "sciplot_intake_project",
        "version": 1,
        "created_at": created_at,
        "project_name": project_name,
        "project_slug": project_slug,
        "data_type": {"id": data_type["id"], "label": data_type["label"]},
        "experiment": {
            "id": selected_experiment["id"],
            "label": selected_experiment["label"],
            "rule_id": effective_rule_id or None,
            "chart": selected_experiment.get("chart"),
            "template": selected_template,
        },
        "recognition": json_safe(recognition_payload),
        "groups": manifest_groups,
        "warnings": warnings,
        "source_dir": str(source_dir),
        "plot_request": str(project_dir / "plot_request.json"),
        "outputs_dir": str(selected_output),
        "study_model": study_model,
        "publication_intent": publication_intent,
        "transform_ledger": transform_ledger,
        "journal_profile": get_publication_profile(
            publication_intent["target_profile_id"]
        ),
        "column_confirmations": selected_column_confirmations,
        "plot_options": {
            "output": str(selected_output),
            "exports": selected_exports,
            "render_options": selected_render_options,
            "series_order": series_order,
            "replicate_mode": selected_replicate_mode,
            **(
                {"template": selected_template} if selected_template is not None else {}
            ),
        },
    }
    (project_dir / "plot_request.json").write_text(
        json.dumps(json_safe(plot_request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        studio_payload = studio_preparer(project_dir)
    except Exception as exc:
        manifest["studio"] = {
            "kind": "sciplot_studio_document",
            "engine": "veusz",
            "status": "blocked",
            "state": str(getattr(exc, "state", "needs_rule_repair")),
            "reason_code": str(
                getattr(exc, "reason_code", "studio_preparation_failed")
            ),
            "error": str(exc),
        }
    else:
        if isinstance(studio_payload.get("studio"), dict):
            manifest["studio"] = studio_payload["studio"]
        prepared_request = _read_json_if_exists(project_dir / "plot_request.json")
        if isinstance(prepared_request, dict):
            for key in (
                "study_model",
                "publication_intent",
                "transform_ledger",
            ):
                if isinstance(prepared_request.get(key), dict):
                    manifest[key] = prepared_request[key]
            sync_figure_plan_projection(manifest, prepared_request)
            intent = prepared_request.get("publication_intent")
            if isinstance(intent, dict) and isinstance(
                intent.get("target_profile_id"), str
            ):
                manifest["journal_profile"] = get_publication_profile(
                    intent["target_profile_id"]
                )
    launcher_contract = converge_intake_project_launchers(
        project_dir,
        update_manifests=False,
    )
    _apply_launcher_contract_to_manifest(
        manifest,
        contract=launcher_contract,
    )
    commit_intake_project_manifest(
        project_dir,
        manifest,
        mirror_path=project_dir / f"{project_slug}.sciplot.json",
    )
    zip_path = output_root / f"{project_slug}.zip"
    _write_zip(project_dir, zip_path)
    return {
        **manifest,
        "project_dir": str(project_dir),
        "zip_path": str(zip_path),
        "download_name": zip_path.name,
    }
