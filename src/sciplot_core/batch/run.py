from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sciplot_core.batch.review_index import write_review_index
from sciplot_core.batch.source_discovery import (
    candidate_sources,
    is_torque_text_export,
    normalize_tensile_roots,
    semantic_priority,
)
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import slug
from sciplot_core.render import DEFAULT_EXPORT_FORMATS, inspect_payload
from sciplot_core.semantic import (
    build_intervention_request,
    classify_source,
)
from sciplot_core.workflow import run_request

_RECORDED_SKIP_SUFFIXES = {".txt", ".tif", ".tiff", ".id_tens", ".is_tens"}
_SMOKE_MAX_RUNS = 6
_MAX_RECORDED_SKIPS = 200
_SUPPORTED_MODES = {"smoke", "all"}


def _top_recommendation(inspection: dict[str, Any]) -> dict[str, Any] | None:
    recommendations = inspection.get("recommendations") or []
    if not recommendations:
        return None
    top = recommendations[0]
    return top if isinstance(top, dict) else None


def run_batch(
    input_dir: Path,
    *,
    output_dir: Path,
    mode: str = "smoke",
    tensile_roots: list[Path] | None = None,
) -> dict[str, Any]:
    if mode not in _SUPPORTED_MODES:
        raise ValueError(
            f"Unsupported batch mode `{mode}`. Supported modes: {sorted(_SUPPORTED_MODES)}."
        )
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    normalized_tensile_roots = normalize_tensile_roots(tensile_roots)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Batch input directory does not exist: {input_dir}")
    for root in normalized_tensile_roots:
        if not root.is_dir():
            raise FileNotFoundError(
                f"Tensile allow-list directory does not exist: {root}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / "runs"
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    for stale_file in (
        output_dir / "batch_manifest.json",
        output_dir / "review_index.html",
    ):
        if stale_file.exists():
            stale_file.unlink()
    runs_dir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    selected_semantic_families: set[str] = set()
    interventions: list[dict[str, Any]] = []

    all_files = sorted(
        (path for path in input_dir.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix(),
    )
    for source in all_files:
        suffix = source.suffix.lower()
        if (
            suffix in _RECORDED_SKIP_SUFFIXES
            and not is_torque_text_export(source)
            and len(skipped) < _MAX_RECORDED_SKIPS
        ):
            skipped.append(
                {"path": str(source), "reason": f"skipped_{suffix.lstrip('.')}_input"}
            )

    candidates: list[tuple[Path, dict[str, Any]]] = []
    discovered_sources, candidate_skips = candidate_sources(
        input_dir,
        all_files,
        tensile_roots=normalized_tensile_roots,
    )
    skipped.extend(candidate_skips)
    for source in discovered_sources:
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

    for source, semantic in sorted(
        candidates, key=lambda item: semantic_priority(item[1], item[0])
    ):
        if mode == "smoke" and len(runs) >= _SMOKE_MAX_RUNS:
            break
        rel_source = source.relative_to(input_dir)
        try:
            inspection = inspect_payload(source)
        except Exception as exc:
            inspection = {"error": str(exc), "sciplot_semantics": semantic}
        if "error" in inspection and not semantic.get("template"):
            skipped.append(
                {
                    "path": str(source),
                    "reason": "inspection_failed",
                    "error": inspection["error"],
                }
            )
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
        run_dir = (
            runs_dir / f"{run_index:04d}_{slug(rel_source.with_suffix('').as_posix())}"
        )
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
        request_path.write_text(
            json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8"
        )
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
                "model": str(
                    inspection.get("model")
                    or semantic.get("vendor_model")
                    or "unknown_model"
                ),
                "semantic_family": semantic_family,
                "rule_id": run_manifest.get("semantic", {}).get("rule_id")
                or semantic.get("rule_id"),
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
        "created_at": utc_now_iso(),
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
    write_review_index(output_dir, manifest=manifest)
    return manifest


__all__ = ["run_batch"]
