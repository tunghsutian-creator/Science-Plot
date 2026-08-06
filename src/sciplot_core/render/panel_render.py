"""Render one or more split panels through the Veusz worker."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.ingest import normalized_source
from sciplot_core.split import (
    build_split_plan,
    normalize_split_policy,
)
from sciplot_core.terminal_request import project_terminal_render_request
from sciplot_core.terminal_source_binding import (
    MaterializedTerminalSourceBinding,
)

from sciplot_core.render.formats import (
    _normalize_export_formats,
    _series_labels_for_split,
)

from sciplot_core.render.worker_runtime import (
    _read_json_if_exists,
    _terminal_transform_steps,
    _extend_unique_transform_steps,
)

from sciplot_core.render.target_paths import (
    _veusz_target_base,
    _render_studio_exports,
)

from sciplot_core.render.layout_report import (
    _veusz_layout_report,
)

from sciplot_core.render.export_files import (
    _copy_veusz_exports,
    _validate_export_records,
    _remove_stale_render_exports,
    _cleanup_worker_exports,
)


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
    _terminal_source_binding: MaterializedTerminalSourceBinding | None = None,
) -> tuple[
    list[Path],
    list[dict[str, Any]],
    dict[str, Any],
    Path,
    Path,
    dict[str, Any],
    list[dict[str, Any]],
]:
    panel_dir.mkdir(parents=True, exist_ok=True)
    terminal_request = project_terminal_render_request(
        template=template,
        render_options=options,
        request_context=request_context,
    )
    if _terminal_source_binding is not None and "series_order" not in terminal_request:
        terminal_request["series_order"] = list(_terminal_source_binding.sample_order)
    request = {
        "input": str(source.resolve()),
        "output": str(output_dir),
        "exports": list(export_formats),
        **terminal_request,
    }
    request_path = panel_dir / "plot_request.json"
    if _terminal_source_binding is not None:
        _terminal_source_binding.validate_request(request_path, request)
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    sealed_binding = (
        _terminal_source_binding.seal(request_path, request)
        if _terminal_source_binding is not None
        else None
    )
    payload = (
        _render_studio_exports(
            request_path,
            export_formats,
            _terminal_source_binding=sealed_binding,
        )
        if sealed_binding is not None
        else _render_studio_exports(request_path, export_formats)
    )
    outputs, export_records = _copy_veusz_exports(
        payload, output_dir=output_dir, output_base=output_base
    )
    _validate_export_records(export_records, requested=export_formats)
    document = Path(str(payload["document"]))
    spec = Path(
        str(payload.get("studio", {}).get("spec") or document.with_suffix(".spec.json"))
    )
    spec_payload = _read_json_if_exists(spec)
    transform_steps = _terminal_transform_steps(request_path)
    report = _veusz_layout_report(
        template=template,
        spec=spec_payload,
        document=document,
        outputs=outputs,
        split_panel=split_panel,
    )
    _cleanup_worker_exports(panel_dir)
    return (
        outputs,
        export_records,
        report,
        document,
        spec,
        terminal_request,
        transform_steps,
    )


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
    _terminal_source_binding: MaterializedTerminalSourceBinding | None = None,
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
    transform_steps: list[dict[str, Any]] = []
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
            panel_binding = (
                {"_terminal_source_binding": _terminal_source_binding}
                if _terminal_source_binding is not None
                else {}
            )
            (
                outputs,
                export_records,
                report,
                document,
                spec,
                terminal_request,
                panel_transform_steps,
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
                **panel_binding,
            )
            all_outputs.extend(outputs)
            all_exports.extend(export_records)
            reports.append(report)
            documents.append(str(document))
            specs.append(str(spec))
            terminal_requests.append(terminal_request)
            _extend_unique_transform_steps(
                transform_steps,
                panel_transform_steps,
            )

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
        "transform_steps": transform_steps,
    }
    if split_plan is not None:
        payload["split_plan"] = json_safe(split_plan)
    return payload
