from __future__ import annotations

import base64
import errno
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import webbrowser
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import pandas as pd

from sciplot_core._paths import REPO_ROOT
from sciplot_core._utils import json_safe, safe_filename, slug, unique_path
from sciplot_core.assisted_cleanup import CLEANUP_REQUEST_FILENAME, CLEANUP_RESULT_FILENAME, write_cleanup_request
from sciplot_core.codex_jobs import codex_available, list_codex_jobs, load_codex_job, start_codex_job
from sciplot_core.ingest import smart_decode
from sciplot_core.materials_rules import get_rule
from sciplot_core.operation_modes import assisted_cleanup_mode_payload, normal_mode_payload
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    FIGURE_SIZE_PRESETS,
    FTIR_SPECTRUM_RENDER_OPTIONS,
    TORQUE_OFFSET_STACK_RENDER_OPTIONS,
)
from sciplot_core.publication import build_publication_intent, build_transform_ledger, get_publication_profile
from sciplot_core.semantic import (
    classify_source,
    is_rheology_frequency_comparison_dir,
    is_rheology_temperature_comparison_dir,
)
from sciplot_core.study_model import build_study_model, sync_study_model_samples
from sciplot_core.workbench_contract import apply_request_patch, normalize_exports, normalize_render_options

_STATIC_DIR = Path(__file__).with_name("intake_static")
_DEFAULT_OUTPUT_ROOT = Path("outputs") / "intake_projects"
APPROVED_INTAKE_SIZE_PRESETS = FIGURE_SIZE_PRESETS
_TEXT_EXTENSIONS = {".csv", ".tsv", ".txt"}
_TABLE_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
_PREVIEW_SCAN_ROWS = 80
_PREVIEW_DISPLAY_ROWS = 24
_PREVIEW_DISPLAY_COLUMNS = 24
_COLUMN_ROLES = {"auto", "x", "y", "series", "sample", "unit", "metadata", "ignore"}
_COLUMN_TYPES = {"auto", "numeric", "text", "categorical", "datetime", "unit", "metadata", "ignore"}
_REPLICATE_MODES = {"mean", "representative", "individual"}


@dataclass(frozen=True)
class IncomingFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class IntakeGroupInput:
    sample: str
    files: tuple[IncomingFile, ...]


@dataclass(frozen=True)
class IntakeProjectRequest:
    project_dir: Path
    manifest: dict[str, Any]
    request_path: Path
    request: dict[str, Any]


INTAKE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "rheology_dma",
        "label": "流变 / DMA",
        "icon": "curves",
        "experiments": (
            {"id": "rheology_frequency_sweep", "label": "频率扫描", "rule_id": "rheology_frequency_sweep"},
            {"id": "rheology_temperature_sweep", "label": "温度扫描", "rule_id": "rheology_temperature_sweep"},
            {"id": "rheology_stress_relaxation", "label": "应力松弛", "rule_id": "rheology_stress_relaxation"},
            {"id": "rheology_creep", "label": "蠕变", "rule_id": "rheology_creep"},
            {"id": "rheology_time_sweep", "label": "时间扫描", "rule_id": "rheology_time_sweep"},
            {"id": "rheology_strain_sweep", "label": "应变扫描", "rule_id": "rheology_strain_sweep"},
            {"id": "rheology_stress_sweep", "label": "应力扫描", "rule_id": "rheology_stress_sweep"},
            {"id": "dma_temperature_sweep", "label": "DMA 温扫", "rule_id": "dma_temperature_sweep"},
            {"id": "dma_frequency_sweep", "label": "DMA 频扫", "rule_id": "dma_frequency_sweep"},
            {"id": "unknown_rheology", "label": "未知流变", "rule_id": None},
        ),
    },
    {
        "id": "mechanical",
        "label": "力学",
        "icon": "tensile",
        "experiments": (
            {
                "id": "tensile_curve",
                "label": "拉伸曲线",
                "rule_id": "tensile_curve",
                "default_replicate_mode": "representative",
            },
            {
                "id": "tensile_strength",
                "label": "拉伸强度",
                "rule_id": "tensile_curve",
                "chart": "box_strip",
                "template": "box_strip",
            },
            {
                "id": "elongation_at_break",
                "label": "断裂伸长率",
                "rule_id": "tensile_curve",
                "chart": "box_strip",
                "template": "box_strip",
            },
            {
                "id": "youngs_modulus",
                "label": "杨氏模量",
                "rule_id": "tensile_curve",
                "chart": "box_strip",
                "template": "box_strip",
            },
            {"id": "compression_curve", "label": "压缩", "rule_id": "compression_curve"},
            {"id": "flexural_curve", "label": "弯曲", "rule_id": "flexural_curve"},
            {"id": "torque_curve", "label": "转矩曲线", "rule_id": "torque_curve", "chart": "curve"},
            {
                "id": "torque_offset_stack",
                "label": "转矩偏移堆积",
                "rule_id": "torque_curve",
                "chart": "stacked_curve",
                "template": "stacked_curve",
                "render_options": dict(TORQUE_OFFSET_STACK_RENDER_OPTIONS),
            },
            {
                "id": "impact_metric",
                "label": "冲击",
                "rule_id": "impact_metric",
                "chart": "box_strip",
                "template": "box_strip",
                "default_replicate_mode": "individual",
            },
            {"id": "unknown_mechanical", "label": "未知力学", "rule_id": None},
        ),
    },
    {
        "id": "thermal",
        "label": "热分析",
        "icon": "thermal",
        "experiments": (
            {"id": "dsc_curve", "label": "DSC", "rule_id": "dsc_curve", "chart": "stacked_curve"},
            {"id": "tga_curve", "label": "TGA", "rule_id": "tga_curve"},
            {"id": "dtg_curve", "label": "DTG", "rule_id": "dtg_curve"},
            {"id": "unknown_thermal", "label": "未知热分析", "rule_id": None},
        ),
    },
    {
        "id": "spectroscopy",
        "label": "光谱",
        "icon": "spectrum",
        "experiments": (
            {
                "id": "ftir_spectrum",
                "label": "FTIR",
                "rule_id": "ftir_spectrum",
                "chart": "stacked_curve",
                "template": "stacked_curve",
                "render_options": dict(FTIR_SPECTRUM_RENDER_OPTIONS),
            },
            {"id": "uvvis_spectrum", "label": "UV-vis", "rule_id": "uvvis_spectrum"},
            {"id": "unknown_spectroscopy", "label": "未知光谱", "rule_id": None},
        ),
    },
    {
        "id": "scattering",
        "label": "衍射 / 散射",
        "icon": "scattering",
        "experiments": (
            {"id": "xrd_pattern", "label": "XRD", "rule_id": "xrd_pattern"},
            {"id": "saxs_profile", "label": "SAXS", "rule_id": "saxs_profile"},
            {"id": "unknown_scattering", "label": "未知散射", "rule_id": None},
        ),
    },
    {
        "id": "chromatography",
        "label": "色谱 / 分子量",
        "icon": "chromatography",
        "experiments": (
            {"id": "gpc_sec_chromatogram", "label": "GPC / SEC", "rule_id": "gpc_sec_chromatogram"},
            {"id": "unknown_chromatography", "label": "未知色谱", "rule_id": None},
        ),
    },
    {
        "id": "metrics_time",
        "label": "指标 / 时序",
        "icon": "metrics",
        "experiments": (
            {"id": "swelling_curve", "label": "溶胀", "rule_id": "swelling_curve"},
            {"id": "unknown_metrics", "label": "未知指标", "rule_id": None},
        ),
    },
    {
        "id": "unknown",
        "label": "未知",
        "icon": "unknown",
        "experiments": ({"id": "unknown", "label": "未知", "rule_id": None},),
    },
)


def _rule_is_ready_for_public_catalog(rule_id: str | None) -> bool:
    if not rule_id:
        return True
    try:
        return get_rule(rule_id).fixture_status == "ready"
    except ValueError:
        return False


def _public_intake_catalog(*, include_pending: bool = False) -> tuple[dict[str, Any], ...]:
    if include_pending:
        return INTAKE_CATALOG
    data_types: list[dict[str, Any]] = []
    for data_type in INTAKE_CATALOG:
        experiments = [
            experiment
            for experiment in data_type["experiments"]
            if _rule_is_ready_for_public_catalog(experiment.get("rule_id"))
        ]
        if not experiments:
            continue
        data_types.append({**data_type, "experiments": tuple(experiments)})
    return tuple(data_types)


def intake_catalog_payload(*, include_pending: bool = False) -> dict[str, Any]:
    catalog = _public_intake_catalog(include_pending=include_pending)
    visible_rules = {
        str(experiment.get("rule_id"))
        for data_type in catalog
        for experiment in data_type["experiments"]
        if experiment.get("rule_id")
    }
    return {
        "kind": "sciplot_intake_catalog",
        "visibility": "all" if include_pending else "ready",
        "ready_rule_ids": sorted(visible_rules),
        "data_types": json_safe(catalog),
        "figure_size_presets": list(APPROVED_INTAKE_SIZE_PRESETS),
    }


def _catalog_item(data_type_id: str, experiment_type_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for data_type in INTAKE_CATALOG:
        if data_type["id"] != data_type_id:
            continue
        for experiment in data_type["experiments"]:
            if experiment["id"] == experiment_type_id:
                return data_type, experiment
        raise ValueError(f"Unknown experiment type `{experiment_type_id}` for data type `{data_type_id}`.")
    raise ValueError(f"Unknown data type `{data_type_id}`.")


def _catalog_item_for_rule(rule_id: str | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not rule_id:
        return None
    for data_type in INTAKE_CATALOG:
        for experiment in data_type["experiments"]:
            if experiment.get("rule_id") == rule_id:
                return data_type, experiment
    return None


def _write_zip(project_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(project_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(project_dir.parent))


def _write_project_launcher(project_dir: Path, *, project_slug: str) -> str:
    launcher = project_dir / "Open_SciPlot_Project.command"
    launcher.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                'PROJECT_DIR="${0:A:h}"',
                'PROJECT_ROOT="${PROJECT_DIR:h}"',
                f'cd "{REPO_ROOT}"',
                (
                    'skill/scripts/sciplot workbench '
                    '--out "${PROJECT_ROOT}" '
                    f'--project "{project_slug}"'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return str(launcher)


def refresh_intake_project_zip(project_dir: str | Path) -> Path:
    project_dir = Path(project_dir).expanduser().resolve()
    manifest_path = project_dir / "intake_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        zip_name = f"{manifest.get('project_slug') or project_dir.name}.zip"
    else:
        zip_name = f"{project_dir.name}.zip"
    zip_path = project_dir.parent / safe_filename(zip_name)
    _write_zip(project_dir, zip_path)
    return zip_path


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_render_failure_cleanup_request(
    *,
    run_output: Path,
    request: dict[str, Any],
    request_path: Path,
    intervention: Path,
) -> str | None:
    cleanup_request = run_output / CLEANUP_REQUEST_FILENAME
    if cleanup_request.exists():
        return str(cleanup_request)
    input_value = request.get("input")
    if not isinstance(input_value, str) or not input_value.strip():
        return None
    input_path = Path(input_value).expanduser()
    if not input_path.is_absolute():
        input_path = request_path.parent / input_path
    write_cleanup_request(
        run_output,
        input_path=input_path,
        reason="render_failure",
        request=request,
        intervention_request=intervention if intervention.exists() else None,
        provider="codex",
    )
    return str(cleanup_request)


def _project_dir_fromslug(output_root: Path, project_slug: str) -> Path:
    safe_slug = safe_filename(project_slug)
    project_dir = (output_root.expanduser().resolve() / safe_slug).resolve()
    if not _path_within(project_dir, output_root.expanduser().resolve()):
        raise PermissionError("Project path is outside the configured output root.")
    return project_dir


def _artifact_info(path: Path, *, project_slug: str) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    stat = path.stat() if exists else None
    return {
        "exists": exists,
        "path": str(path),
        "name": path.name,
        "size_bytes": stat.st_size if stat is not None else 0,
        "mtime_ns": stat.st_mtime_ns if stat is not None else 0,
        "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "url": f"/api/projects/{quote(project_slug)}/artifact?path={quote(str(path), safe='')}" if exists else None,
    }


def _download_info(path: Path) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    stat = path.stat() if exists else None
    return {
        "exists": exists,
        "path": str(path),
        "name": path.name,
        "size_bytes": stat.st_size if stat is not None else 0,
        "mtime_ns": stat.st_mtime_ns if stat is not None else 0,
        "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "url": f"/api/download/{quote(path.name)}" if exists else None,
    }


def _project_package_info(project_dir: Path, *, project_slug: str) -> dict[str, Any]:
    launcher = project_dir / "Open_SciPlot_Project.command"
    launcher_info = _artifact_info(launcher, project_slug=project_slug)
    launcher_info["executable"] = bool(launcher_info["exists"] and (launcher.stat().st_mode & 0o111))
    studio_launcher = project_dir / "Open_in_SciPlot_Studio.command"
    studio_launcher_info = _artifact_info(studio_launcher, project_slug=project_slug)
    studio_launcher_info["executable"] = bool(
        studio_launcher_info["exists"] and (studio_launcher.stat().st_mode & 0o111)
    )
    veusz_launcher = project_dir / "Open_in_Veusz.command"
    veusz_launcher_info = _artifact_info(veusz_launcher, project_slug=project_slug)
    veusz_launcher_info["executable"] = bool(
        veusz_launcher_info["exists"] and (veusz_launcher.stat().st_mode & 0o111)
    )
    export_edited_launcher = project_dir / "Export_Edited_Veusz.command"
    export_edited_launcher_info = _artifact_info(export_edited_launcher, project_slug=project_slug)
    export_edited_launcher_info["executable"] = bool(
        export_edited_launcher_info["exists"] and (export_edited_launcher.stat().st_mode & 0o111)
    )
    studio_documents = [
        _artifact_info(path, project_slug=project_slug)
        for path in sorted((project_dir / "studio").glob("*.vsz"))
    ]
    sciplot_manifests = [
        _artifact_info(path, project_slug=project_slug)
        for path in sorted(project_dir.glob("*.sciplot.json"))
    ]
    zip_path = project_dir.parent / safe_filename(f"{project_slug}.zip")
    zip_info = _download_info(zip_path)
    return {
        "kind": "sciplot_project_package_status",
        "complete": bool(
            launcher_info["exists"]
            and launcher_info["executable"]
            and sciplot_manifests
            and all(item["exists"] for item in sciplot_manifests)
            and zip_info["exists"]
        ),
        "launcher": launcher_info,
        "studio": {
            "launcher": studio_launcher_info,
            "veusz_launcher": veusz_launcher_info,
            "export_edited_launcher": export_edited_launcher_info,
            "documents": studio_documents,
            "complete": bool(
                studio_launcher_info["exists"]
                and studio_launcher_info["executable"]
                and veusz_launcher_info["exists"]
                and veusz_launcher_info["executable"]
                and export_edited_launcher_info["exists"]
                and export_edited_launcher_info["executable"]
                and studio_documents
                and all(item["exists"] for item in studio_documents)
            ),
        },
        "sciplot_manifests": sciplot_manifests,
        "zip": zip_info,
    }


def _studio_prepare_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    framework_paths = [Path("/opt/homebrew/opt/qtbase/lib"), Path("/opt/homebrew/opt/qt/lib")]
    existing = [str(path) for path in framework_paths if path.exists()]
    if existing:
        joined = ":".join(existing)
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            current = env.get(key)
            env[key] = f"{joined}:{current}" if current else joined
        env.setdefault("SCIPLOT_STUDIO_QT_RUNTIME", "1")
    return env


def _prepare_studio_project_package(project_dir: Path) -> None:
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.cli",
                "studio",
                str(project_dir),
                "--prepare-only",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=True,
            env=_studio_prepare_env(),
        )
    except Exception:
        return


def _preview_path_for_figure(path: Path) -> Path:
    stem = path.stem
    if stem.endswith("_300dpi"):
        stem = stem[: -len("_300dpi")]
    return path.with_name(f"{stem}_preview.png")


def _preview_is_fresh(preview_path: Path, source_path: Path, *, min_width_px: int = 0) -> bool:
    if not preview_path.exists() or not preview_path.is_file():
        return False
    try:
        if preview_path.stat().st_mtime_ns < source_path.stat().st_mtime_ns:
            return False
        if min_width_px:
            from PIL import Image

            with Image.open(preview_path) as image:
                return int(image.width) >= min_width_px
        return True
    except OSError:
        return False


def _write_image_preview(source_path: Path, preview_path: Path) -> None:
    from PIL import Image

    with Image.open(source_path) as image:
        try:
            image.seek(0)
        except EOFError:
            pass
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(preview_path)


def _write_pdf_preview(source_path: Path, preview_path: Path) -> None:
    import fitz

    with fitz.open(source_path) as document:
        if document.page_count < 1:
            raise ValueError("PDF has no pages.")
        page = document.load_page(0)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(preview_path))


def _figure_preview_info(figures: list[Path], *, project_slug: str) -> dict[str, Any]:
    existing_images = [
        figure
        for figure in figures
        if figure.exists() and figure.is_file() and figure.suffix.casefold() in {".png", ".jpg", ".jpeg"}
    ]
    for image_path in existing_images:
        info = _artifact_info(image_path, project_slug=project_slug)
        return {**info, "display_kind": "image", "source_path": str(image_path)}

    source_figures = [figure for figure in figures if figure.exists() and figure.is_file()]
    image_sources = [figure for figure in source_figures if figure.suffix.casefold() in {".tif", ".tiff"}]
    pdf_sources = [figure for figure in source_figures if figure.suffix.casefold() == ".pdf"]

    for source_path in image_sources:
        preview_path = _preview_path_for_figure(source_path)
        if _preview_is_fresh(preview_path, source_path, min_width_px=600):
            info = _artifact_info(preview_path, project_slug=project_slug)
            return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in image_sources:
        preview_path = _preview_path_for_figure(source_path)
        try:
            _write_image_preview(source_path, preview_path)
        except Exception:
            continue
        info = _artifact_info(preview_path, project_slug=project_slug)
        return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in pdf_sources:
        preview_path = _preview_path_for_figure(source_path)
        if _preview_is_fresh(preview_path, source_path):
            info = _artifact_info(preview_path, project_slug=project_slug)
            return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in pdf_sources:
        preview_path = _preview_path_for_figure(source_path)
        try:
            _write_pdf_preview(source_path, preview_path)
        except Exception:
            continue
        info = _artifact_info(preview_path, project_slug=project_slug)
        return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in pdf_sources:
        info = _artifact_info(source_path, project_slug=project_slug)
        return {**info, "display_kind": "pdf", "source_path": str(source_path)}

    return {
        "exists": False,
        "path": "",
        "name": "",
        "size_bytes": 0,
        "mtime_ns": 0,
        "content_type": "",
        "url": None,
        "display_kind": "none",
        "source_path": "",
    }


def list_intake_projects(output_root: Path) -> list[dict[str, Any]]:
    output_root = output_root.expanduser().resolve()
    if not output_root.is_dir():
        return []
    projects: list[dict[str, Any]] = []
    for entry in sorted(output_root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "intake_manifest.json"
        manifest = _read_json_if_exists(manifest_path)
        if manifest is None:
            continue
        sciplot_path = next(entry.glob("*.sciplot.json"), None)
        sciplot_meta = _read_json_if_exists(sciplot_path) if sciplot_path else {}
        stat = entry.stat()
        last_run = manifest.get("last_run") if isinstance(manifest.get("last_run"), dict) else {}
        figure_count = len(last_run.get("figures", []))
        projects.append({
            "slug": entry.name,
            "project_name": manifest.get("project_name") or entry.name,
            "data_type": manifest.get("data_type"),
            "experiment": manifest.get("experiment"),
            "created": sciplot_meta.get("created", ""),
            "figure_count": figure_count,
            "has_failure": bool(last_run.get("failure")),
            "last_run_output": last_run.get("output", ""),
            "mtime_ns": stat.st_mtime_ns,
            "group_count": len(manifest.get("groups", [])),
            "file_count": sum(len(group.get("files", [])) for group in manifest.get("groups", [])),
        })
    projects.sort(key=lambda p: p["mtime_ns"], reverse=True)
    return projects


def _allowed_artifact_roots(project_dir: Path) -> list[Path]:
    roots = [project_dir.resolve()]
    manifest = _read_json_if_exists(project_dir / "intake_manifest.json") or {}
    for value in (
        manifest.get("outputs_dir"),
        (manifest.get("last_run") or {}).get("output") if isinstance(manifest.get("last_run"), dict) else None,
    ):
        if isinstance(value, str) and value.strip():
            roots.append(Path(value).expanduser().resolve())
    return roots


def _resolve_project_artifact(project_dir: Path, artifact_path: str) -> Path:
    if not artifact_path.strip():
        raise ValueError("Artifact path is required.")
    requested = Path(artifact_path).expanduser()
    roots = _allowed_artifact_roots(project_dir)
    if requested.is_absolute():
        candidate = requested.resolve()
        if any(_path_within(candidate, root) for root in roots):
            return candidate
        raise PermissionError("Artifact path is outside this SciPlot project.")
    for root in roots:
        candidate = (root / requested).resolve()
        if _path_within(candidate, root):
            return candidate
    raise PermissionError("Artifact path is outside this SciPlot project.")


def intake_project_status(project_dir: str | Path) -> dict[str, Any]:
    project_path = Path(project_dir).expanduser().resolve()
    manifest_path = project_path / "intake_manifest.json"
    manifest = _read_json_if_exists(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"No intake project manifest found at {manifest_path}.")
    project_slug = str(manifest.get("project_slug") or project_path.name)
    last_run = manifest.get("last_run") if isinstance(manifest.get("last_run"), dict) else {}
    run_output = Path(str(last_run.get("output") or manifest.get("outputs_dir") or project_path / "runs" / "run_001"))
    intervention_path = run_output / "intervention_request.json"
    cleanup_request_path = run_output / CLEANUP_REQUEST_FILENAME
    cleanup_result_path = run_output / CLEANUP_RESULT_FILENAME
    artifacts = {
        "manifest": _artifact_info(run_output / "manifest.json", project_slug=project_slug),
        "analysis_report": _artifact_info(run_output / "analysis_report.md", project_slug=project_slug),
        "analysis_metrics": _artifact_info(run_output / "tables" / "analysis_metrics.csv", project_slug=project_slug),
        "revision_brief": _artifact_info(run_output / "revision_brief.md", project_slug=project_slug),
        "review_html": _artifact_info(run_output / "review.html", project_slug=project_slug),
        "intervention_request": _artifact_info(intervention_path, project_slug=project_slug),
        "assisted_cleanup_request": _artifact_info(cleanup_request_path, project_slug=project_slug),
        "cleanup_result": _artifact_info(cleanup_result_path, project_slug=project_slug),
    }
    delivery = last_run.get("delivery_package") if isinstance(last_run.get("delivery_package"), dict) else {}
    project_file = delivery.get("project_file")
    excel_data = delivery.get("excel_data")
    if isinstance(project_file, str) and project_file.strip():
        artifacts["delivery_project"] = _artifact_info(Path(project_file), project_slug=project_slug)
    if isinstance(excel_data, str) and excel_data.strip():
        artifacts["delivery_excel"] = _artifact_info(Path(excel_data), project_slug=project_slug)
    figure_paths = [Path(str(path)) for path in last_run.get("figures", []) if isinstance(path, str)]
    figures = [_artifact_info(path, project_slug=project_slug) for path in figure_paths]
    preview_figure = _figure_preview_info(figure_paths, project_slug=project_slug)
    cleanup_result = _read_json_if_exists(cleanup_result_path)
    cleanup_ready = bool(cleanup_result and cleanup_result.get("ready_for_normal_mode") is True)
    has_cleanup_blocker = bool(
        last_run.get("failure")
        or artifacts["intervention_request"]["exists"]
        or artifacts["assisted_cleanup_request"]["exists"]
    )
    needs_assisted_cleanup = bool(has_cleanup_blocker and not cleanup_ready)
    operation_mode = (
        assisted_cleanup_mode_payload(reason="project_failure_or_intervention")
        if needs_assisted_cleanup
        else normal_mode_payload(route="web")
    )
    assistant_available = codex_available()
    assistant_jobs = list_codex_jobs(project_path)
    return {
        "kind": "sciplot_project_status",
        "project_slug": project_slug,
        "project_dir": str(project_path),
        "manifest": json_safe(manifest),
        "plot_request": manifest.get("plot_request"),
        "outputs_dir": str(run_output),
        "last_run": json_safe(last_run),
        "artifacts": artifacts,
        "project_package": _project_package_info(project_path, project_slug=project_slug),
        "figures": figures,
        "preview_figure": preview_figure,
        "workbench": {
            "apply_url": f"/api/projects/{quote(project_slug)}/workbench/apply",
            "preview_source": "rendered_artifacts_only",
        },
        "operation_mode": operation_mode,
        "needs_assisted_cleanup": needs_assisted_cleanup,
        "needs_codex": needs_assisted_cleanup,
        "cleanup": {
            "request": artifacts["assisted_cleanup_request"],
            "result": artifacts["cleanup_result"],
            "ready_for_normal_mode": cleanup_ready,
            "payload": json_safe(cleanup_result) if cleanup_result is not None else None,
        },
        "assistant": {
            "provider": "codex",
            "available": assistant_available,
            "jobs": assistant_jobs,
        },
        "codex": {
            "available": assistant_available,
            "jobs": assistant_jobs,
        },
}


def _decode_text_preview(path: Path, *, max_bytes: int = 8192) -> str:
    return smart_decode(path.read_bytes()[:max_bytes])[0]


def _looks_like_tensile_export_dir(path: Path) -> bool:
    return path.is_dir() and path.name.casefold().endswith(".is_tens_exports")


def _tensile_export_dirs(source: Path) -> list[Path]:
    if _looks_like_tensile_export_dir(source):
        return [source]
    if not source.is_dir():
        return []
    direct = [path for path in source.iterdir() if _looks_like_tensile_export_dir(path)]
    if direct:
        return sorted(direct, key=lambda path: path.name.casefold())
    return sorted(
        (path for path in source.rglob("*") if _looks_like_tensile_export_dir(path)),
        key=lambda path: path.name,
    )


def _is_torque_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in _TEXT_EXTENSIONS:
        return False
    text = _decode_text_preview(path).casefold()
    return "screw torque" in text or "转矩" in text


def _torque_files(source: Path) -> list[Path]:
    if _is_torque_file(source):
        return [source]
    if not source.is_dir():
        return []
    return sorted((path for path in source.iterdir() if _is_torque_file(path)), key=lambda path: path.name.casefold())


def _table_files(source: Path) -> list[Path]:
    if source.is_file() and source.suffix.lower() in _TABLE_EXTENSIONS:
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (path for path in source.iterdir() if path.is_file() and path.suffix.lower() in _TABLE_EXTENSIONS),
        key=lambda path: path.name.casefold(),
    )


def _rheology_comparison_files(source: Path) -> list[Path]:
    files = _table_files(source)
    text_files = [path for path in files if path.suffix.lower() in {".csv", ".tsv", ".txt"}]
    return text_files or files


def _file_payload(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "name": path.name,
        "source_path": str(path.expanduser().resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _duplicate_source_warnings(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[dict[str, str]]] = {}
    for group in groups:
        sample = str(group.get("sample") or "")
        for item in group.get("files", []):
            if not isinstance(item, dict):
                continue
            digest = str(item.get("sha256") or "")
            if not digest:
                continue
            by_hash.setdefault(digest, []).append(
                {
                    "sample": sample,
                    "name": str(item.get("original_name") or item.get("name") or ""),
                    "source_path": str(item.get("source_path") or ""),
                }
            )
    warnings: list[dict[str, Any]] = []
    for digest, records in sorted(by_hash.items()):
        samples = sorted({record["sample"] for record in records if record["sample"]})
        if len(records) < 2 or len(samples) < 2:
            continue
        warnings.append(
            {
                "id": "duplicate_source_files",
                "severity": "warning",
                "message": (
                    "Multiple sample files have identical byte content; rendered curves may overlap exactly."
                ),
                "sha256": digest,
                "samples": samples,
                "files": records,
            }
        )
    return warnings


def _preview_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _preview_is_number(value: object) -> bool:
    text = _preview_cell(value).replace(",", "").strip()
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _preview_read_frame(name: str, content: bytes) -> tuple[pd.DataFrame, str | None, str | None]:
    suffix = Path(name).suffix.lower()
    encoding: str | None = None
    sheet: str | None = None
    if suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(io.BytesIO(content))
        sheet = str(workbook.sheet_names[0])
        frame = pd.read_excel(workbook, sheet_name=sheet, header=None, nrows=_PREVIEW_SCAN_ROWS)
    else:
        text, encoding = smart_decode(content)
        buffer = io.StringIO(text)
        try:
            frame = pd.read_csv(buffer, sep=None, engine="python", header=None, nrows=_PREVIEW_SCAN_ROWS)
        except Exception:
            buffer = io.StringIO(text)
            delimiter = "\t" if suffix in {".tsv", ".txt"} or "\t" in text[:4096] else ","
            frame = pd.read_csv(buffer, sep=delimiter, header=None, nrows=_PREVIEW_SCAN_ROWS)
    frame = frame.dropna(axis=1, how="all")
    if frame.shape[1] > _PREVIEW_DISPLAY_COLUMNS:
        frame = frame.iloc[:, :_PREVIEW_DISPLAY_COLUMNS]
    return frame, sheet, encoding


def _preview_header_score(frame: pd.DataFrame, row_index: int) -> int:
    row = [_preview_cell(value).strip() for value in frame.iloc[row_index].tolist()]
    non_empty = [value for value in row if value]
    if len(non_empty) < 2:
        return 0
    text_cells = sum(1 for value in non_empty if not _preview_is_number(value))
    numeric_after = 0
    for column_index, header in enumerate(row):
        if not header:
            continue
        for lookahead in range(row_index + 1, min(frame.shape[0], row_index + 8)):
            if _preview_is_number(frame.iat[lookahead, column_index]):
                numeric_after += 1
                break
    return text_cells * 2 + min(len(non_empty), 12) + numeric_after


def _preview_header_row(frame: pd.DataFrame) -> int | None:
    if frame.empty:
        return None
    candidates = [(row_index, _preview_header_score(frame, row_index)) for row_index in range(min(frame.shape[0], 14))]
    row_index, score = max(candidates, key=lambda item: item[1])
    return row_index if score >= 6 else None


def _infer_preview_type(values: list[object]) -> str:
    non_empty = [value for value in values if _preview_cell(value).strip()]
    if not non_empty:
        return "ignore"
    numeric_count = sum(1 for value in non_empty if _preview_is_number(value))
    if numeric_count / len(non_empty) >= 0.75:
        return "numeric"
    unique_count = len({_preview_cell(value).strip() for value in non_empty})
    if len(non_empty) >= 4 and unique_count <= max(2, len(non_empty) // 3):
        return "categorical"
    unit_like = sum(1 for value in non_empty if re.fullmatch(r"\[?[%A-Za-zµμ°./^·\-0-9]+\]?", _preview_cell(value)))
    if unit_like == len(non_empty) and len(non_empty) <= 4:
        return "unit"
    return "text"


def _suggest_preview_role(column_name: str, column_index: int, inferred_type: str) -> str:
    token = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", column_name.casefold())
    if inferred_type == "ignore":
        return "ignore"
    if any(item in token for item in ("sample", "specimen", "legend", "group", "样品", "组别")):
        return "sample"
    if any(item in token for item in ("unit", "单位")):
        return "unit"
    x_tokens = ("time", "temperature", "frequency", "strain", "wavenumber", "2theta", "时间", "温度")
    if any(item in token for item in x_tokens):
        return "x"
    if inferred_type == "numeric" and column_index == 0:
        return "x"
    if inferred_type == "numeric":
        return "y"
    if inferred_type == "categorical":
        return "series"
    return "metadata"


def preview_table_payload(
    *,
    name: str,
    content: bytes | None = None,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    if content is None:
        if source_path is None:
            raise ValueError("Preview requires `source_path` or `content_base64`.")
        path = Path(source_path).expanduser()
        content = path.read_bytes()
        name = name or path.name
    frame, sheet, encoding = _preview_read_frame(name, content)
    header_row = _preview_header_row(frame)
    columns: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    start_row = (header_row + 1) if header_row is not None else 0
    for column_index in range(frame.shape[1]):
        header = _preview_cell(frame.iat[header_row, column_index]).strip() if header_row is not None else ""
        values = frame.iloc[start_row:, column_index].tolist()
        inferred_type = _infer_preview_type(values)
        name_value = header or f"Column {column_index + 1}"
        columns.append(
            {
                "index": column_index,
                "name": name_value,
                "inferred_type": inferred_type,
                "suggested_role": _suggest_preview_role(name_value, column_index, inferred_type),
                "non_empty": sum(1 for value in values if _preview_cell(value).strip()),
                "numeric": sum(1 for value in values if _preview_is_number(value)),
            }
        )
    for row_index, row in frame.head(_PREVIEW_DISPLAY_ROWS).iterrows():
        rows.append(
            {
                "index": int(row_index) + 1,
                "values": [_preview_cell(value) for value in row.tolist()],
            }
        )
    return {
        "kind": "sciplot_table_preview",
        "name": name,
        "sheet": sheet,
        "encoding": encoding,
        "header_row": (header_row + 1) if header_row is not None else None,
        "preview_rows": len(rows),
        "preview_columns": len(columns),
        "columns": columns,
        "rows": rows,
    }


def _group_payload(sample: str, files: list[Path]) -> dict[str, Any]:
    return {"sample": sample, "files": [_file_payload(path) for path in files]}


def _session_path(output_root: Path, project_name: str) -> Path:
    sessions_dir = output_root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return unique_path(sessions_dir, f"{slug(project_name)}.json")


def _session_project_name(source: Path, experiment_label: str) -> str:
    return slug(f"{source.name}_{experiment_label}")


def prepare_intake_session(
    input_path: str | Path,
    *,
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    requested_rule_id: str | None = None,
) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    if not source.exists():
        raise ValueError(f"Input path does not exist: {source}")
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    tensile_dirs = _tensile_export_dirs(source)
    temperature_files = _rheology_comparison_files(source) if is_rheology_temperature_comparison_dir(source) else []
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
        if selected_rule.fixture_status != "ready":
            raise ValueError(f"Material rule `{selected_rule.rule_id}` is not ready for production use.")
        matched = _catalog_item_for_rule(selected_rule.rule_id)
        if matched is None:
            raise ValueError(f"Material rule `{selected_rule.rule_id}` is not available in the intake catalog.")
        semantic = classify_source(source, requested_rule_id=selected_rule.rule_id)
        data_type, experiment = matched
        data_type_id = str(data_type["id"])
        experiment_type_id = str(experiment["id"])
        rule_id = selected_rule.rule_id
        reason = f"Explicit material rule `{selected_rule.rule_id}` selected by the user or Luna/Codex."
        confidence = 100.0
        if selected_rule.rule_id == "tensile_curve" and tensile_dirs:
            groups = [
                _group_payload(path.name.removesuffix(".is_tens_Exports"), sorted(path.glob("*.csv")))
                for path in tensile_dirs
            ]
        else:
            files = (
                _rheology_comparison_files(source)
                if selected_rule.semantic_family.startswith("rheology_")
                else _table_files(source)
            )
            groups = [_group_payload(path.stem, [path]) for path in files] if files else []
    elif tensile_dirs:
        data_type_id = "mechanical"
        experiment_type_id = "tensile_curve"
        rule_id = "tensile_curve"
        reason = "Detected tensile export directories and mapped each export folder to one sample group."
        confidence = 98.0
        groups = [
            _group_payload(path.name.removesuffix(".is_tens_Exports"), sorted(path.glob("*.csv")))
            for path in tensile_dirs
        ]
    elif frequency_files:
        semantic = classify_source(source, requested_rule_id="rheology_frequency_sweep")
        data_type_id = "rheology_dma"
        experiment_type_id = "rheology_frequency_sweep"
        rule_id = "rheology_frequency_sweep"
        reason = "Detected frequency-sweep exports and mapped each file to one sample group."
        confidence = 98.0
        groups = [_group_payload(path.stem, [path]) for path in frequency_files]
    elif temperature_files:
        semantic = classify_source(source, requested_rule_id="rheology_temperature_sweep")
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
        "created_at": datetime.now(UTC).isoformat(),
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
    }
    path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def create_intake_project_from_session(session: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(session, str | Path):
        payload = json.loads(Path(session).expanduser().read_text(encoding="utf-8"))
    else:
        payload = dict(session)
    groups: list[IntakeGroupInput] = []
    for group in payload.get("groups", []):
        files: list[IncomingFile] = []
        for item in group.get("files", []):
            source_path = Path(str(item.get("source_path") or "")).expanduser()
            if not source_path.exists():
                continue
            files.append(IncomingFile(name=str(item.get("name") or source_path.name), content=source_path.read_bytes()))
        groups.append(IntakeGroupInput(sample=str(group.get("sample") or ""), files=tuple(files)))
    return create_intake_project(
        project_name=str(payload.get("project_name") or ""),
        data_type_id=str(payload.get("data_type_id") or "unknown"),
        experiment_type_id=str(payload.get("experiment_type_id") or "unknown"),
        groups=groups,
        output_root=Path(str(payload.get("output_root") or _DEFAULT_OUTPUT_ROOT)),
        plot_output=payload.get("plot_output"),
        exports=payload.get("exports"),
        render_options=payload.get("render_options"),
        column_confirmations=payload.get("column_confirmations"),
        replicate_mode=payload.get("replicate_mode"),
        recognition=payload.get("semantic")
        if isinstance(payload.get("semantic"), dict)
        else {
            "semantic_family": payload.get("experiment_type_id"),
            "rule_id": payload.get("rule_id"),
            "confidence": payload.get("confidence"),
            "reason": payload.get("reason"),
        },
    )


def _resolve_plot_output(plot_output: object, *, project_dir: Path, default_output: Path) -> Path:
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


def _selected_series_order(series_order: object) -> list[str] | None:
    if not isinstance(series_order, list | tuple):
        return None
    selected: list[str] = []
    seen: set[str] = set()
    for item in series_order:
        label = str(item).strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        selected.append(label)
        seen.add(key)
    return selected or None


def _filter_manifest_groups(groups: object, series_order: list[str] | None) -> list[dict[str, Any]] | None:
    if not series_order or not isinstance(groups, list | tuple):
        return None
    ordered: list[dict[str, Any]] = []
    used: set[int] = set()
    for label in series_order:
        for index, group in enumerate(groups):
            if index in used or not isinstance(group, dict):
                continue
            if str(group.get("sample") or "").strip() != label:
                continue
            ordered.append(dict(group))
            used.add(index)
            break
    return ordered or None


def _experiment_template(experiment: dict[str, Any]) -> str | None:
    template = experiment.get("template")
    return str(template).strip() if isinstance(template, str) and template.strip() else None


def _experiment_render_options(experiment: dict[str, Any]) -> dict[str, Any]:
    options = experiment.get("render_options")
    return dict(options) if isinstance(options, dict) else {}


def _selected_column_confirmations(column_confirmations: object) -> list[dict[str, Any]]:
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
            confirmed_type = str(column.get("confirmed_type") or column.get("type") or "auto").strip()
            role = str(column.get("role") or "auto").strip()
            columns.append(
                {
                    "index": column_index,
                    "name": str(column.get("name") or f"Column {column_index + 1}"),
                    "inferred_type": str(column.get("inferred_type") or "auto"),
                    "confirmed_type": confirmed_type if confirmed_type in _COLUMN_TYPES else "auto",
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
) -> dict[str, Any]:
    data_type, experiment = _catalog_item(data_type_id, experiment_type_id)
    cleaned_groups = [group for group in groups if group.sample.strip() and group.files]
    if not cleaned_groups:
        raise ValueError("At least one named sample group with files is required.")

    series_order = [group.sample.strip() for group in cleaned_groups]
    project_slug = slug(project_name or f"{experiment['label']}_{'_'.join(group.sample for group in cleaned_groups)}")
    output_root = output_root.expanduser().resolve()
    project_dir = unique_path(output_root, project_slug)
    project_slug = project_dir.name
    raw_dir = project_dir / "raw"
    source_dir = project_dir / "source"
    runs_dir = project_dir / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    manifest_groups: list[dict[str, Any]] = []
    for group in cleaned_groups:
        sample = group.sample.strip()
        sample_dir = raw_dir / slug(sample)
        sample_dir.mkdir(parents=True, exist_ok=True)
        group_files: list[dict[str, Any]] = []
        for incoming in group.files:
            raw_path = unique_path(sample_dir, safe_filename(incoming.name))
            raw_path.write_bytes(incoming.content)
            source_name = safe_filename(f"{sample}__{raw_path.name}")
            source_path = unique_path(source_dir, source_name)
            source_path.write_bytes(incoming.content)
            group_files.append(
                {
                    "original_name": incoming.name,
                    "raw_path": str(raw_path),
                    "source_path": str(source_path),
                    "size_bytes": len(incoming.content),
                    "sha256": hashlib.sha256(incoming.content).hexdigest(),
                }
            )
        manifest_groups.append({"sample": sample, "files": group_files})

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
    template = _experiment_template(experiment)
    if template is None:
        semantic_template = recognition_payload.get("template")
        if isinstance(semantic_template, str) and semantic_template.strip():
            template = semantic_template.strip()
    contract_template = template
    if contract_template is None and isinstance(experiment.get("chart"), str):
        contract_template = str(experiment.get("chart") or "").strip() or None
    semantic_render_options = (
        dict(recognition_payload.get("render_options"))
        if isinstance(recognition_payload.get("render_options"), dict)
        else {}
    )
    explicit_user_render_options = _selected_render_options(render_options, template=contract_template)
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
    axis_plan = recognition_payload.get("axis_plan") if isinstance(recognition_payload.get("axis_plan"), dict) else {}
    for axis_name, option_name in (("x", "x_label_override"), ("y", "y_label_override")):
        axis_payload = axis_plan.get(axis_name) if isinstance(axis_plan.get(axis_name), dict) else {}
        display_label = axis_payload.get("display_label")
        if isinstance(display_label, str) and display_label.strip():
            selected_render_options.setdefault(option_name, display_label.strip())
    selected_render_options.setdefault("series_order", series_order)
    selected_column_confirmations = _selected_column_confirmations(column_confirmations)
    selected_replicate_mode = _selected_replicate_mode(
        replicate_mode if replicate_mode is not None else experiment.get("default_replicate_mode")
    )
    plot_request = {
        "recipe": "auto",
        "input": str(source_dir),
        "output": str(selected_output),
        "exports": selected_exports,
        "series_order": series_order,
        "replicate_mode": selected_replicate_mode,
        "review_notes": ["Prepared by SciPlot from the selected data mapping."],
    }
    if selected_render_options:
        plot_request["render_options"] = selected_render_options
    plot_request["explicit_render_option_keys"] = sorted(explicit_user_render_options)
    if template:
        plot_request["template"] = template
    if rule_id:
        plot_request["rule_id"] = rule_id
    if selected_column_confirmations:
        plot_request["column_confirmations"] = selected_column_confirmations

    created_at = datetime.now(UTC).isoformat()
    warnings = _duplicate_source_warnings(manifest_groups)
    if warnings:
        plot_request["review_notes"].extend(str(item["message"]) for item in warnings)
    study_model = build_study_model(
        data_type=data_type,
        experiment=experiment,
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
    launcher_path = _write_project_launcher(project_dir, project_slug=project_slug)
    manifest = {
        "kind": "sciplot_intake_project",
        "version": 1,
        "created_at": created_at,
        "project_name": project_name,
        "project_slug": project_slug,
        "data_type": {"id": data_type["id"], "label": data_type["label"]},
        "experiment": {
            "id": experiment["id"],
            "label": experiment["label"],
            "rule_id": rule_id,
            "chart": experiment.get("chart"),
            "template": template,
        },
        "recognition": json_safe(recognition_payload),
        "groups": manifest_groups,
        "warnings": warnings,
        "source_dir": str(source_dir),
        "plot_request": str(project_dir / "plot_request.json"),
        "outputs_dir": str(selected_output),
        "launcher": launcher_path,
        "study_model": study_model,
        "publication_intent": publication_intent,
        "transform_ledger": transform_ledger,
        "journal_profile": get_publication_profile(publication_intent["target_profile_id"]),
        "column_confirmations": selected_column_confirmations,
        "plot_options": {
            "output": str(selected_output),
            "exports": selected_exports,
            "render_options": selected_render_options,
            "series_order": series_order,
            "replicate_mode": selected_replicate_mode,
        },
    }
    (project_dir / "plot_request.json").write_text(
        json.dumps(json_safe(plot_request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        from sciplot_core.studio import prepare_studio_document

        studio_payload = prepare_studio_document(project_dir)
        if isinstance(studio_payload.get("studio"), dict):
            manifest["studio"] = studio_payload["studio"]
        prepared_request = _read_json_if_exists(project_dir / "plot_request.json")
        if isinstance(prepared_request, dict):
            for key in ("study_model", "publication_intent", "transform_ledger"):
                if isinstance(prepared_request.get(key), dict):
                    manifest[key] = prepared_request[key]
            intent = prepared_request.get("publication_intent")
            if isinstance(intent, dict) and isinstance(intent.get("target_profile_id"), str):
                manifest["journal_profile"] = get_publication_profile(intent["target_profile_id"])
    except Exception as exc:
        manifest["studio"] = {
            "kind": "sciplot_studio_document",
            "engine": "veusz",
            "status": "blocked",
            "state": str(getattr(exc, "state", "needs_rule_repair")),
            "reason_code": str(getattr(exc, "reason_code", "studio_preparation_failed")),
            "error": str(exc),
        }
    (project_dir / "intake_manifest.json").write_text(
        json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (project_dir / f"{project_slug}.sciplot.json").write_text(
        json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    zip_path = output_root / f"{project_slug}.zip"
    _write_zip(project_dir, zip_path)
    return {
        **manifest,
        "project_dir": str(project_dir),
        "zip_path": str(zip_path),
        "download_name": zip_path.name,
    }


def create_and_run_intake_project(
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
) -> dict[str, Any]:
    from sciplot_core.workflow import run_request

    project = create_intake_project(
        project_name=project_name,
        data_type_id=data_type_id,
        experiment_type_id=experiment_type_id,
        groups=groups,
        output_root=output_root,
        plot_output=plot_output,
        exports=exports,
        render_options=render_options,
        column_confirmations=column_confirmations,
        replicate_mode=replicate_mode,
    )
    project_dir = Path(str(project["project_dir"]))
    plot_request_path = Path(str(project["plot_request"]))
    try:
        manifest = run_request(plot_request_path)
    except Exception as exc:
        intake_manifest = json.loads((project_dir / "intake_manifest.json").read_text(encoding="utf-8"))
        request = json.loads(plot_request_path.read_text(encoding="utf-8"))
        run_output = Path(str(request.get("output") or intake_manifest.get("outputs_dir")))
        intervention = run_output / "intervention_request.json"
        cleanup_request = _write_render_failure_cleanup_request(
            run_output=run_output,
            request=request,
            request_path=plot_request_path,
            intervention=intervention,
        )
        failed_run = {
            "failed_at": datetime.now(UTC).isoformat(),
            "output": str(run_output),
            "figures": [],
            "analysis_metrics": [],
            "qa": {},
            "failure": str(exc),
            "operation_mode": assisted_cleanup_mode_payload(reason="render_failure"),
            "needs_assisted_cleanup": True,
            "needs_codex": True,
            "intervention_request": str(intervention) if intervention.exists() else None,
            "assisted_cleanup_request": cleanup_request,
        }
        intake_manifest["last_run"] = failed_run
        intake_manifest["run_failed"] = True
        intake_manifest["failure"] = str(exc)
        (project_dir / "intake_manifest.json").write_text(
            json.dumps(json_safe(intake_manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for path in sorted(project_dir.glob("*.sciplot.json")):
            path.write_text(json.dumps(json_safe(intake_manifest), indent=2, ensure_ascii=False), encoding="utf-8")
        refreshed_zip = refresh_intake_project_zip(project_dir)
        return {
            **project,
            **intake_manifest,
            "project_dir": str(project_dir),
            "zip_path": str(refreshed_zip),
            "download_name": refreshed_zip.name,
            "last_run": failed_run,
        }
    intake_manifest = json.loads((project_dir / "intake_manifest.json").read_text(encoding="utf-8"))
    refreshed_zip = refresh_intake_project_zip(project_dir)
    return {
        **project,
        **intake_manifest,
        "project_dir": str(project_dir),
        "zip_path": str(refreshed_zip),
        "download_name": refreshed_zip.name,
        "last_run": intake_manifest.get("last_run", manifest),
    }


def _write_intake_manifest(project_dir: Path, manifest: dict[str, Any]) -> None:
    (project_dir / "intake_manifest.json").write_text(
        json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    for path in sorted(project_dir.glob("*.sciplot.json")):
        path.write_text(json.dumps(json_safe(manifest), indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_project_plot_request(project_dir: Path, manifest: dict[str, Any]) -> Path:
    request_value = str(manifest.get("plot_request") or "plot_request.json")
    request_path = Path(request_value).expanduser()
    if not request_path.is_absolute():
        request_path = project_dir / request_path
    request_path = request_path.resolve()
    if not _path_within(request_path, project_dir):
        raise PermissionError("Plot request must belong to the intake project.")
    return request_path


def _load_intake_project_request(project_dir: str | Path) -> IntakeProjectRequest:
    project_path = Path(project_dir).expanduser().resolve()
    manifest_path = project_path / "intake_manifest.json"
    manifest = _read_json_if_exists(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"No intake project manifest found at {manifest_path}.")
    request_path = _resolve_project_plot_request(project_path, manifest)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Plot request must be a JSON object.")
    return IntakeProjectRequest(
        project_dir=project_path,
        manifest=manifest,
        request_path=request_path,
        request=request,
    )


def _project_template_for_contract(
    project_dir: Path,
    intake_manifest: dict[str, Any],
    request: dict[str, Any],
) -> str | None:
    template = request.get("template")
    if isinstance(template, str) and template.strip():
        return template.strip()
    last_run = intake_manifest.get("last_run") if isinstance(intake_manifest.get("last_run"), dict) else {}
    output = last_run.get("output") or intake_manifest.get("outputs_dir")
    if isinstance(output, str) and output.strip():
        manifest_path = Path(output).expanduser()
        if not manifest_path.is_absolute():
            manifest_path = project_dir / manifest_path
        run_manifest = _read_json_if_exists(manifest_path / "manifest.json") or {}
        result = run_manifest.get("result") if isinstance(run_manifest.get("result"), dict) else {}
        result_template = result.get("template")
        if isinstance(result_template, str) and result_template.strip():
            return result_template.strip()
    experiment = intake_manifest.get("experiment") if isinstance(intake_manifest.get("experiment"), dict) else {}
    for key in ("template", "chart"):
        value = experiment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def apply_intake_project(
    project_dir: str | Path,
    *,
    exports: list[str] | tuple[str, ...] | None = None,
    render_options: dict[str, Any] | None = None,
    clear_render_options: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
    series_order: list[str] | tuple[str, ...] | None = None,
    review_note: str | None = None,
) -> dict[str, Any]:
    project = _load_intake_project_request(project_dir)
    intake_manifest = project.manifest
    template = _project_template_for_contract(project.project_dir, intake_manifest, project.request)
    patched_request = apply_request_patch(
        project.request,
        exports=exports,
        render_options=render_options,
        clear_render_options=clear_render_options,
        split_policy=split_policy,
        series_order=series_order,
        template=template,
        review_note=review_note,
    )
    project.request_path.write_text(
        json.dumps(json_safe(patched_request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    render_patch = (
        patched_request.get("render_options")
        if isinstance(patched_request.get("render_options"), dict)
        else {}
    )
    selected_series = _selected_series_order(patched_request.get("series_order"))
    plot_options = intake_manifest.get("plot_options") if isinstance(intake_manifest.get("plot_options"), dict) else {}
    intake_manifest["plot_options"] = {
        **plot_options,
        "exports": patched_request.get("exports", list(DEFAULT_EXPORT_FORMATS_POLICY)),
        "render_options": render_patch,
        **(
            {"split_policy": patched_request["split_policy"]}
            if isinstance(patched_request.get("split_policy"), dict)
            else {}
        ),
        **({"series_order": selected_series} if selected_series is not None else {}),
    }
    filtered_groups = _filter_manifest_groups(intake_manifest.get("groups"), selected_series)
    if filtered_groups is not None:
        intake_manifest["groups"] = filtered_groups
    patched_study_model = patched_request.get("study_model")
    if isinstance(patched_study_model, dict):
        intake_manifest["study_model"] = sync_study_model_samples(
            patched_study_model,
            sample_order=selected_series,
        )
    _write_intake_manifest(project.project_dir, intake_manifest)
    refreshed_zip = refresh_intake_project_zip(project.project_dir)
    return {
        **intake_manifest,
        "project_dir": str(project.project_dir),
        "zip_path": str(refreshed_zip),
        "download_name": refreshed_zip.name,
        "last_run": intake_manifest.get("last_run", {}),
    }


def rerun_intake_project(
    project_dir: str | Path,
    *,
    exports: list[str] | tuple[str, ...] | None = None,
    render_options: dict[str, Any] | None = None,
    clear_render_options: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
    series_order: list[str] | tuple[str, ...] | None = None,
    review_note: str | None = None,
) -> dict[str, Any]:
    from sciplot_core.workflow import run_request

    project_path = Path(project_dir).expanduser().resolve()
    applied = apply_intake_project(
        project_path,
        exports=exports,
        render_options=render_options,
        clear_render_options=clear_render_options,
        split_policy=split_policy,
        series_order=series_order,
        review_note=review_note,
    )
    project = _load_intake_project_request(project_path)
    intake_manifest = project.manifest

    try:
        run_manifest = run_request(project.request_path)
    except Exception as exc:
        run_output_value = (
            project.request.get("output")
            or intake_manifest.get("outputs_dir")
            or project_path / "runs" / "run_001"
        )
        run_output = Path(str(run_output_value))
        intervention = run_output / "intervention_request.json"
        cleanup_request = _write_render_failure_cleanup_request(
            run_output=run_output,
            request=project.request,
            request_path=project.request_path,
            intervention=intervention,
        )
        failed_run = {
            "failed_at": datetime.now(UTC).isoformat(),
            "output": str(run_output),
            "figures": [],
            "analysis_metrics": [],
            "qa": {},
            "failure": str(exc),
            "operation_mode": assisted_cleanup_mode_payload(reason="render_failure"),
            "needs_assisted_cleanup": True,
            "needs_codex": True,
            "intervention_request": str(intervention) if intervention.exists() else None,
            "assisted_cleanup_request": cleanup_request,
        }
        intake_manifest = _read_json_if_exists(project_path / "intake_manifest.json") or intake_manifest
        intake_manifest["last_run"] = failed_run
        intake_manifest["run_failed"] = True
        intake_manifest["failure"] = str(exc)
        _write_intake_manifest(project_path, intake_manifest)
        refreshed_zip = refresh_intake_project_zip(project_path)
        return {
            **intake_manifest,
            "project_dir": str(project_path),
            "zip_path": str(refreshed_zip),
            "download_name": refreshed_zip.name,
            "last_run": failed_run,
        }

    intake_manifest = _read_json_if_exists(project_path / "intake_manifest.json") or intake_manifest
    intake_manifest.pop("run_failed", None)
    intake_manifest.pop("failure", None)
    _write_intake_manifest(project_path, intake_manifest)
    _prepare_studio_project_package(project_path)
    refreshed_zip = refresh_intake_project_zip(project_path)
    return {
        **applied,
        **intake_manifest,
        "project_dir": str(project_path),
        "zip_path": str(refreshed_zip),
        "download_name": refreshed_zip.name,
        "last_run": intake_manifest.get("last_run", run_manifest),
    }


def _decode_group_payload(payload: dict[str, Any]) -> list[IntakeGroupInput]:
    groups: list[IntakeGroupInput] = []
    for group in payload.get("groups", []):
        sample = str(group.get("sample") or "").strip()
        files: list[IncomingFile] = []
        for item in group.get("files", []):
            name = str(item.get("name") or "file")
            source_path = str(item.get("source_path") or "").strip()
            if source_path:
                path = Path(source_path).expanduser()
                files.append(IncomingFile(name=name or path.name, content=path.read_bytes()))
            else:
                content_base64 = str(item.get("content_base64") or "")
                if "," in content_base64:
                    content_base64 = content_base64.split(",", 1)[1]
                files.append(IncomingFile(name=name, content=base64.b64decode(content_base64)))
        groups.append(IntakeGroupInput(sample=sample, files=tuple(files)))
    return groups


class _IntakeHandler(BaseHTTPRequestHandler):
    server: _IntakeServer

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _project_dir_from_request(self, project_slug: str) -> Path:
        return _project_dir_fromslug(self.server.output_root, unquote(project_slug))

    def _respond_error(self, exc: Exception) -> None:
        detail = str(exc) or type(exc).__name__
        if isinstance(exc, FileNotFoundError):
            self._send_json(
                {"error": detail, "code": "not_found", "hint": "The requested resource was not found."},
                status=HTTPStatus.NOT_FOUND,
            )
        elif isinstance(exc, PermissionError):
            self._send_json({"error": detail, "code": "forbidden"}, status=HTTPStatus.FORBIDDEN)
        elif isinstance(exc, (ValueError, TypeError)):
            self._send_json({"error": detail, "code": "invalid_input"}, status=HTTPStatus.BAD_REQUEST)
        elif isinstance(exc, OSError):
            self._send_json({"error": detail, "code": "io_error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        else:
            self._send_json({"error": detail, "code": "internal_error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(_STATIC_DIR / "index.html")
            return
        if parsed.path == "/api/catalog":
            query = parse_qs(parsed.query)
            include_pending = query.get("all", ["0"])[0] in {"1", "true", "yes"}
            self._send_json(intake_catalog_payload(include_pending=include_pending))
            return
        if parsed.path.startswith("/api/session/"):
            session_id = safe_filename(unquote(parsed.path.rsplit("/", 1)[-1]))
            self._send_file(self.server.output_root / "sessions" / f"{session_id}.json")
            return
        if parsed.path == "/api/session":
            query = parse_qs(parsed.query)
            session_id = safe_filename(query.get("id", [""])[0])
            self._send_file(self.server.output_root / "sessions" / f"{session_id}.json")
            return
        if parsed.path == "/api/projects":
            query = parse_qs(parsed.query)
            search = str(query.get("search", [""])[0]).strip().lower()
            all_projects = list_intake_projects(self.server.output_root)
            if search:
                all_projects = [
                    p for p in all_projects
                    if search in p["slug"].lower() or search in str(p.get("project_name", "")).lower()
                ]
            self._send_json({"kind": "sciplot_project_list", "projects": all_projects})
            return
        if parsed.path.startswith("/api/download/"):
            filename = safe_filename(unquote(parsed.path.rsplit("/", 1)[-1]))
            self._send_file(self.server.output_root / filename)
            return
        if parsed.path.startswith("/api/projects/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 4 and parts[0] == "api" and parts[1] == "projects":
                project_dir = self._project_dir_from_request(parts[2])
                try:
                    if parts[3] == "status":
                        self._send_json(intake_project_status(project_dir))
                        return
                    if parts[3] == "artifact":
                        query = parse_qs(parsed.query)
                        artifact_path = query.get("path", [""])[0]
                        artifact = _resolve_project_artifact(project_dir, artifact_path)
                        self._send_file(artifact)
                        return
                except PermissionError as exc:
                    self.send_error(HTTPStatus.FORBIDDEN, str(exc))
                    return
                except FileNotFoundError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                except ValueError as exc:
                    self._respond_error(exc)
                    return
        if parsed.path.startswith("/api/codex/jobs/"):
            parts = parsed.path.strip("/").split("/")
            query = parse_qs(parsed.query)
            project_slug = query.get("project", [""])[0]
            if len(parts) >= 4 and project_slug:
                try:
                    project_dir = self._project_dir_from_request(project_slug)
                    job_dir = project_dir / "codex_jobs" / safe_filename(unquote(parts[3]))
                    if len(parts) == 5 and parts[4] == "logs":
                        stdout_path = job_dir / "stdout.jsonl"
                        self._send_text(stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else "")
                        return
                    self._send_json(load_codex_job(job_dir))
                    return
                except (FileNotFoundError, OSError):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                except PermissionError as exc:
                    self.send_error(HTTPStatus.FORBIDDEN, str(exc))
                    return
        if parsed.path == "/api/reveal":
            query = parse_qs(parsed.query)
            target = str(query.get("path", [""])[0])
            if not target:
                self._send_json({"error": "Path required"}, status=HTTPStatus.BAD_REQUEST)
                return
            target_path = Path(target).expanduser().resolve()
            if not target_path.exists():
                self._send_json({"error": f"Path not found: {target_path}"}, status=HTTPStatus.NOT_FOUND)
                return
            if not _path_within(target_path, self.server.output_root.expanduser().resolve()):
                raise PermissionError("Reveal path is outside the configured output root.")
            import subprocess

            subprocess.Popen(["open", str(target_path)])
            self._send_json({"revealed": str(target_path)})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/table-preview":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                source_path = str(payload.get("source_path") or "").strip()
                content_base64 = str(payload.get("content_base64") or "")
                content: bytes | None = None
                if content_base64:
                    if "," in content_base64:
                        content_base64 = content_base64.split(",", 1)[1]
                    content = base64.b64decode(content_base64)
                preview = preview_table_payload(
                    name=str(payload.get("name") or Path(source_path).name or "table"),
                    content=content,
                    source_path=source_path or None,
                )
            except Exception as exc:
                self._respond_error(exc)
                return
            self._send_json(preview)
            return
        if parsed.path == "/api/codex/jobs":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                project_slug = str(payload.get("project_slug") or "").strip()
                project_dir_value = str(payload.get("project_dir") or "").strip()
                if project_slug:
                    project_dir = self._project_dir_from_request(project_slug)
                elif project_dir_value:
                    project_dir = Path(project_dir_value).expanduser().resolve()
                    if not _path_within(project_dir, self.server.output_root):
                        raise PermissionError("Assistant jobs must belong to an intake project.")
                else:
                    raise ValueError("Assistant job payload must include `project_slug` or `project_dir`.")
                job = start_codex_job(
                    project_dir=project_dir,
                    plot_request=payload.get("plot_request"),
                    run_output=payload.get("run_output"),
                    intervention_request=payload.get("intervention_request"),
                    failure=payload.get("failure"),
                    user_goal=payload.get("user_goal"),
                    run_async=True,
                )
            except PermissionError as exc:
                self.send_error(HTTPStatus.FORBIDDEN, str(exc))
                return
            except Exception as exc:
                self._respond_error(exc)
                return
            self._send_json(job)
            return
        if parsed.path.startswith("/api/projects/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "workbench":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    project_dir = self._project_dir_from_request(parts[2])
                    if parts[4] == "apply":
                        project = apply_intake_project(
                            project_dir,
                            exports=payload.get("exports"),
                            render_options=payload.get("render_options"),
                            clear_render_options=payload.get("clear_render_options"),
                            split_policy=payload.get("split_policy"),
                            series_order=payload.get("series_order"),
                            review_note=payload.get("review_note"),
                        )
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                except PermissionError as exc:
                    self.send_error(HTTPStatus.FORBIDDEN, str(exc))
                    return
                except Exception as exc:
                    self._respond_error(exc)
                    return
                self._send_json(project)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "rerun":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    project_dir = self._project_dir_from_request(parts[2])
                    project = rerun_intake_project(
                        project_dir,
                        exports=payload.get("exports"),
                        render_options=payload.get("render_options"),
                        clear_render_options=payload.get("clear_render_options"),
                        split_policy=payload.get("split_policy"),
                        series_order=payload.get("series_order"),
                        review_note=payload.get("review_note"),
                    )
                except PermissionError as exc:
                    self.send_error(HTTPStatus.FORBIDDEN, str(exc))
                    return
                except Exception as exc:
                    self._respond_error(exc)
                    return
                self._send_json(project)
                return
        if parsed.path != "/api/projects":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            create_project = create_and_run_intake_project if payload.get("run_after_create") else create_intake_project
            project = create_project(
                project_name=str(payload.get("project_name") or ""),
                data_type_id=str(payload.get("data_type_id") or ""),
                experiment_type_id=str(payload.get("experiment_type_id") or ""),
                groups=_decode_group_payload(payload),
                output_root=self.server.output_root,
                plot_output=payload.get("plot_output"),
                exports=payload.get("exports"),
                render_options=payload.get("render_options"),
                column_confirmations=payload.get("column_confirmations"),
                replicate_mode=payload.get("replicate_mode"),
            )
        except Exception as exc:
            self._respond_error(exc)
            return
        self._send_json(project)


class _IntakeServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])

    def __init__(self, server_address: tuple[str, int], output_root: Path):
        super().__init__(server_address, _IntakeHandler)
        self.output_root = output_root.expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)


def serve_intake(
    *,
    input_path: str | Path | None = None,
    project_slug: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    open_browser: bool = True,
) -> None:
    requested_port = port
    try:
        server = _IntakeServer((host, port), output_root)
    except OSError as exc:
        if port and getattr(exc, "errno", None) == errno.EADDRINUSE:
            server = _IntakeServer((host, 0), output_root)
        else:
            raise
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}"
    payload: dict[str, Any] = {"url": url, "output_root": str(server.output_root)}
    if requested_port and actual_port != requested_port:
        payload.update({"requested_port": requested_port, "port_fallback": True})
    if input_path is not None:
        session = prepare_intake_session(input_path, output_root=server.output_root)
        url = f"{url}?session={quote(str(session['session_id']))}"
        payload.update({"url": url, "session_path": session["session_path"], "session_id": session["session_id"]})
    elif project_slug:
        safe_project = safe_filename(project_slug)
        project_dir = _project_dir_fromslug(server.output_root, safe_project)
        if not (project_dir / "intake_manifest.json").exists():
            raise FileNotFoundError(f"No intake project manifest found for project: {project_slug}")
        url = f"{url}?project={quote(safe_project)}"
        payload.update({"url": url, "project_slug": safe_project, "project_dir": str(project_dir)})
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()


__all__ = [
    "IncomingFile",
    "IntakeGroupInput",
    "APPROVED_INTAKE_SIZE_PRESETS",
    "create_and_run_intake_project",
    "apply_intake_project",
    "create_intake_project_from_session",
    "create_intake_project",
    "intake_catalog_payload",
    "intake_project_status",
    "list_intake_projects",
    "prepare_intake_session",
    "preview_table_payload",
    "refresh_intake_project_zip",
    "rerun_intake_project",
    "serve_intake",
]
