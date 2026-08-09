"""Compatibility access to non-authoritative mechanical summary tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.mechanical_figure_contract import mechanical_figure_contract
from sciplot_core.mechanical_render_options import mechanical_summary_render_options


def _mechanical_summary_sources(
    input_path: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
    options: dict[str, Any],
) -> list[tuple[str, Path, dict[str, Any]]]:
    """Materialize box-strip tables for diagnostics; execution uses typed facts."""

    rule_id = str(request.get("rule_id") or "").strip()
    try:
        contract = mechanical_figure_contract(rule_id)
    except ValueError:
        return []
    summary_path = input_path.with_name(f"{input_path.stem}_summary.csv")
    if not summary_path.is_file():
        return []
    summary = pd.read_csv(summary_path)
    if "sample" not in summary.columns:
        return []
    observed = [
        str(value) for value in summary["sample"].dropna().drop_duplicates().tolist()
    ]
    study_model = request.get("study_model")
    requested_order = (
        [str(value) for value in study_model.get("sample_order", [])]
        if isinstance(study_model, dict)
        else []
    )
    sample_order = [value for value in requested_order if value in observed]
    sample_order.extend(value for value in observed if value not in sample_order)
    if not sample_order:
        return []
    target = output_dir / "processed" / "veusz_metric_sources"
    target.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, Path, dict[str, Any]]] = []
    for task in contract.summary_tasks:
        if task.y_metric not in summary.columns:
            continue
        groups = [
            pd.to_numeric(
                summary.loc[
                    summary["sample"].astype(str) == sample,
                    task.y_metric,
                ],
                errors="coerce",
            )
            .dropna()
            .tolist()
            for sample in sample_order
        ]
        if any(not values for values in groups):
            continue
        rows: list[list[Any]] = [
            [task.y_label for _sample in sample_order],
            [task.y_unit for _sample in sample_order],
            list(sample_order),
        ]
        rows.extend(
            [values[index] if index < len(values) else "" for values in groups]
            for index in range(max(len(values) for values in groups))
        )
        source = target / f"{task.artifact_stem}.csv"
        pd.DataFrame(rows).to_csv(source, header=False, index=False)
        records.append(
            (
                task.artifact_stem,
                source,
                {
                    "template": "box_strip",
                    **mechanical_summary_render_options(task, options=options),
                },
            )
        )
    return records


__all__ = ["_mechanical_summary_sources"]
