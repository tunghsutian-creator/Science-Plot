"""Run and summarize the representative 3DPA acceptance workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import slug
from sciplot_core.curate import curate_torque_project
from sciplot_core.policy import DEFAULT_FIGURE_SIZE
from sciplot_core.workflow import run_request

from sciplot_core.acceptance.fixtures import (
    DEFAULT_DENSE_SERIES_COUNT,
    DEFAULT_REPRESENTATIVE_COUNT,
)

from sciplot_core.acceptance.three_dpa_sources import (
    _find_ftir_files,
    _find_torque_dir,
    _load_spectra,
    _write_curve_table,
    _build_dense_series,
    _write_request,
)


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(manifest["output"]))
    layout_quality = (
        manifest.get("layout_quality")
        if isinstance(manifest.get("layout_quality"), dict)
        else {}
    )
    delivery = (
        manifest.get("delivery_package")
        if isinstance(manifest.get("delivery_package"), dict)
        else {}
    )
    summaries = (
        layout_quality.get("summaries")
        if isinstance(layout_quality.get("summaries"), list)
        else []
    )
    first_axis: dict[str, Any] = {}
    if summaries:
        axes = summaries[0].get("axes") if isinstance(summaries[0], dict) else []
        if isinstance(axes, list) and axes:
            first_axis = axes[0] if isinstance(axes[0], dict) else {}
    pdf_count = len(list((output_dir / "figures").glob("*.pdf")))
    tiff_count = len(list((output_dir / "figures").glob("*_300dpi.tiff")))
    delivery_dir = (
        Path(str(delivery.get("path")))
        if delivery.get("path")
        else output_dir / "delivery"
    )
    state = "ready"
    if manifest.get("qa", {}).get("status") != "passed":
        state = "needs_rule_repair"
    if layout_quality.get("issue_ids"):
        state = "needs_rule_repair"
    if delivery.get("complete") is not True:
        state = "needs_rule_repair"
    return {
        "state": state,
        "output": str(output_dir),
        "manifest": str(output_dir / "manifest.json"),
        "delivery": str(delivery_dir),
        "delivery_complete": bool(delivery.get("complete")),
        "qa_status": manifest.get("qa", {}).get("status"),
        "render_engine": manifest.get("render_engine"),
        "qa_target": manifest.get("qa_target"),
        "veusz_document_count": len(manifest.get("veusz_documents", [])),
        "veusz_spec_count": len(manifest.get("veusz_specs", [])),
        "layout_issue_ids": layout_quality.get("issue_ids", []),
        "autofixes_applied": layout_quality.get("autofixes_applied", []),
        "auto_split": layout_quality.get("auto_split"),
        "split_plan": layout_quality.get("split_plan"),
        "x_bounds": first_axis.get("x_bounds"),
        "x_ticks": first_axis.get("x_ticks"),
        "legend": first_axis.get("legend"),
        "pdf_count": pdf_count,
        "tiff_300_count": tiff_count,
    }


def _run_acceptance_request(
    *,
    run_root: Path,
    request_name: str,
    input_path: Path,
    render_options: dict[str, Any],
    review_notes: list[str],
) -> dict[str, Any]:
    request_dir = run_root / request_name
    request = {
        "template": "stacked_curve",
        "input": str(input_path.resolve()),
        "output": str((request_dir / "run_001").resolve()),
        "render_options": render_options,
        "review_notes": review_notes,
    }
    request_path = _write_request(request_dir / "plot_request.json", request)
    manifest = run_request(request_path)
    return {
        "id": request_name,
        "request_path": str(request_path),
        "summary": _manifest_summary(manifest),
    }


def _run_torque_acceptance(*, project_dir: Path, torque_dir: Path) -> dict[str, Any]:
    curation = curate_torque_project(
        torque_dir,
        output_root=project_dir / "_torque_curation_projects",
        project_name="3D PA torque acceptance",
        open_review=False,
    )
    request_path = Path(str(curation["plot_request"]))
    manifest = run_request(request_path)
    return {
        "id": "torque_260607_curve",
        "request_path": str(request_path),
        "summary": _manifest_summary(manifest),
        "curation": {
            "source_dir": str(torque_dir),
            "project_dir": curation.get("project_dir"),
            "selection_path": curation.get("selection_path"),
            "plot_data_path": curation.get("plot_data_path"),
            "review_html": curation.get("review_html"),
        },
    }


def run_3dpa_acceptance(
    input_root: Path,
    *,
    output_root: Path,
    project_name: str = "3dpa_acceptance",
    representative_count: int = DEFAULT_REPRESENTATIVE_COUNT,
    dense_series_count: int = DEFAULT_DENSE_SERIES_COUNT,
) -> dict[str, Any]:
    root = input_root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"3D PA input root not found: {input_root}")
    if representative_count < 2:
        raise ValueError("representative_count must be at least 2.")
    output_root = output_root.expanduser().resolve()
    project_dir = output_root / slug(project_name)
    data_dir = project_dir / "data"
    source_files = _find_ftir_files(root, representative_count=representative_count)
    spectra = _load_spectra(source_files)
    representative_table = _write_curve_table(
        spectra, data_dir / "3dpa_ftir_representative_stack.csv"
    )
    dense_table = _write_curve_table(
        _build_dense_series(spectra, series_count=dense_series_count),
        data_dir / f"3dpa_ftir_dense_stack_{dense_series_count}.csv",
    )

    runs = [
        _run_acceptance_request(
            run_root=project_dir,
            request_name="ftir_representative_stack",
            input_path=representative_table,
            render_options={"size": DEFAULT_FIGURE_SIZE, "series_label_mode": "legend"},
            review_notes=[
                "3D PA FTIR representative stack acceptance from raw two-column spectra."
            ],
        ),
        _run_acceptance_request(
            run_root=project_dir,
            request_name="ftir_dense_auto_split",
            input_path=dense_table,
            render_options={"size": "60x110", "series_label_mode": "legend"},
            review_notes=[
                "3D PA FTIR dense-stack acceptance. Representative raw spectra are duplicated to exercise "
                "automatic split boundaries without synthetic curve shapes."
            ],
        ),
    ]
    torque_dir = _find_torque_dir(root)
    if torque_dir is not None:
        runs.append(
            _run_torque_acceptance(project_dir=project_dir, torque_dir=torque_dir)
        )
    state = (
        "ready"
        if all(run["summary"]["state"] == "ready" for run in runs)
        else "needs_rule_repair"
    )
    payload = {
        "kind": "sciplot_acceptance_run",
        "target": "3dpa",
        "state": state,
        "project_dir": str(project_dir),
        "source_root": str(root),
        "source_files": [str(path) for path in source_files],
        "torque_source_dir": str(torque_dir) if torque_dir is not None else None,
        "data": {
            "representative_table": str(representative_table),
            "dense_table": str(dense_table),
            "dense_series_count": dense_series_count,
        },
        "runs": runs,
    }
    (project_dir / "acceptance_summary.json").write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload
