"""Run one-step and persist its autoplot summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.workflow import run_one_step

from sciplot_core.autoplot.summary import (
    build_autoplot_summary,
)


def run_autoplot(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
    delivery_root: Path | None = None,
    template: str | None = None,
) -> dict[str, Any]:
    result = run_one_step(
        input_path,
        output_root=output_root,
        project_name=project_name,
        delivery_root=delivery_root,
        template=template,
    )
    summary = build_autoplot_summary(result)
    run_output = Path(str(summary["run_output"]))
    summary_path = run_output / "autoplot_summary.json"
    summary["summary_path"] = str(summary_path)
    atomic_write_json(summary_path, json_safe(summary))
    return summary
