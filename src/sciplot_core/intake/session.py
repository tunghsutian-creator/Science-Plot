"""Initial source-recognition session and option normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import reserve_unique_file, slug
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic import (
    classify_source,
    is_rheology_frequency_comparison_dir,
    is_rheology_temperature_comparison_dir,
    tensile_export_csv_files,
    tensile_export_sample_name,
)
from sciplot_core.request_contract import normalize_exports, normalize_render_options

from .catalog import _catalog_item, _catalog_item_for_rule
from .config import _COLUMN_ROLES, _COLUMN_TYPES, _DEFAULT_OUTPUT_ROOT, _REPLICATE_MODES
from .table_preview import (
    _duplicate_source_warnings,
    _file_payload,
    _rheology_comparison_files,
    _table_files,
    _tensile_export_dirs,
    _torque_files,
)


def _group_payload(sample: str, files: list[Path]) -> dict[str, Any]:
    return {"sample": sample, "files": [_file_payload(path) for path in files]}


def _session_path(output_root: Path, project_name: str) -> Path:
    sessions_dir = output_root / "sessions"
    return reserve_unique_file(sessions_dir, f"{slug(project_name)}.json")


def _session_project_name(source: Path, experiment_label: str) -> str:
    return slug(f"{source.name}_{experiment_label}")


def prepare_intake_session(
    input_path: str | Path,
    *,
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    requested_rule_id: str | None = None,
    allow_pending_rule_review: bool = False,
) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    if not source.exists():
        raise ValueError(f"Input path does not exist: {source}")
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    tensile_dirs = _tensile_export_dirs(source)
    temperature_files = (
        _rheology_comparison_files(source)
        if is_rheology_temperature_comparison_dir(source)
        else []
    )
    frequency_files = (
        _rheology_comparison_files(source)
        if not temperature_files and is_rheology_frequency_comparison_dir(source)
        else []
    )
    torque_files = _torque_files(source)
    semantic: dict[str, Any] | None = None
    selected_rule_id = str(requested_rule_id or "").strip() or None

    if selected_rule_id:
        selected_rule = get_rule(selected_rule_id)
        pending_rule_review = selected_rule.fixture_status != "ready"
        if pending_rule_review and not allow_pending_rule_review:
            raise ValueError(
                f"Material rule `{selected_rule.rule_id}` is not ready for "
                "production use; an explicit rule plus template is required "
                "for a non-ready Studio review."
            )
        matched = _catalog_item_for_rule(selected_rule.rule_id)
        if matched is None:
            raise ValueError(
                f"Material rule `{selected_rule.rule_id}` is not available in the intake catalog."
            )
        semantic = classify_source(source, requested_rule_id=selected_rule.rule_id)
        data_type, experiment = matched
        data_type_id = str(data_type["id"])
        experiment_type_id = str(experiment["id"])
        rule_id = selected_rule.rule_id
        reason = (
            f"Explicit pending material rule `{selected_rule.rule_id}` selected "
            "for a non-ready Studio review."
            if pending_rule_review
            else f"Explicit material rule `{selected_rule.rule_id}` selected by "
            "the user or an assistant."
        )
        confidence = 0.0 if pending_rule_review else 100.0
        if selected_rule.rule_id == "tensile_curve" and tensile_dirs:
            groups = [
                _group_payload(
                    tensile_export_sample_name(path),
                    tensile_export_csv_files(path),
                )
                for path in tensile_dirs
            ]
        else:
            files = (
                _rheology_comparison_files(source)
                if selected_rule.semantic_family.startswith("rheology_")
                else _table_files(source)
            )
            groups = (
                [_group_payload(path.stem, [path]) for path in files] if files else []
            )
    elif tensile_dirs:
        data_type_id = "mechanical"
        experiment_type_id = "tensile_curve"
        rule_id = "tensile_curve"
        reason = "Detected tensile export directories and mapped each export folder to one sample group."
        confidence = 98.0
        groups = [
            _group_payload(
                tensile_export_sample_name(path),
                tensile_export_csv_files(path),
            )
            for path in tensile_dirs
        ]
    elif frequency_files:
        semantic = classify_source(source, requested_rule_id="rheology_frequency_sweep")
        data_type_id = "rheology_dma"
        experiment_type_id = "rheology_frequency_sweep"
        rule_id = "rheology_frequency_sweep"
        reason = (
            "Detected frequency-sweep exports and mapped each file to one sample group."
        )
        confidence = 98.0
        groups = [_group_payload(path.stem, [path]) for path in frequency_files]
    elif temperature_files:
        semantic = classify_source(
            source, requested_rule_id="rheology_temperature_sweep"
        )
        data_type_id = "rheology_dma"
        experiment_type_id = "rheology_temperature_sweep"
        rule_id = "rheology_temperature_sweep"
        reason = "Detected temperature-sweep exports and mapped each file to one sample group."
        confidence = 98.0
        groups = [_group_payload(path.stem, [path]) for path in temperature_files]
    elif torque_files:
        data_type_id = "mechanical"
        experiment_type_id = "torque_curve"
        rule_id = "torque_curve"
        reason = "Detected torque text exports with a Screw Torque column."
        confidence = 96.0
        groups = [_group_payload(path.stem, [path]) for path in torque_files]
    else:
        semantic = classify_source(source)
        matched = _catalog_item_for_rule(str(semantic.get("rule_id") or ""))
        if matched is None:
            data_type_id = "unknown"
            experiment_type_id = "unknown"
            rule_id = None
        else:
            data_type, experiment = matched
            data_type_id = str(data_type["id"])
            experiment_type_id = str(experiment["id"])
            rule_id = str(experiment.get("rule_id") or "") or None
        reason = str(semantic.get("reason") or "No specific material rule matched.")
        confidence = float(semantic.get("confidence") or 0.0)
        files = (
            _rheology_comparison_files(source)
            if str(semantic.get("semantic_family") or "").startswith("rheology_")
            else _table_files(source)
        )
        groups = [_group_payload(path.stem, [path]) for path in files] if files else []

    warnings = _duplicate_source_warnings(groups)
    data_type, experiment = _catalog_item(data_type_id, experiment_type_id)
    project_name = _session_project_name(source, str(experiment["label"]))
    path = _session_path(output_root, project_name)
    payload = {
        "kind": "sciplot_intake_session",
        "version": 1,
        "created_at": utc_now_iso(),
        "session_id": path.stem,
        "session_path": str(path),
        "input_path": str(source),
        "output_root": str(output_root),
        "project_name": project_name,
        "data_type_id": data_type_id,
        "data_type_label": data_type["label"],
        "experiment_type_id": experiment_type_id,
        "experiment_label": experiment["label"],
        "rule_id": rule_id,
        "confidence": confidence,
        "reason": reason,
        "groups": groups,
        "warnings": warnings,
        "semantic": semantic,
        "pending_rule_review": bool(
            selected_rule_id and get_rule(selected_rule_id).fixture_status != "ready"
        ),
    }
    try:
        path.write_text(
            json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return payload


def _resolve_plot_output(
    plot_output: object, *, project_dir: Path, default_output: Path
) -> Path:
    if plot_output is None or str(plot_output).strip() == "":
        return default_output
    output_path = Path(str(plot_output).strip()).expanduser()
    if not output_path.is_absolute():
        output_path = project_dir / output_path
    return output_path


def _selected_exports(exports: object) -> list[str]:
    return normalize_exports(exports)


def _selected_render_options(
    render_options: object,
    *,
    template: str | None = None,
) -> dict[str, Any]:
    return normalize_render_options(render_options, template=template)


def _experiment_template(experiment: dict[str, Any]) -> str | None:
    template = experiment.get("template")
    return (
        str(template).strip()
        if isinstance(template, str) and template.strip()
        else None
    )


def _experiment_render_options(experiment: dict[str, Any]) -> dict[str, Any]:
    options = experiment.get("render_options")
    return dict(options) if isinstance(options, dict) else {}


def _selected_column_confirmations(
    column_confirmations: object,
) -> list[dict[str, Any]]:
    if not isinstance(column_confirmations, list | tuple):
        return []
    selected: list[dict[str, Any]] = []
    for item in column_confirmations:
        if not isinstance(item, dict):
            continue
        columns: list[dict[str, Any]] = []
        for column in item.get("columns", []):
            if not isinstance(column, dict):
                continue
            try:
                column_index = int(column.get("index"))
            except (TypeError, ValueError):
                continue
            confirmed_type = str(
                column.get("confirmed_type") or column.get("type") or "auto"
            ).strip()
            role = str(column.get("role") or "auto").strip()
            columns.append(
                {
                    "index": column_index,
                    "name": str(column.get("name") or f"Column {column_index + 1}"),
                    "inferred_type": str(column.get("inferred_type") or "auto"),
                    "confirmed_type": confirmed_type
                    if confirmed_type in _COLUMN_TYPES
                    else "auto",
                    "role": role if role in _COLUMN_ROLES else "auto",
                }
            )
        if not columns:
            continue
        selected.append(
            {
                "sample": str(item.get("sample") or ""),
                "file_name": str(item.get("file_name") or item.get("name") or ""),
                "source_path": str(item.get("source_path") or ""),
                "sheet": str(item.get("sheet") or "") or None,
                "columns": columns,
            }
        )
    return selected


def _selected_replicate_mode(replicate_mode: object) -> str:
    value = str(replicate_mode or "mean").strip().casefold()
    aliases = {
        "average": "mean",
        "avg": "mean",
        "best": "representative",
        "all": "individual",
    }
    value = aliases.get(value, value)
    return value if value in _REPLICATE_MODES else "mean"
