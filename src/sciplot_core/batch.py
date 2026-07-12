from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe, slug, text_preview
from sciplot_core.render import DEFAULT_EXPORT_FORMATS, inspect_payload
from sciplot_core.semantic import (
    build_intervention_request,
    classify_source,
    is_rheology_frequency_comparison_dir,
    is_rheology_temperature_comparison_dir,
)
from sciplot_core.workflow import run_request

_TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}
_TORQUE_TEXT_SUFFIXES = {".txt", ".tsv"}
_RECORDED_SKIP_SUFFIXES = {".txt", ".tif", ".tiff", ".id_tens", ".is_tens"}
_SMOKE_MAX_RUNS = 6
_MAX_RECORDED_SKIPS = 200
_SUPPORTED_MODES = {"smoke", "all"}
_SMOKE_SEMANTIC_PRIORITY = {
    "impact_metric": 0,
    "rheology_frequency": 1,
    "rheology_temperature_sweep": 2,
    "rheology_creep": 3,
    "rheology_stress_relaxation": 4,
    "tensile_curve": 5,
    "ftir_spectrum": 6,
    "torque_curve": 7,
    "generic_replicate": 8,
    "generic_curve": 9,
}


def _top_recommendation(inspection: dict[str, Any]) -> dict[str, Any] | None:
    recommendations = inspection.get("recommendations") or []
    if not recommendations:
        return None
    top = recommendations[0]
    return top if isinstance(top, dict) else None


def _smoke_priority(path: Path) -> tuple[int, str]:
    text = path.as_posix().lower()
    if "impact" in text:
        return (0, text)
    if "流变" in text or "rheology" in text or "pinlv" in text or "/freq/" in text:
        return (1, text)
    if "tensile" in text:
        return (2, text)
    return (3, text)


def _is_tensile_export_dir(path: Path) -> bool:
    return path.is_dir() and path.name.casefold().endswith(".is_tens_exports")


def _is_under_tensile_export_dir(path: Path) -> bool:
    return any(parent.name.casefold().endswith(".is_tens_exports") for parent in path.parents)


def _is_tensile_related(path: Path) -> bool:
    text = path.as_posix().casefold()
    return (
        "/tensile/" in text
        or "/拉伸/" in text
        or path.name.casefold().endswith(".is_tens_exports")
        or _is_under_tensile_export_dir(path)
    )


def _is_torque_text_export(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in _TORQUE_TEXT_SUFFIXES:
        return False
    path_text = path.as_posix().casefold()
    if "torque" in path_text or "转矩" in path_text:
        return True
    try:
        preview = text_preview(path).casefold()
    except Exception:
        return False
    return "screw torque" in preview or "screwtorque" in preview or "转矩" in preview


def _is_under_any_root(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _is_under_any_dir(path: Path, dirs: tuple[Path, ...]) -> bool:
    return any(path == directory or directory in path.parents for directory in dirs)


def _normalize_tensile_roots(values: list[Path] | None) -> tuple[Path, ...]:
    if not values:
        return ()
    return tuple(path.expanduser().resolve() for path in values)


def _candidate_sources(
    input_dir: Path,
    all_files: list[Path],
    *,
    tensile_roots: tuple[Path, ...] = (),
) -> tuple[list[Path], list[dict[str, Any]]]:
    skipped: list[dict[str, Any]] = []
    rheology_comparison_dirs = tuple(
        sorted(
            (
                path
                for path in [input_dir, *input_dir.rglob("*")]
                if path.is_dir()
                and (
                    is_rheology_frequency_comparison_dir(path)
                    or is_rheology_temperature_comparison_dir(path)
                )
            ),
            key=lambda path: path.as_posix(),
        )
    )
    tensile_dirs = sorted(
        (path for path in input_dir.rglob("*") if _is_tensile_export_dir(path)),
        key=lambda path: path.as_posix(),
    )
    table_files = sorted(
        (
            path
            for path in all_files
            if (path.suffix.lower() in _TABLE_SUFFIXES or _is_torque_text_export(path))
            and not _is_under_tensile_export_dir(path)
            and not _is_under_any_dir(path, rheology_comparison_dirs)
        ),
        key=_smoke_priority,
    )
    for path in all_files:
        if path.suffix.lower() in _TABLE_SUFFIXES and _is_under_any_dir(path, rheology_comparison_dirs):
            skipped.append({"path": str(path), "reason": "covered_by_rheology_sweep_comparison_dir"})
    candidates: list[Path] = []
    seen: set[Path] = set()
    for path in sorted([*rheology_comparison_dirs, *tensile_dirs, *table_files], key=_smoke_priority):
        if path in seen:
            continue
        seen.add(path)
        if tensile_roots and _is_tensile_related(path) and not _is_under_any_root(path, tensile_roots):
            skipped.append(
                {
                    "path": str(path),
                    "reason": "tensile_outside_allowed_roots",
                }
            )
            continue
        candidates.append(path)
    return candidates, skipped


def _semantic_priority(semantic: dict[str, Any], source: Path) -> tuple[int, str]:
    family = str(semantic.get("semantic_family") or "unknown")
    return (
        _SMOKE_SEMANTIC_PRIORITY.get(family, int(semantic.get("rule_priority") or 99)),
        source.as_posix(),
    )


def _write_review_index(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    run_items = []
    for run in manifest.get("runs", []):
        run_output = Path(str(run["output"]))
        rel = run_output.relative_to(output_dir) if run_output.is_relative_to(output_dir) else run_output
        review = rel / "review.html"
        rule_id = run.get("rule_id") or run.get("semantic_family") or "unknown"
        run_items.append(
            "<li>"
            f"<a href=\"{escape(str(review))}\">{escape(str(run.get('label', run_output.name)))}</a>"
            f" <code>{escape(str(rule_id))}</code>"
            f" <code>{escape(str(run.get('model', 'unknown')))}</code>"
            "</li>"
        )
    skipped_count = len(manifest.get("skipped", []))
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Batch Review</title>",
            "<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Batch Review</h1>",
            f"<p>Runs: {len(run_items)}; skipped: {skipped_count}</p>",
            "<ul>",
            *run_items,
            "</ul>",
            "</body>",
            "</html>",
        ]
    )
    (output_dir / "review_index.html").write_text(html + "\n", encoding="utf-8")


def run_batch(
    input_dir: Path,
    *,
    output_dir: Path,
    mode: str = "smoke",
    tensile_roots: list[Path] | None = None,
) -> dict[str, Any]:
    if mode not in _SUPPORTED_MODES:
        raise ValueError(f"Unsupported batch mode `{mode}`. Supported modes: {sorted(_SUPPORTED_MODES)}.")
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    normalized_tensile_roots = _normalize_tensile_roots(tensile_roots)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Batch input directory does not exist: {input_dir}")
    for root in normalized_tensile_roots:
        if not root.is_dir():
            raise FileNotFoundError(f"Tensile allow-list directory does not exist: {root}")

    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / "runs"
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    for stale_file in (output_dir / "batch_manifest.json", output_dir / "review_index.html"):
        if stale_file.exists():
            stale_file.unlink()
    runs_dir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    selected_semantic_families: set[str] = set()
    interventions: list[dict[str, Any]] = []

    all_files = sorted((path for path in input_dir.rglob("*") if path.is_file()), key=lambda path: path.as_posix())
    for source in all_files:
        suffix = source.suffix.lower()
        if (
            suffix in _RECORDED_SKIP_SUFFIXES
            and not _is_torque_text_export(source)
            and len(skipped) < _MAX_RECORDED_SKIPS
        ):
            skipped.append({"path": str(source), "reason": f"skipped_{suffix.lstrip('.')}_input"})

    candidates: list[tuple[Path, dict[str, Any]]] = []
    candidate_sources, candidate_skips = _candidate_sources(
        input_dir,
        all_files,
        tensile_roots=normalized_tensile_roots,
    )
    skipped.extend(candidate_skips)
    for source in candidate_sources:
        semantic = classify_source(source)
        if semantic.get("needs_ai_intervention"):
            interventions.append(
                build_intervention_request(
                    input_path=source,
                    output_dir=output_dir,
                    semantic=semantic,
                    error=str(semantic.get("vendor_error") or ""),
                )
            )
            continue
        candidates.append((source, semantic))

    for source, semantic in sorted(candidates, key=lambda item: _semantic_priority(item[1], item[0])):
        if mode == "smoke" and len(runs) >= _SMOKE_MAX_RUNS:
            break
        rel_source = source.relative_to(input_dir)
        try:
            inspection = inspect_payload(source)
        except Exception as exc:
            inspection = {"error": str(exc), "sciplot_semantics": semantic}
        if "error" in inspection and not semantic.get("template"):
            skipped.append({"path": str(source), "reason": "inspection_failed", "error": inspection["error"]})
            continue
        if "error" in inspection:
            recommendation = None
        else:
            recommendation = _top_recommendation(inspection)
        if recommendation is None and not semantic.get("template"):
            skipped.append({"path": str(source), "reason": "no_plot_recommendation"})
            continue
        semantic_family = str(semantic.get("semantic_family") or "unknown")
        if mode == "smoke" and semantic_family in selected_semantic_families:
            skipped.append(
                {
                    "path": str(source),
                    "reason": "smoke_duplicate_semantic_family",
                    "semantic_family": semantic_family,
                }
            )
            continue

        run_index = len(runs) + 1
        run_dir = runs_dir / f"{run_index:04d}_{slug(rel_source.with_suffix('').as_posix())}"
        request = {
            "recipe": "auto",
            "input": str(source),
            "output": str(run_dir),
            "exports": list(DEFAULT_EXPORT_FORMATS),
            "review_notes": [
                f"Batch {mode} selected `{rel_source}`.",
                f"Detected semantic family `{semantic_family}`.",
            ],
        }
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "plot_request.json"
        request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            run_manifest = run_request(request_path)
        except Exception as exc:
            interventions.append(
                build_intervention_request(
                    input_path=source,
                    output_dir=run_dir,
                    semantic=semantic,
                    request=request,
                    error=str(exc),
                )
            )
            continue
        selected_semantic_families.add(semantic_family)
        runs.append(
            {
                "label": rel_source.as_posix(),
                "source": str(source),
                "output": str(run_dir),
                "request_path": str(request_path),
                "model": str(inspection.get("model") or semantic.get("vendor_model") or "unknown_model"),
                "semantic_family": semantic_family,
                "rule_id": run_manifest.get("semantic", {}).get("rule_id") or semantic.get("rule_id"),
                "final_recipe": run_manifest.get("final_recipe"),
                "template": run_manifest.get("result", {}).get("template")
                or (recommendation or {}).get("template_id")
                or semantic.get("template"),
                "render_engine": run_manifest.get("render_engine"),
                "qa_target": run_manifest.get("qa_target"),
                "veusz_documents": run_manifest.get("veusz_documents", []),
                "veusz_specs": run_manifest.get("veusz_specs", []),
                "manifest": str(run_dir / "manifest.json"),
                "raw_archive": run_manifest.get("raw_archive"),
                "figures": run_manifest.get("figures", []),
            }
        )

    manifest = {
        "kind": "sciplot_batch",
        "created_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "tensile_roots": [str(path) for path in normalized_tensile_roots],
        "runs": json_safe(runs),
        "skipped": json_safe(skipped),
        "interventions": json_safe(interventions),
    }
    (output_dir / "batch_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_review_index(output_dir, manifest=manifest)
    return manifest


__all__ = ["run_batch"]
