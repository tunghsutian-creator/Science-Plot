"""Apply explicit Studio request overrides and write request snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.project_manifest import (
    edit_intake_project_manifest,
)
from sciplot_core.materials_rules import (
    get_rule,
    resolve_rule_template,
    semantic_payload_from_rule,
)
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    project_selected_presentation_to_request,
)
from sciplot_core.study_model import study_model_from_request
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)

from sciplot_core.studio_core.runtime import (
    upstream_status,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)

from sciplot_core.studio_core.context import (
    _normalize_optional_string,
)

from sciplot_core.studio_core.source_snapshots import (
    _excel_sheet_name,
)

from sciplot_core.studio_core.series_request import (
    _read_source_frames,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_reference,
)
from sciplot_core.studio_core.request_paths import _resolve_request_input


def _apply_studio_request_overrides(
    project_dir: Path,
    *,
    request_path: Path,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> None:
    selected_rule_id = _normalize_optional_string(rule_id)
    selected_rule = get_rule(selected_rule_id) if selected_rule_id else None
    requested_template = _normalize_optional_string(template)
    pending_rule_review = bool(
        selected_rule is not None and selected_rule.fixture_status != "ready"
    )
    if pending_rule_review and not requested_template:
        raise ValueError(
            f"Material rule `{selected_rule.rule_id}` is not ready for "
            "production use; an explicit supported template is required for "
            "a non-ready Studio review."
        )
    selected_rule_payload = (
        semantic_payload_from_rule(
            selected_rule,
            confidence=0.0 if pending_rule_review else 100.0,
            reason=(
                f"Explicit pending material rule `{selected_rule.rule_id}` "
                "selected for a non-ready Studio review."
                if pending_rule_review
                else f"Explicit material rule `{selected_rule.rule_id}` selected "
                "by the user or an assistant."
            ),
        )
        if selected_rule is not None
        else None
    )
    selected_template = (
        resolve_rule_template(selected_rule, requested_template)
        if selected_rule is not None
        else requested_template
    )
    selected_project_name = _normalize_optional_string(project_name)
    if not selected_rule and not selected_template and not selected_project_name:
        return
    if request_path.exists():
        request = _read_json(request_path)
        original_rule_id = str(request.get("rule_id") or "").strip()
        original_template = str(request.get("template") or "").strip()
        if selected_rule is not None:
            request["rule_id"] = selected_rule.rule_id
            request.setdefault("recipe", "auto")
            if pending_rule_review:
                request["pending_rule_review"] = True
            else:
                request.pop("pending_rule_review", None)
            current_options = (
                dict(request.get("render_options"))
                if isinstance(request.get("render_options"), dict)
                else {}
            )
            explicit_key_payload = request.get("explicit_render_option_keys")
            explicit_keys = (
                {
                    str(key)
                    for key in explicit_key_payload
                    if str(key) in current_options
                }
                if isinstance(explicit_key_payload, list | tuple | set)
                else set(current_options)
            )
            explicit_options = {key: current_options[key] for key in explicit_keys}
            current_options = dict(
                (selected_rule_payload or {}).get("render_options") or {}
            )
            current_options.setdefault(
                "x_label_override", selected_rule.x_axis.display_label
            )
            current_options.setdefault(
                "y_label_override", selected_rule.y_axis.display_label
            )
            current_options.update(explicit_options)
            request["render_options"] = current_options
        if selected_template:
            previous_template = str(request.get("template") or "").strip()
            if previous_template != selected_template:
                try:
                    from sciplot_core.contract import load_plot_contract

                    contract = load_plot_contract()
                    previous_defaults = (
                        contract.templates[previous_template].default_options
                        if previous_template in contract.templates
                        else {}
                    )
                    selected_defaults = (
                        contract.templates[selected_template].default_options
                        if selected_template in contract.templates
                        else {}
                    )
                    current_options = (
                        dict(request.get("render_options"))
                        if isinstance(request.get("render_options"), dict)
                        else {}
                    )
                    explicit_key_payload = request.get("explicit_render_option_keys")
                    explicit_keys = (
                        {str(key) for key in explicit_key_payload}
                        if isinstance(explicit_key_payload, list | tuple | set)
                        else set(current_options)
                    )
                    for key, value in previous_defaults.items():
                        if (
                            key not in explicit_keys
                            and current_options.get(key) == value
                        ):
                            current_options.pop(key, None)
                    for key, value in selected_defaults.items():
                        current_options.setdefault(key, value)
                    request["render_options"] = current_options
                except Exception:
                    pass
            request["template"] = selected_template
            request["explicit_template_selection"] = True
        rule_changed = bool(
            selected_rule is not None and selected_rule.rule_id != original_rule_id
        )
        template_changed = bool(
            selected_template and selected_template != original_template
        )
        if rule_changed:
            request.pop("study_model", None)
            request.pop("publication_intent", None)
            request.pop("transform_ledger", None)
            request["study_model"] = study_model_from_request(
                request=request,
                semantic=selected_rule_payload or {},
                input_path=(
                    _resolve_request_input(request, base_dir=request_path.parent)
                    or project_dir
                ),
            )
        if selected_template:
            projected_rule_id = str(request.get("rule_id") or "").strip() or None
            project_selected_presentation_to_request(
                request,
                SelectedPresentationIdentity(
                    rule_id=projected_rule_id,
                    template=selected_template,
                ),
            )
        if rule_changed or template_changed:
            request.pop("resolved_figure_plan", None)
            request.pop("studio_rule_contract_binding", None)
        request_path.write_text(
            json.dumps(json_safe(request), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    with edit_intake_project_manifest(project_dir) as payload:
        if payload is None:
            return
        if selected_project_name:
            payload["project_name"] = selected_project_name
        if selected_template:
            experiment = (
                payload.get("experiment")
                if isinstance(payload.get("experiment"), dict)
                else {}
            )
            experiment["template"] = selected_template
            experiment["chart"] = selected_template
            payload["experiment"] = experiment
            plot_options = (
                payload.get("plot_options")
                if isinstance(payload.get("plot_options"), dict)
                else {}
            )
            plot_options["template"] = selected_template
            payload["plot_options"] = plot_options
        if selected_rule is not None:
            recognition = dict(selected_rule_payload or {})
            if pending_rule_review:
                recognition.update(
                    {
                        "confidence": 0.0,
                        "reason": (
                            f"Explicit pending material rule "
                            f"`{selected_rule.rule_id}` selected for a non-ready "
                            "Studio review."
                        ),
                        "needs_ai_intervention": True,
                        "production_status": "needs_rule_repair",
                        "pending_rule_review": True,
                    }
                )
            else:
                recognition.update(
                    {
                        "confidence": 100.0,
                        "reason": (
                            f"Explicit material rule `{selected_rule.rule_id}` "
                            "selected by the user or an assistant."
                        ),
                        "needs_ai_intervention": False,
                        "production_status": "ready",
                    }
                )
            payload["recognition"] = recognition
            experiment = (
                payload.get("experiment")
                if isinstance(payload.get("experiment"), dict)
                else {}
            )
            experiment["rule_id"] = selected_rule.rule_id
            experiment.setdefault("id", selected_rule.rule_id)
            experiment.setdefault("label", selected_rule.rule_id)
            payload["experiment"] = experiment


def _existing_document_payload(document_path: Path) -> dict[str, Any]:
    spec_reference = _veusz_spec_reference(document_path)
    return {
        "kind": "sciplot_studio_prepare",
        "mode": "vsz",
        "operation_mode": normal_mode_payload(route="studio"),
        "document": str(document_path),
        "studio": {
            "kind": "sciplot_studio_document",
            "engine": "veusz",
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "document": str(document_path),
            "spec": spec_reference["path"],
            "spec_reference": spec_reference,
            "manual_edit_hash": existing_file_sha256(document_path),
            "upstream": upstream_status()["veusz"],
            "operation_mode": normal_mode_payload(route="studio"),
        },
    }


def _write_studio_data_snapshots(
    input_paths: list[Path],
    output_dir: Path,
) -> Path:
    processed_dir = output_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = processed_dir / "studio_export_data.xlsx"
    with pd.ExcelWriter(destination) as writer:
        used_names: set[str] = set()
        frame_index = 0
        for source_index, input_path in enumerate(input_paths, start=1):
            try:
                frames = _read_source_frames(input_path)
            except Exception as exc:
                raise StudioPreparationBlocked(
                    "studio_data_snapshot_failed",
                    f"Studio could not create a data snapshot from {input_path}: {exc}",
                ) from exc
            for label, frame in frames:
                frame_index += 1
                qualified_label = (
                    f"{input_path.stem}_{label}" if len(input_paths) > 1 else label
                )
                sheet_name = _excel_sheet_name(
                    qualified_label,
                    fallback=f"data_{source_index}_{frame_index}",
                    used=used_names,
                )
                frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return destination
