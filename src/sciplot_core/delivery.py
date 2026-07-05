from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import json_safe, slug
from sciplot_core.policy import DELIVERY_DIR, DELIVERY_FIGURES_DIR, DELIVERY_INTERNAL_DIR


def _project_slug(output_dir: Path, manifest: dict[str, Any]) -> str:
    request_path = manifest.get("request_path")
    if isinstance(request_path, str) and request_path.strip():
        parent = Path(request_path).expanduser().parent
        if parent.name and parent.name not in {".", ".."}:
            return slug(parent.name)
    input_path = manifest.get("input")
    if isinstance(input_path, str) and input_path.strip():
        return slug(Path(input_path).stem)
    return slug(output_dir.name)


def _copytree_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def _copy_file_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _write_excel_data(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        shutil.copy2(source, destination)
        return {"source": str(source), "converted": False, "sheet": None}
    if source.suffix.lower() in {".csv", ".txt", ".tsv"}:
        separator = "\t" if source.suffix.lower() == ".tsv" else ","
        frame = pd.read_csv(source, header=None, sep=separator)
        with pd.ExcelWriter(destination) as writer:
            frame.to_excel(writer, sheet_name="plot_data", header=False, index=False)
        return {"source": str(source), "converted": True, "sheet": "plot_data"}
    frame = pd.DataFrame({"source_path": [str(source)]})
    with pd.ExcelWriter(destination) as writer:
        frame.to_excel(writer, sheet_name="plot_data", index=False)
    return {"source": str(source), "converted": True, "sheet": "plot_data"}


def _delivery_data_source(manifest: dict[str, Any]) -> Path | None:
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for key in ("processed_source", "input"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            candidate = Path(value).expanduser()
            if candidate.exists() and candidate.is_file():
                return candidate
    value = manifest.get("input")
    if isinstance(value, str) and value.strip():
        candidate = Path(value).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def build_delivery_package(output_dir: Path, *, manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    delivery_dir = output_dir / DELIVERY_DIR
    if delivery_dir.exists():
        shutil.rmtree(delivery_dir)
    figures_dir = delivery_dir / DELIVERY_FIGURES_DIR
    internal_dir = delivery_dir / DELIVERY_INTERNAL_DIR
    figures_dir.mkdir(parents=True, exist_ok=True)
    internal_dir.mkdir(parents=True, exist_ok=True)

    project = _project_slug(output_dir, manifest)
    sciplot_path = delivery_dir / f"{project}.sciplot"
    data_path = delivery_dir / f"{project}.xlsx"

    figure_records: list[dict[str, Any]] = []
    for figure_value in manifest.get("figures", []):
        if not isinstance(figure_value, str):
            continue
        source = Path(figure_value).expanduser()
        if not source.exists() or not source.is_file():
            continue
        destination = figures_dir / source.name
        shutil.copy2(source, destination)
        figure_records.append(
            {
                "source": str(source),
                "path": str(destination),
                "relative_path": str(destination.relative_to(delivery_dir)),
                "format": source.suffix.lower().lstrip("."),
            }
        )

    data_source = _delivery_data_source(manifest)
    data_record: dict[str, Any] | None = None
    if data_source is not None:
        data_record = _write_excel_data(data_source, data_path)
        data_record["path"] = str(data_path)
        data_record["relative_path"] = str(data_path.relative_to(delivery_dir))

    copied_internal: list[str] = []
    for filename in (
        "request_snapshot.json",
        "analysis_report.md",
        "revision_brief.md",
        "review.html",
        "intervention_request.json",
    ):
        if _copy_file_if_exists(output_dir / filename, internal_dir / filename):
            copied_internal.append(filename)
    for folder in ("tables", "raw", "processed", "_veusz", "studio"):
        if _copytree_if_exists(output_dir / folder, internal_dir / folder):
            copied_internal.append(folder)
    if _copytree_if_exists(output_dir / "figures" / "_veusz", internal_dir / "_veusz"):
        copied_internal.append("_veusz")

    delivery_record = {
        "kind": "sciplot_minimal_delivery_package",
        "version": 1,
        "path": str(delivery_dir),
        "project": project,
        "project_file": str(sciplot_path),
        "excel_data": str(data_path) if data_path.exists() else None,
        "figures": figure_records,
        "internal": str(internal_dir),
        "internal_artifacts": copied_internal,
    }
    manifest_payload = json_safe({**manifest, "delivery_package": delivery_record})
    (internal_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    copied_internal.insert(0, "manifest.json")

    project_payload = {
        "kind": "sciplot_project",
        "version": 1,
        "project": project,
        "manifest": manifest_payload,
        "delivery_package": delivery_record,
        "data": data_record,
        "figures": figure_records,
        "internal_dir": DELIVERY_INTERNAL_DIR,
    }
    sciplot_path.write_text(json.dumps(project_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    artifact_status = [
        {"id": "project_file", "path": str(sciplot_path), "exists": sciplot_path.exists()},
        {"id": "excel_data", "path": str(data_path), "exists": data_path.exists()},
        {"id": "pdf", "path": str(figures_dir), "exists": any(figures_dir.glob("*.pdf"))},
        {"id": "tiff_300", "path": str(figures_dir), "exists": any(figures_dir.glob("*_300dpi.tiff"))},
    ]
    delivery_record = {
        **delivery_record,
        "complete": all(item["exists"] for item in artifact_status),
        "artifacts": artifact_status,
    }
    manifest_payload = json_safe({**manifest, "delivery_package": delivery_record})
    one_step = manifest_payload.get("one_step")
    if isinstance(one_step, dict):
        one_step["delivery_package"] = delivery_record
        figure_qa = one_step.get("figure_qa_report")
        if isinstance(figure_qa, dict):
            figure_qa["delivery_complete"] = bool(delivery_record["complete"])
        if delivery_record["complete"]:
            reasons = [
                str(reason)
                for reason in one_step.get("state_reasons", [])
                if str(reason) != "delivery_package_incomplete"
            ]
            one_step["state_reasons"] = reasons or ["all_programmatic_gates_passed"]
            if one_step.get("state") == "needs_rule_repair" and not reasons:
                one_step["state"] = "ready"
    project_payload["delivery_package"] = delivery_record
    project_payload["manifest"] = manifest_payload
    (internal_dir / "manifest.json").write_text(
        json.dumps(project_payload["manifest"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    sciplot_path.write_text(json.dumps(project_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return delivery_record


__all__ = ["build_delivery_package"]
