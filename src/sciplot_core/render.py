from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sciplot_core._bootstrap import ensure_vendored_core
from sciplot_core._utils import json_safe
from sciplot_core.ingest import normalized_source
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    normalize_export_formats,
)
from sciplot_core.semantic import classify_source
from sciplot_core.split import (
    SUPPORTED_SPLIT_TEMPLATES,
    build_split_plan,
    normalize_split_policy,
)
from sciplot_core.style_contract import validate_veusz_template_id
from sciplot_core.terminal_request import project_terminal_render_request
from sciplot_core.veusz_runtime import veusz_worker_environment

ensure_vendored_core()

from src.data_loader import load_curve_table  # noqa: E402
from src.rendering.options import validate_template_name  # noqa: E402
from src.rendering.recommendation import inspect_input_file  # noqa: E402
from src.rendering.series_order import (  # noqa: E402
    filter_curve_series,
    reorder_curve_series,
    unknown_series_order_labels,
)

_EXPORT_FORMATS = {
    "pdf": ("pdf", None, ""),
    "svg": ("svg", None, ""),
    "png_300": ("png", 300, "_300dpi"),
    "png_600": ("png", 600, "_600dpi"),
    "tiff_300": ("tiff", 300, "_300dpi"),
}

DEFAULT_EXPORT_FORMATS = DEFAULT_EXPORT_FORMATS_POLICY
DEFAULT_RENDER_ENGINE = "veusz"

_GENERIC_PRESENTATION_WARNING_MARKERS = (
    "axis label",
    "axis labels",
    "box plot",
    "boxplot",
    "categories",
    "category labels",
    "crowd",
    "density plot",
    "heatmap",
    "legend",
    "many groups",
    "matrix view",
    "shrink",
    "violin",
    "wrap",
)
_GENERIC_DATA_RISK_WARNING_MARKERS = (
    "duplicate",
    "empty",
    "failed",
    "inconsistent",
    "invalid",
    "missing",
    "nan",
    "negative",
    "non-finite",
    "nonfinite",
    "out of range",
    "zero",
)
_GENERIC_PRESENTATION_ONLY_MISSING_PHRASES = (
    "missing axis label",
    "missing axis labels",
    "missing category label",
    "missing category labels",
)


def _material_rule_recommendation(semantics: dict[str, Any]) -> dict[str, Any]:
    axis_plan = (
        semantics.get("axis_plan")
        if isinstance(semantics.get("axis_plan"), dict)
        else {}
    )
    x_axis = axis_plan.get("x") if isinstance(axis_plan.get("x"), dict) else {}
    y_axis = axis_plan.get("y") if isinstance(axis_plan.get("y"), dict) else {}
    semantic_family = str(semantics.get("semantic_family") or "unknown")
    template = str(semantics.get("template") or "curve")
    confidence = float(semantics.get("confidence") or 0.0)
    reason = str(
        semantics.get("reason") or f"Matched SciPlot material rule `{semantic_family}`."
    )
    return {
        "template_id": template,
        "score": confidence,
        "why_hard_match": [reason],
        "why_soft_prior": [
            "SciPlot material semantics take precedence over generic table-shape inspection."
        ],
        "inferred_mapping": {
            "x": x_axis.get("canonical_label") or "x",
            "y": y_axis.get("canonical_label") or "y",
        },
        "optional_enhancements": [],
        "preview_config_summary": {
            "template": template,
            **dict(semantics.get("render_options") or {}),
            "experiment_family": semantics.get("recommended_recipe"),
            "recommended_action": "add_as_plot_source",
            "model": semantic_family,
        },
        "experiment_family": semantics.get("recommended_recipe"),
        "role_hints": [
            f"x:{x_axis.get('canonical_label') or 'x'}",
            f"y:{y_axis.get('canonical_label') or 'y'}",
        ],
        "recommendation_reason": reason,
        "recommended_action": "add_as_plot_source",
        "default_render_overrides": dict(semantics.get("render_options") or {}),
        "rank": 1,
        "reason": reason,
        "suitability_hint": "Authoritative SciPlot material-rule match.",
        "score_gap_to_top": 0.0,
        "canonical_id": template,
        "role": "canonical",
        "lifecycle_policy": "canonical",
        "implementation_id": template,
        "recommendation_source": "sciplot_material_rule",
    }


def _generic_warning_is_superseded_by_ready_rule(message: str) -> bool:
    normalized = " ".join(str(message).strip().lower().split())
    if not normalized:
        return True
    # Remove only the known presentation-only use of "missing" before looking
    # for data-risk words. This keeps "Missing axis labels" suppressible while
    # preserving mixed warnings such as "Missing axis labels and values".
    risk_text = normalized
    for phrase in _GENERIC_PRESENTATION_ONLY_MISSING_PHRASES:
        risk_text = risk_text.replace(phrase, "")
    if any(marker in risk_text for marker in _GENERIC_DATA_RISK_WARNING_MARKERS):
        return False
    if any(marker in normalized for marker in _GENERIC_PRESENTATION_WARNING_MARKERS):
        return True
    # Unknown generic warnings are review input, not safe to suppress.
    return False


def _resolve_ready_rule_inspection_warnings(
    warnings: list[Any],
    *,
    rule_id: str,
) -> tuple[list[str], list[dict[str, str]]]:
    user_warnings: list[str] = []
    provenance: list[dict[str, str]] = []
    for raw_warning in warnings:
        message = str(raw_warning).strip()
        if not message:
            continue
        superseded = _generic_warning_is_superseded_by_ready_rule(message)
        disposition = (
            "superseded_by_ready_rule" if superseded else "preserved_for_review"
        )
        provenance.append(
            {
                "message": message,
                "source": "generic_table_inspection",
                "disposition": disposition,
                "resolved_by": f"sciplot_material_rule:{rule_id}" if superseded else "",
            }
        )
        if not superseded:
            user_warnings.append(f"[generic_table_inspection] {message}")
    return user_warnings, provenance


def _semantic_only_inspection_payload(
    source: Path,
    semantics: dict[str, Any],
    *,
    vendor_error: Exception,
) -> dict[str, Any]:
    candidate = _material_rule_recommendation(semantics)
    candidate.update(
        {
            "score": 0.0,
            "recommended_action": "inspect_source",
            "lifecycle_policy": "candidate_only",
            "recommendation_source": "sciplot_material_rule_candidate",
            "suitability_hint": (
                "Unverified SciPlot material-rule candidate; not eligible for "
                "automatic rendering."
            ),
        }
    )
    semantic_family = str(semantics.get("semantic_family") or "unknown")
    reason = str(
        semantics.get("reason") or f"Matched SciPlot material rule `{semantic_family}`."
    )
    rule_id = str(semantics.get("rule_id") or semantic_family)
    warning = (
        "Generic table inspection could not read this source, so SciPlot cannot "
        f"treat material rule `{rule_id}` as authoritative: {vendor_error}"
    )
    return {
        "source": str(source),
        "model": semantic_family,
        "model_label": f"{semantic_family} ({rule_id}; unverified candidate)",
        # Keep executable recommendation surfaces empty.  Consumers such as
        # ``render --auto`` intentionally select only from this list.
        "recommendations": [],
        "canonical_templates": [],
        "advanced_templates": [],
        "unverified_candidate": candidate,
        "recommendation_confidence": 0.0,
        "recommendation_summary": f"Unverified candidate only. {reason}",
        "warnings": [f"[generic_table_inspection] {warning}"],
        "inspection_resolution": {
            "status": "generic_inspection_failed",
            "authoritative_source": None,
            "candidate_source": "sciplot_material_rule",
            "candidate_rule_id": rule_id,
            "candidate_model": semantic_family,
            "candidate_template": semantics.get("template"),
            "generic_inspection_status": "failed",
        },
        "inspection_warning_provenance": [
            {
                "message": warning,
                "source": "generic_table_inspection",
                "disposition": "preserved_for_review",
                "resolved_by": "",
            }
        ],
        "vendor_inspection_error": str(vendor_error),
        "sciplot_semantics": semantics,
    }


def inspect_payload(input_path: Path, *, sheet: str | int = 0) -> dict[str, Any]:
    with normalized_source(input_path) as source:
        if source.is_file() and source.stat().st_size <= 0:
            raise ValueError(f"Input file is empty: {source}")
        try:
            payload = json_safe(inspect_input_file(source, sheet))
        except (IsADirectoryError, TypeError, ValueError) as exc:
            # A non-empty file that the generic reader cannot parse must fail
            # closed.  Classifying it after the failure lets path keywords such
            # as ``dma`` or ``ftir`` turn arbitrary bytes into an apparently
            # authoritative ready-rule result.
            if source.is_file():
                raise
            semantics = json_safe(classify_source(source, sheet=sheet))
            if semantics.get("production_status") != "ready" or not semantics.get(
                "rule_id"
            ):
                raise
            return _semantic_only_inspection_payload(
                source, semantics, vendor_error=exc
            )
        semantics = json_safe(
            classify_source(source, sheet=sheet, vendor_inspection=payload)
        )
        payload["sciplot_semantics"] = semantics
        vendor_model = str(payload.get("model") or "")
        semantic_family = str(semantics.get("semantic_family") or "")
        rule_id = str(semantics.get("rule_id") or "")
        vendor_recommendations = (
            payload.get("recommendations")
            if isinstance(payload.get("recommendations"), list)
            else []
        )
        vendor_template = (
            str(vendor_recommendations[0].get("template_id") or "")
            if vendor_recommendations
            else ""
        )
        semantic_template = str(semantics.get("template") or "")
        ready_rule_authority = semantics.get("production_status") == "ready" and bool(
            rule_id
        )
        semantic_override = ready_rule_authority and (
            vendor_model != semantic_family or vendor_template != semantic_template
        )
        if semantic_override:
            vendor_advanced = (
                payload.get("advanced_templates")
                if isinstance(payload.get("advanced_templates"), list)
                else []
            )
            confidence = float(semantics.get("confidence") or 0.0)
            reason = str(
                semantics.get("reason")
                or f"Matched SciPlot material rule `{semantic_family}`."
            )
            recommendation = _material_rule_recommendation(semantics)
            payload["vendor_inspection_model"] = vendor_model
            payload["vendor_recommendations"] = vendor_recommendations
            payload["vendor_advanced_templates"] = vendor_advanced
            payload["model"] = semantic_family
            payload["model_label"] = (
                f"{semantic_family} ({semantics.get('rule_id') or semantic_family})"
            )
            payload["recommendations"] = [recommendation]
            payload["canonical_templates"] = [recommendation]
            payload["advanced_templates"] = []
            payload["recommendation_confidence"] = confidence
            payload["recommendation_summary"] = reason
        if ready_rule_authority:
            warnings = (
                payload.get("warnings")
                if isinstance(payload.get("warnings"), list)
                else []
            )
            user_warnings, warning_provenance = _resolve_ready_rule_inspection_warnings(
                warnings,
                rule_id=rule_id,
            )
            payload["warnings"] = user_warnings
            payload["inspection_resolution"] = {
                "status": "ready_rule_authoritative",
                "authoritative_source": "sciplot_material_rule",
                "rule_id": rule_id,
                "selected_model": semantic_family,
                "selected_template": semantic_template,
                "generic_inspection_status": (
                    "superseded" if semantic_override else "confirmed"
                ),
                "generic_model": vendor_model or "unknown",
                "generic_template": vendor_template or "unknown",
            }
            payload["inspection_warning_provenance"] = warning_provenance
    return payload


def _normalize_export_formats(
    export_formats: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    return normalize_export_formats(export_formats, default=DEFAULT_EXPORT_FORMATS)


def _export_path(filename: str, output_dir: Path, export_format: str) -> Path:
    target_format, _dpi, suffix = _EXPORT_FORMATS[export_format]
    base = Path(filename).with_suffix("").name
    if target_format == "pdf":
        return output_dir / f"{base}.pdf"
    extension = "tiff" if target_format == "tiff" else target_format
    return output_dir / f"{base}{suffix}.{extension}"


def _series_labels_for_split(
    source: Path, sheet: str | int, options: dict[str, Any]
) -> list[str]:
    series_list = load_curve_table(source, sheet_name=sheet)
    available = [series.sample for series in series_list]
    series_include = options.get("series_include")
    unknown_include = unknown_series_order_labels(available, series_include)
    if unknown_include:
        raise ValueError(
            "series_include contains unknown series labels: "
            + ", ".join(unknown_include)
        )
    selected = filter_curve_series(series_list, series_include)
    if not selected and series_include:
        raise ValueError("series_include did not match any series.")
    selected_labels = [series.sample for series in selected]
    series_order = options.get("series_order")
    unknown_order = unknown_series_order_labels(selected_labels, series_order)
    if unknown_order:
        raise ValueError(
            "series_order contains unknown series labels: " + ", ".join(unknown_order)
        )
    ordered = reorder_curve_series(selected, series_order)
    return [series.sample for series in ordered]


def _veusz_worker_env() -> dict[str, str]:
    return veusz_worker_environment()


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _veusz_target_base(
    source: Path, template: str, *, panel_index: int | None = None
) -> str:
    base = f"{source.stem}_{template}"
    if panel_index is not None:
        base = f"{base}_part{panel_index:02d}"
    return base


def _render_studio_exports(
    request_path: Path, export_formats: tuple[str, ...]
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "export",
        str(request_path),
        "--formats",
        ",".join(export_formats),
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        env=_veusz_worker_env(),
    )
    return json.loads(result.stdout)


def _veusz_layout_report(
    *,
    template: str,
    spec: dict[str, Any],
    document: Path,
    outputs: list[Path],
    split_panel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    size = spec.get("size_mm") if isinstance(spec.get("size_mm"), list) else []
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    y_axis = axes.get("y") if isinstance(axes.get("y"), dict) else {}
    summary: dict[str, Any] = {
        "kind": "sciplot_veusz_layout_summary",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template,
        "document": str(document),
        "outputs": [str(path) for path in outputs],
        "series_count": len(series),
        "requested_size_mm": size,
        "figure_size_mm": size,
        "axes": [
            {
                "x_label": x_axis.get("label"),
                "y_label": y_axis.get("label"),
                "x_bounds": [x_axis.get("min"), x_axis.get("max")],
                "y_bounds": [y_axis.get("min"), y_axis.get("max")],
                "x_ticks": x_axis.get("ticks") or [],
                "y_ticks": y_axis.get("ticks") or [],
                "legend": spec.get("legend", {}),
            }
        ],
    }
    categorical = (
        spec.get("categorical") if isinstance(spec.get("categorical"), dict) else None
    )
    if categorical is not None:
        summary["categorical_replicates"] = {
            "presentation_kind": categorical.get("presentation_kind"),
            "summary_statistic": categorical.get("summary_statistic"),
            "native_veusz_boxplot": categorical.get("native_veusz_boxplot"),
            "raw_values_preserved": categorical.get("raw_values_preserved"),
            "raw_replicate_count": categorical.get("raw_replicate_count"),
            "group_count": len(categorical.get("groups") or []),
            "insufficient_replicate_groups": categorical.get(
                "insufficient_replicate_groups"
            )
            or [],
        }
    if split_panel is not None:
        summary["split_panel"] = split_panel
    issues: list[dict[str, Any]] = [
        item for item in spec.get("layout_issues", []) if isinstance(item, dict)
    ]
    try:
        from sciplot_core.contract import load_plot_contract, qa_profile

        contract = load_plot_contract()
        alignment_profile = qa_profile("alignment")
        tolerance_mm = float(alignment_profile.get("frame_tolerance_mm", 0.05))
        expected_margins = {
            "left": float(contract.global_frame.left_margin_mm),
            "right": float(contract.global_frame.right_margin_mm),
            "bottom": float(contract.global_frame.bottom_margin_mm),
            "top": float(contract.global_frame.top_margin_mm),
        }
        style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
        actual_margins = (
            style.get("margins_mm") if isinstance(style.get("margins_mm"), dict) else {}
        )
        margin_errors = {
            side: abs(float(actual_margins.get(side, float("inf"))) - expected)
            for side, expected in expected_margins.items()
        }
        frame_alignment = {
            "mode": "fixed_mm",
            "status": (
                "aligned"
                if all(error <= tolerance_mm for error in margin_errors.values())
                else "misaligned"
            ),
            "expected_margins_mm": expected_margins,
            "actual_margins_mm": actual_margins,
            "margin_error_mm": margin_errors,
            "tolerance_mm": tolerance_mm,
            "outside_legend_allowed": False,
        }
        summary["frame_alignment"] = frame_alignment
        if frame_alignment["status"] != "aligned":
            issues.append(
                {
                    "id": "fixed_publication_frame_misaligned",
                    "severity": "critical",
                    "message": "The Veusz graph margins drifted from the fixed publication frame.",
                    "margin_error_mm": margin_errors,
                    "tolerance_mm": tolerance_mm,
                }
            )
        legend = spec.get("legend") if isinstance(spec.get("legend"), dict) else {}
        if str(legend.get("mode") or "").strip().casefold() in {
            "outside",
            "outside_right",
        }:
            issues.append(
                {
                    "id": "outside_legend_forbidden",
                    "severity": "critical",
                    "message": "Outside legends are disabled because they break the fixed publication frame.",
                }
            )
    except (TypeError, ValueError):
        issues.append(
            {
                "id": "fixed_publication_frame_unverifiable",
                "severity": "critical",
                "message": "The generated Veusz spec did not expose verifiable physical graph margins.",
            }
        )
    if (
        split_panel is None
        and template in SUPPORTED_SPLIT_TEMPLATES
        and len(series) >= 24
        and len(size) >= 2
        and float(size[1]) >= 100.0
    ):
        issues.append(
            {
                "id": "stack_peak_too_small",
                "severity": "warning",
                "message": "Dense stacked Veusz output should be split into readable panels.",
            }
        )
    return {
        "kind": "sciplot_veusz_qa_report",
        "engine": "veusz",
        "issues": issues,
        "autofixes_applied": [
            str(item)
            for item in spec.get("autofixes_applied", [])
            if isinstance(item, str)
        ],
        "layout_summary": summary,
    }


def _copy_veusz_exports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    output_base: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    outputs: list[Path] = []
    export_records: list[dict[str, Any]] = []
    raw_exports = payload.get("exports")
    if not isinstance(raw_exports, list):
        raise RuntimeError("Veusz export response must contain an `exports` list.")
    for index, item in enumerate(raw_exports):
        if not isinstance(item, dict):
            raise RuntimeError(f"Veusz export record {index} is not an object.")
        source_value = item.get("path")
        fmt = str(item.get("format") or "").strip().lower()
        if not isinstance(source_value, str) or not source_value.strip():
            raise RuntimeError(f"Veusz export record {index} has no artifact path.")
        if fmt not in _EXPORT_FORMATS:
            raise RuntimeError(
                f"Veusz export record {index} has unsupported format `{fmt or 'missing'}`."
            )
        source = Path(source_value).expanduser()
        if not source.is_file() or source.stat().st_size <= 0:
            raise RuntimeError(
                f"Veusz reported a missing or empty `{fmt}` export: {source}"
            )
        destination = _export_path(f"{output_base}.pdf", output_dir, fmt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record = {
            "path": str(destination),
            "format": fmt,
            "dpi": item.get("dpi"),
            "source": str(source),
            "exists": destination.exists(),
            "size_bytes": destination.stat().st_size if destination.exists() else 0,
        }
        outputs.append(destination)
        export_records.append(record)
    return outputs, export_records


def _validate_export_records(
    records: list[dict[str, Any]], *, requested: tuple[str, ...]
) -> None:
    received = tuple(str(record.get("format") or "") for record in records)
    if Counter(received) == Counter(requested):
        return
    missing = list((Counter(requested) - Counter(received)).elements())
    unexpected = list((Counter(received) - Counter(requested)).elements())
    raise RuntimeError(
        "Veusz export response does not match the requested format set: "
        f"missing={missing or 'none'}, unexpected={unexpected or 'none'}."
    )


def _remove_stale_render_exports(
    output_dir: Path,
    *,
    source_stem: str,
    template: str,
    keep: set[Path] | None = None,
) -> None:
    base = re.escape(f"{source_stem}_{template}")
    generated_name = re.compile(
        rf"^{base}(?:_part\d{{2}})?(?:_(?:300|600)dpi)?\.(?:pdf|svg|png|tiff)$",
        flags=re.IGNORECASE,
    )
    if not output_dir.is_dir():
        return
    retained = {path.expanduser().resolve() for path in (keep or set())}
    for path in output_dir.iterdir():
        if (
            path.is_file()
            and generated_name.fullmatch(path.name)
            and path.resolve() not in retained
        ):
            path.unlink()


def _cleanup_worker_exports(panel_dir: Path) -> None:
    for path in (panel_dir / "studio" / "exports", panel_dir / "runs"):
        if path.exists():
            shutil.rmtree(path)


def _render_veusz_panel(
    source: Path,
    *,
    template: str,
    output_dir: Path,
    panel_dir: Path,
    output_base: str,
    options: dict[str, Any],
    export_formats: tuple[str, ...],
    split_panel: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
) -> tuple[
    list[Path],
    list[dict[str, Any]],
    dict[str, Any],
    Path,
    Path,
    dict[str, Any],
]:
    panel_dir.mkdir(parents=True, exist_ok=True)
    terminal_request = project_terminal_render_request(
        template=template,
        render_options=options,
        request_context=request_context,
    )
    request = {
        "input": str(source.resolve()),
        "output": str(output_dir),
        "exports": list(export_formats),
        **terminal_request,
    }
    request_path = panel_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    payload = _render_studio_exports(request_path, export_formats)
    outputs, export_records = _copy_veusz_exports(
        payload, output_dir=output_dir, output_base=output_base
    )
    _validate_export_records(export_records, requested=export_formats)
    document = Path(str(payload["document"]))
    spec = Path(
        str(payload.get("studio", {}).get("spec") or document.with_suffix(".spec.json"))
    )
    spec_payload = _read_json_if_exists(spec)
    report = _veusz_layout_report(
        template=template,
        spec=spec_payload,
        document=document,
        outputs=outputs,
        split_panel=split_panel,
    )
    _cleanup_worker_exports(panel_dir)
    return outputs, export_records, report, document, spec, terminal_request


def _render_to_dir_veusz(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    export_formats: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = dict(options or {})
    normalized_exports = _normalize_export_formats(export_formats)
    normalized_split_policy = normalize_split_policy(split_policy)
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_root = output_dir / "_veusz"
    if worker_root.exists():
        shutil.rmtree(worker_root)
    worker_root.mkdir(parents=True, exist_ok=True)

    all_outputs: list[Path] = []
    all_exports: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    documents: list[str] = []
    specs: list[str] = []
    terminal_requests: list[dict[str, Any]] = []
    with normalized_source(input_path) as source:
        split_plan: dict[str, Any] | None = None
        panels: list[tuple[int | None, list[str] | None]]
        if normalized_split_policy is None:
            panels = [(None, None)]
        else:
            labels = _series_labels_for_split(source, sheet, options)
            split_plan = build_split_plan(labels, policy=normalized_split_policy)
            chunks = [list(chunk["series"]) for chunk in split_plan["chunks"]]
            panels = [(index, chunk) for index, chunk in enumerate(chunks, start=1)]

        for panel_index, chunk in panels:
            panel_options = dict(options)
            split_panel: dict[str, Any] | None = None
            if chunk is not None and panel_index is not None:
                panel_options["series_include"] = list(chunk)
                panel_options["series_order"] = list(chunk)
                split_panel = {
                    "index": panel_index,
                    "count": len(panels),
                    "series": list(chunk),
                    "policy": dict(normalized_split_policy or {}),
                }
            output_base = _veusz_target_base(source, template, panel_index=panel_index)
            (
                outputs,
                export_records,
                report,
                document,
                spec,
                terminal_request,
            ) = _render_veusz_panel(
                source,
                template=template,
                output_dir=output_dir,
                panel_dir=worker_root
                / (f"panel_{panel_index:02d}" if panel_index else "single"),
                output_base=output_base,
                options=panel_options,
                export_formats=normalized_exports,
                split_panel=split_panel,
                request_context=request_context,
            )
            all_outputs.extend(outputs)
            all_exports.extend(export_records)
            reports.append(report)
            documents.append(str(document))
            specs.append(str(spec))
            terminal_requests.append(terminal_request)

        _remove_stale_render_exports(
            output_dir,
            source_stem=source.stem,
            template=template,
            keep=set(all_outputs),
        )

    payload = {
        "kind": "sciplot_render_result",
        "template": template,
        "input": str(input_path),
        "sheet": sheet,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(normalized_exports),
        "exports": all_exports,
        "outputs": [str(path) for path in all_outputs],
        "qa_reports": reports,
        "veusz_documents": documents,
        "veusz_specs": specs,
        "terminal_render_requests": terminal_requests,
    }
    if split_plan is not None:
        payload["split_plan"] = json_safe(split_plan)
    return payload


def render_to_dir(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    export_formats: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = validate_veusz_template_id(validate_template_name(template))
    return _render_to_dir_veusz(
        input_path,
        template=template,
        output_dir=output_dir,
        sheet=sheet,
        options=options,
        export_formats=export_formats,
        split_policy=split_policy,
        request_context=request_context,
    )


__all__ = [
    "DEFAULT_EXPORT_FORMATS",
    "DEFAULT_RENDER_ENGINE",
    "inspect_payload",
    "json_safe",
    "render_to_dir",
]
