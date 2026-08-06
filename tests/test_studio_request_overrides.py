from __future__ import annotations

import json
from pathlib import Path

from sciplot_core.project_manifest import (
    commit_intake_project_manifest,
    read_intake_project_manifest,
)
from sciplot_core.studio_core.request_overrides import (
    _apply_studio_request_overrides,
)


def _pending_project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "rule_id": "performance_comparison",
                "template": "scatter",
                "pending_rule_review": True,
                "study_model": {
                    "kind": "sciplot_study_model",
                    "version": 1,
                    "experiment": {
                        "rule_id": "performance_comparison",
                        "template": "scatter",
                        "chart": "scatter",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    commit_intake_project_manifest(
        project_dir,
        {
            "kind": "sciplot_intake_project",
            "version": 1,
            "project_slug": project_dir.name,
            "recognition": {
                "rule_id": "performance_comparison",
                "pending_rule_review": True,
                "production_status": "needs_rule_repair",
            },
            "experiment": {
                "rule_id": "performance_comparison",
                "template": "scatter",
            },
        },
    )
    return project_dir, request_path


def test_ready_rule_override_clears_a_stale_pending_review_marker(
    tmp_path: Path,
) -> None:
    project_dir, request_path = _pending_project(tmp_path)

    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        rule_id="performance_comparison",
        template="scatter",
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    project = read_intake_project_manifest(project_dir)
    assert project is not None
    recognition = project["recognition"]
    assert "pending_rule_review" not in request
    assert "pending_rule_review" not in recognition
    assert recognition["production_status"] == "ready"


def test_template_only_override_preserves_the_pending_review_marker(
    tmp_path: Path,
) -> None:
    project_dir, request_path = _pending_project(tmp_path)

    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        template="polar_curve",
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    project = read_intake_project_manifest(project_dir)
    assert project is not None
    assert request["pending_rule_review"] is True
    assert request["study_model"]["experiment"]["template"] == "polar_curve"
    assert request["study_model"]["experiment"]["chart"] == "polar_curve"
    assert project["recognition"]["pending_rule_review"] is True
    assert project["recognition"]["production_status"] == "needs_rule_repair"
