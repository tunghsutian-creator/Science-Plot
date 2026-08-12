from __future__ import annotations

import json
from pathlib import Path

from sciplot_core.intake import intake_project_status
from sciplot_core.scientific_review import (
    build_scientific_transform_review,
    scientific_transform_review_from_ledger,
)
from sciplot_gui import studio_project_status


class _Document:
    changeset = 1

    def isModified(self) -> bool:
        return False


def _contract(anchor_time: float) -> dict[str, object]:
    return {
        "kind": "sciplot_scientific_transform",
        "version": 1,
        "semantic_family": "example_curve",
        "source_columns": [
            {
                "sample": "sample A",
                "sources": ["/private/source/example.csv"],
                "x": {
                    "role": "coordinate",
                    "header": "Elapsed time",
                    "unit": "s",
                },
                "response": {
                    "role": "response",
                    "header": "Signal",
                    "unit": "Pa",
                },
            }
        ],
        "unit_conversions": [
            {
                "sample": "sample A",
                "role": "response",
                "source_unit": "Pa",
                "canonical_unit": "Pa",
                "display_unit": "MPa",
                "source_to_canonical": {"factor": 1.0, "offset": 0.0},
                "canonical_to_display": {"factor": 1.0e-6, "offset": 0.0},
            }
        ],
        "anchor": {
            "scope": "per_series",
            "selections": [
                {
                    "sample": "sample A",
                    "selector": "detected_source_anchor",
                    "applicable": True,
                    "source_time": anchor_time,
                    "source_time_unit": "s",
                    "response_value": 42.0,
                    "response_unit": "Pa",
                    "retained": True,
                    "output_point": [anchor_time, 1.0],
                }
            ],
        },
        "normalizer": {
            "scope": "per_series",
            "output_metric": "normalized_signal",
            "output_unit": "1",
            "series": [
                {
                    "sample": "sample A",
                    "operation": "divide_by_detected_source_anchor",
                }
            ],
        },
        "x_coordinate_policy": {
            "operation": "preserve_source_coordinate",
            "metric": "time",
            "unit": "s",
            "reset_applied": False,
        },
        "retain_anchor": True,
        "axis_compatibility": {
            "x": {
                "registered_scale": "log",
                "finite_compatible": True,
                "log_compatible": True,
                "nonpositive_count": 0,
            },
            "y": {
                "registered_scale": "linear",
                "finite_compatible": True,
                "log_compatible": False,
                "nonpositive_count": 1,
            },
        },
        "output": {
            "x_metric": "time",
            "x_unit": "s",
            "y_metric": "normalized_signal",
            "y_unit": "1",
            "series_order": ["sample A"],
            "series": [
                {
                    "sample": "sample A",
                    "retained_point_count": 9,
                    "excluded_point_count": 2,
                    "negative_y_count": 1,
                    "excluded_by_reason": {"missing": 2},
                }
            ],
        },
        "selected_sources": ["/private/source/example.csv"],
    }


def _ledger(anchor_time: float) -> dict[str, object]:
    return {
        "status": "complete",
        "steps": [
            {
                "step_id": "semantic_preparation",
                "parameters": {"scientific_transform": _contract(anchor_time)},
            }
        ],
    }


def test_scientific_review_projects_only_persisted_source_values() -> None:
    review = build_scientific_transform_review(_contract(0.123))

    assert review["status"] == "available"
    assert review["semantic_family"] == "example_curve"
    assert review["anchors"] == [
        {
            "sample": "sample A",
            "applicable": True,
            "selector": "detected_source_anchor",
            "retained": True,
            "source_time": 0.123,
            "source_time_unit": "s",
            "response_value": 42.0,
            "response_unit": "Pa",
        }
    ]
    items = {item["id"]: item["value"] for item in review["items"]}
    assert items["anchors"] == "sample A: 0.123 [s] (retained)"
    assert items["points"] == "9 retained; 2 excluded; 1 negative retained"
    assert "/private/source" not in " ".join(items.values())


def test_scientific_review_keeps_missing_boolean_claims_unknown() -> None:
    contract = _contract(0.314159)
    anchor = contract["anchor"]
    assert isinstance(anchor, dict)
    selections = anchor["selections"]
    assert isinstance(selections, list)
    selection = selections[0]
    assert isinstance(selection, dict)
    selection.pop("applicable")
    selection.pop("retained")
    axes = contract["axis_compatibility"]
    assert isinstance(axes, dict)
    x_axis = axes["x"]
    assert isinstance(x_axis, dict)
    x_axis.pop("log_compatible")

    review = build_scientific_transform_review(contract)

    assert review["anchors"][0]["applicable"] is None
    assert review["anchors"][0]["retained"] is None
    assert review["anchors"][0]["source_time"] == 0.314159
    items = {item["id"]: item["value"] for item in review["items"]}
    assert items["anchors"] == (
        "sample A: 0.314159 [s] "
        "(applicability not declared; retention not declared)"
    )
    assert "x=log, log compatibility not declared" in items["axes"]


def test_scientific_review_does_not_invent_an_unknown_anchor() -> None:
    contract = _contract(0.314159)
    anchor = contract["anchor"]
    assert isinstance(anchor, dict)
    selections = anchor["selections"]
    assert isinstance(selections, list)
    selection = selections[0]
    assert isinstance(selection, dict)
    selection.pop("applicable")
    selection.pop("source_time")

    review = build_scientific_transform_review(contract)

    assert "source_time" not in review["anchors"][0]
    items = {item["id"]: item["value"] for item in review["items"]}
    assert items["anchors"] == "sample A: applicability not declared"


def test_scientific_review_blocks_failed_ledger_with_residual_payload() -> None:
    ledger = _ledger(0.314159)
    ledger["status"] = "failed"

    review = scientific_transform_review_from_ledger(ledger)

    assert review is not None
    assert review["status"] == "blocked"
    assert review["reason_code"] == "scientific_transform_ledger_unavailable"
    assert review["ledger_status"] == "failed"
    assert review["items"] == []
    assert "0.314159" not in json.dumps(review)


def test_intake_status_reads_only_run_local_scientific_transform(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    run_dir = project_dir / "runs" / "run_001"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"transform_ledger": _ledger(0.123)}),
        encoding="utf-8",
    )
    (project_dir / "plot_request.json").write_text(
        json.dumps({"transform_ledger": _ledger(0.271)}),
        encoding="utf-8",
    )
    (project_dir / "intake_manifest.json").write_text(
        json.dumps(
            {
                "project_slug": "project",
                "project_name": "Project",
                "outputs_dir": str(run_dir),
                "transform_ledger": _ledger(0.456),
                "last_run": {
                    "output": str(run_dir),
                    "figures": [],
                    "transform_ledger": _ledger(0.789),
                },
            }
        ),
        encoding="utf-8",
    )

    status = intake_project_status(project_dir)

    assert status["scientific_transform_review"]["anchors"][0][
        "source_time"
    ] == 0.123
    assert status["scientific_transform_review"]["phase"] == "run_result"

    (run_dir / "manifest.json").unlink()
    assert intake_project_status(project_dir)["scientific_transform_review"] is None


def test_intake_status_reads_prepared_review_from_canonical_request(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    stale_request = project_dir / "stale_request.json"
    stale_request.write_text(
        json.dumps({"transform_ledger": _ledger(0.789)}),
        encoding="utf-8",
    )
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps({"transform_ledger": _ledger(0.271)}),
        encoding="utf-8",
    )
    (project_dir / "intake_manifest.json").write_text(
        json.dumps(
            {
                "project_slug": "project",
                "project_name": "Project",
                "plot_request": str(stale_request),
                "transform_ledger": _ledger(0.456),
            }
        ),
        encoding="utf-8",
    )

    review = intake_project_status(project_dir)["scientific_transform_review"]

    assert review["anchors"][0]["source_time"] == 0.271
    assert review["phase"] == "prepared"

    request_path.unlink()
    assert intake_project_status(project_dir)["scientific_transform_review"] is None


def test_primary_studio_status_reads_current_request_review_before_export(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    document_path = project_dir / "studio" / "document.vsz"
    request_path = project_dir / "plot_request.json"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("# minimal Veusz document\n", encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "input": "missing.csv",
                "rule_id": "example_curve",
                "template": "curve",
                "transform_ledger": _ledger(0.271),
            }
        ),
        encoding="utf-8",
    )

    status = studio_project_status.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=project_dir,
        request_path=request_path,
        _figure_set_scope_resolver=lambda **_kwargs: (None, "not_applicable"),
    )

    review = status["scientific_transform_review"]
    assert review["anchors"][0]["source_time"] == 0.271
    text = studio_project_status._status_text(status)
    assert "Scientific review:" in text
    assert "sample A: 0.271 [s] (retained)" in text
