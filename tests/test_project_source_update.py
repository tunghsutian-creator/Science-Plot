from __future__ import annotations

import json

import pytest

from sciplot_core.studio_core import source_update as update
from sciplot_core.studio_core.source_update_review import (
    project_figures,
    scientific_summary,
)


def test_source_review_rejects_corrupt_registry_instead_of_dropping_secondary_figures(
    tmp_path,
):
    (tmp_path / "studio").mkdir()
    (tmp_path / "studio/document.vsz").write_text("old")
    (tmp_path / "studio/spec.json").write_text("{}")
    (tmp_path / "studio/figure_set.json").write_text("broken")
    with pytest.raises(ValueError, match="registry"):
        project_figures(tmp_path)


def test_scientific_review_preserves_duplicate_replicate_counts_and_ignores_paths():
    spec = {
        "categorical": {
            "groups": [{"label": "A", "raw_values": [2, 2, 3], "replicate_count": 3}]
        },
        "scalar_field": {
            "x_values": [1],
            "y_values": [2],
            "z_values": [[3]],
            "source_artifacts": [{"path": "/a"}],
        },
    }
    before = scientific_summary(spec)
    spec["scalar_field"]["source_artifacts"][0]["path"] = "/b"
    assert scientific_summary(spec) == before
    assert before["groups"][0]["raw_values"]["count"] == 3
    spec["categorical"]["groups"][0]["raw_values"].append(2)
    assert scientific_summary(spec) != before


def test_source_update_rechecks_selected_source_and_visible_delivery(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    delivery = tmp_path / "visible"
    source = tmp_path / "data.csv"
    source.write_text("one")
    (project / "plot_request.json").write_text(
        json.dumps({"delivery_output": str(delivery)})
    )
    review = {
        "source_files": update.file_inventory(source),
        "delivery_sha256": update.payload_hash(None),
    }
    update._check_external_state(project, source, review)
    delivery.mkdir()
    (delivery / "visible.vsz").write_text("edit")
    with pytest.raises(ValueError, match="visible delivery changed"):
        update._check_external_state(project, source, review)
    (delivery / "visible.vsz").unlink()
    delivery.rmdir()
    source.write_text("two")
    with pytest.raises(ValueError, match="selected source"):
        update._check_external_state(project, source, review)


def test_update_cannot_apply_blocked_or_unreviewed_data(tmp_path):
    with pytest.raises(ValueError, match="preview"):
        update.apply_project_source_update(tmp_path, {"status": "blocked"})


def test_numerical_review_shows_internal_changed_points_without_losing_duplicate_rows():
    from sciplot_core.studio_core.source_update_review import numerical_differences

    old = {"series": [{"label": "A", "y_values": [1, 2, 2, 4]}]}
    new = {"series": [{"label": "A", "y_values": [1, 3, 2, 4]}]}
    delta = numerical_differences(old, new)[0]
    assert delta["changed_value_count"] == 1
    assert delta["examples"] == [{"point_index": 2, "before": 2, "after": 3}]
