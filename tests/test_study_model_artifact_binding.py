from __future__ import annotations

from pathlib import Path

from sciplot_core.study_model import attach_run_artifacts_to_study_model


def test_artifact_binding_uses_shared_case_insensitive_dpi_stem(tmp_path: Path) -> None:
    model = {
        "kind": "sciplot_study_model",
        "version": 2,
        "samples": [],
        "figure_queue": [{"id": "Figure_A", "metric": "primary"}],
    }
    figures = [
        str(tmp_path / "Figure_A.pdf"),
        str(tmp_path / "Figure_A_600DPI.png"),
    ]

    updated = attach_run_artifacts_to_study_model(
        model,
        output_dir=tmp_path,
        figures=figures,
    )

    queue = updated["figure_queue"]
    assert queue[0]["status"] == "rendered"
    assert [item["path"] for item in queue[0]["artifacts"]] == figures
    assert updated["run"]["unbound_figure_artifacts"] == []
