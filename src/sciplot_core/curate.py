from __future__ import annotations

import json
import webbrowser
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.intake import create_intake_project_from_session, prepare_intake_session, refresh_intake_project_zip
from sciplot_core.semantic import (
    _apply_torque_selection,
    _auto_torque_event_selection,
    _compact_torque_sample_labels,
    _read_torque_full_series,
    _torque_source_files,
    _write_curve_table,
)


def _project_relative(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _sample_points(points: tuple[tuple[float, float], ...], *, limit: int = 1200) -> list[list[float]]:
    if len(points) <= limit:
        return [[float(x_value), float(y_value)] for x_value, y_value in points]
    stride = max(1, len(points) // limit)
    return [[float(x_value), float(y_value)] for x_value, y_value in points[::stride]]


def _write_torque_review_html(
    path: Path,
    *,
    project_name: str,
    selection: dict[str, Any],
    preview_series: list[dict[str, Any]],
) -> None:
    data_json = json.dumps(
        {"selection": selection, "series": preview_series},
        ensure_ascii=False,
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SciPlot Torque Curation</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f5f7;
      --surface: rgba(255,255,255,.86);
      --line: rgba(60,60,67,.18);
      --text: #1d1d1f;
      --muted: #6e6e73;
      --accent: #007aff;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); }}
    main {{ width: min(1180px, calc(100vw - 40px)); margin: 24px auto; display: grid; gap: 18px; }}
    header, section {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 18px 50px rgba(0,0,0,.08);
    }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .plot-wrap {{ overflow-x: auto; }}
    svg {{ width: 100%; min-width: 900px; height: 430px; background: #fff; border-radius: 12px; }}
    textarea {{
      width: 100%;
      min-height: 220px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      font: 12px ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    button {{
      height: 36px;
      border: 0;
      border-radius: 10px;
      padding: 0 14px;
      color: white;
      background: var(--accent);
      font: inherit;
      cursor: pointer;
    }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid var(--line); border-radius: 12px; padding: 12px; background: #fff; }}
    code {{ font-size: 12px; overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{escape(project_name)}</h1>
      <div class="muted">Torque event curation</div>
    </header>
    <section>
      <div id="cards" class="grid"></div>
    </section>
    <section class="plot-wrap">
      <svg id="plot" viewBox="0 0 1100 430" role="img" aria-label="Torque curation preview"></svg>
    </section>
    <section>
      <textarea id="selection"></textarea>
      <p><button id="download">Download selection JSON</button></p>
    </section>
  </main>
  <script>
    const payload = {data_json};
    const textarea = document.getElementById('selection');
    textarea.value = JSON.stringify(payload.selection, null, 2);
    const cards = document.getElementById('cards');
    payload.selection.samples.forEach(item => {{
      const div = document.createElement('div');
      div.className = 'card';
      div.innerHTML = `<strong>${{item.sample}}</strong><br>
        <span class="muted">
          start ${{item.start_s}} s · peak ${{item.feed_peak_s}} s ·
          drop ${{item.discharge_drop_s}} s · end ${{item.end_s}} s
        </span><br>
        <code>${{item.source_path}}</code>`;
      cards.appendChild(div);
    }});
    const svg = document.getElementById('plot');
    const pad = {{l: 64, r: 24, t: 24, b: 54}};
    const width = 1100 - pad.l - pad.r;
    const height = 430 - pad.t - pad.b;
    const all = payload.series.flatMap(s => s.points);
    const xmin = Math.min(...all.map(p => p[0]));
    const xmax = Math.max(...all.map(p => p[0]));
    const ymin = Math.min(...all.map(p => p[1]));
    const ymax = Math.max(...all.map(p => p[1]));
    const sx = x => pad.l + (x - xmin) / Math.max(1, xmax - xmin) * width;
    const sy = y => pad.t + height - (y - ymin) / Math.max(1, ymax - ymin) * height;
    const line = (x1,y1,x2,y2, color, sw=1) => {{
      const el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      el.setAttribute('x1', x1); el.setAttribute('y1', y1);
      el.setAttribute('x2', x2); el.setAttribute('y2', y2);
      el.setAttribute('stroke', color); el.setAttribute('stroke-width', sw);
      svg.appendChild(el);
    }};
    line(pad.l, pad.t + height, pad.l + width, pad.t + height, '#1d1d1f', 2);
    line(pad.l, pad.t, pad.l, pad.t + height, '#1d1d1f', 2);
    payload.series.forEach((series, index) => {{
      const item = payload.selection.samples[index];
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', sx(item.start_s));
      rect.setAttribute('y', pad.t);
      rect.setAttribute('width', Math.max(2, sx(item.end_s) - sx(item.start_s)));
      rect.setAttribute('height', height);
      rect.setAttribute('fill', 'rgba(0,122,255,.10)');
      svg.appendChild(rect);
      line(sx(item.start_s), pad.t, sx(item.start_s), pad.t + height, '#007aff', 2);
      line(sx(item.feed_peak_s), pad.t, sx(item.feed_peak_s), pad.t + height, '#ff9500', 2);
      line(sx(item.discharge_drop_s), pad.t, sx(item.discharge_drop_s), pad.t + height, '#ff3b30', 2);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const d = series.points.map((p, i) => `${{i ? 'L' : 'M'}} ${{sx(p[0])}} ${{sy(p[1])}}`).join(' ');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', ['#007aff','#34c759','#ff9500','#af52de','#ff2d55'][index % 5]);
      path.setAttribute('stroke-width', 2);
      svg.appendChild(path);
    }});
    document.getElementById('download').addEventListener('click', () => {{
      const blob = new Blob([textarea.value], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'torque_selection.json';
      a.click();
      URL.revokeObjectURL(url);
    }});
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def curate_torque_project(
    input_path: str | Path,
    *,
    output_root: Path,
    project_name: str | None = None,
    open_review: bool = False,
) -> dict[str, Any]:
    input_path = Path(input_path).expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    session = prepare_intake_session(input_path, output_root=output_root)
    if session.get("rule_id") != "torque_curve":
        raise ValueError(f"Expected torque data, but detected `{session.get('rule_id')}`.")
    if project_name:
        session["project_name"] = project_name
    project = create_intake_project_from_session(session)
    project_dir = Path(project["project_dir"])
    curation_dir = project_dir / "curation"
    processed_dir = project_dir / "processed"
    curation_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    source_dir = Path(project["source_dir"])
    source_files = _torque_source_files(source_dir)
    if not source_files:
        raise ValueError(f"No torque files found in prepared project source directory: {source_dir}")

    selection_items: list[dict[str, Any]] = []
    full_series_list = []
    preview_series: list[dict[str, Any]] = []
    for source_file in source_files:
        full_series = _read_torque_full_series(source_file)
        selection = _auto_torque_event_selection(full_series)
        selection.update(
            {
                "source_path": str(source_file.resolve()),
                "source_name": source_file.name,
            }
        )
        full_series_list.append(full_series)
        preview_series.append(
            {
                "sample": full_series.sample,
                "source_path": str(source_file.resolve()),
                "points": _sample_points(full_series.points),
            }
        )
        selection_items.append(selection)
    plot_labels = _compact_torque_sample_labels([item["sample"] for item in selection_items])
    selected_series = []
    for full_series, selection, plot_label in zip(full_series_list, selection_items, plot_labels, strict=False):
        selection["plot_label"] = plot_label
        selected_series.append(_apply_torque_selection(full_series, selection))

    plot_data_path = processed_dir / "torque_curated_plot_data.csv"
    _write_curve_table(selected_series, plot_data_path)
    selection_path = curation_dir / "torque_selection.json"
    review_path = curation_dir / "torque_review.html"
    plot_request_path = project_dir / "plot_request.json"
    project_slug = str(project["project_slug"])
    project_file = project_dir / f"{project_slug}.sciplot.json"

    selection_payload: dict[str, Any] = {
        "kind": "sciplot_torque_curation",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "project_name": project_name or str(project["project_name"]),
        "input_path": str(input_path),
        "mode": "last_batch_event",
        "samples": selection_items,
        "files": {
            "selection": str(selection_path),
            "plot_data": str(plot_data_path),
            "review_html": str(review_path),
            "plot_request": str(plot_request_path),
            "project_file": str(project_file),
        },
    }
    selection_path.write_text(
        json.dumps(json_safe(selection_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_torque_review_html(
        review_path,
        project_name=project_name or str(project["project_name"]),
        selection=selection_payload,
        preview_series=preview_series,
    )

    request = json.loads(plot_request_path.read_text(encoding="utf-8"))
    request["series_order"] = plot_labels
    render_options = request.get("render_options")
    if not isinstance(render_options, dict):
        render_options = {}
    render_options["series_order"] = plot_labels
    request["render_options"] = render_options
    study_model = request.get("study_model")
    if isinstance(study_model, dict):
        study_model["sample_order"] = plot_labels
        render_defaults = study_model.get("render_defaults")
        if not isinstance(render_defaults, dict):
            render_defaults = {}
        render_defaults["series_order"] = plot_labels
        study_model["render_defaults"] = render_defaults
    request.update(
        {
            "recipe": "auto",
            "rule_id": "torque_curve",
            "curation": _project_relative(selection_path, project_dir),
            "review_notes": ["Generated by SciPlot torque curation."],
        }
    )
    plot_request_path.write_text(json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8")

    # The intake project is initially generated before the event selections exist.
    # Regenerate only the still-generated Studio document now that the request
    # points at the curation file, so document.vsz and the eventual run consume
    # the same authoritative event windows.
    from sciplot_core.studio import prepare_studio_document

    studio_payload = prepare_studio_document(project_dir, regenerate_generated=True)

    manifest_path = project_dir / "intake_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["kind"] = "sciplot_torque_curation_project"
    manifest["curation"] = {
        "mode": "last_batch_event",
        "selection_path": str(selection_path),
        "plot_data_path": str(plot_data_path),
        "review_html": str(review_path),
        "samples": selection_items,
    }
    manifest["files"] = {
        "project_dir": str(project_dir),
        "plot_request": str(plot_request_path),
        "project_file": str(project_file),
        "selection": str(selection_path),
        "plot_data": str(plot_data_path),
        "review_html": str(review_path),
    }
    if isinstance(studio_payload.get("studio"), dict):
        manifest["studio"] = studio_payload["studio"]
    prepared_request = json.loads(plot_request_path.read_text(encoding="utf-8"))
    for key in ("study_model", "publication_intent", "transform_ledger"):
        if isinstance(prepared_request.get(key), dict):
            manifest[key] = prepared_request[key]
    manifest_path.write_text(json.dumps(json_safe(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    project_file.write_text(json.dumps(json_safe(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    zip_path = refresh_intake_project_zip(project_dir)
    selection_payload["files"]["zip"] = str(zip_path)
    selection_path.write_text(
        json.dumps(json_safe(selection_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if open_review:
        webbrowser.open(review_path.as_uri())
    return {
        "kind": "sciplot_torque_curation_project",
        "project_name": project_name or str(project["project_name"]),
        "project_dir": str(project_dir),
        "plot_request": str(plot_request_path),
        "selection_path": str(selection_path),
        "plot_data_path": str(plot_data_path),
        "review_html": str(review_path),
        "project_file": str(project_file),
        "zip_path": str(zip_path),
        "samples": selection_items,
    }


__all__ = ["curate_torque_project"]
