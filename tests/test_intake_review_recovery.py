from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.intake.table_preview import preview_table_payload
from sciplot_core.intake.session import _selected_column_confirmations
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.scientific_source_single_curve import (
    resolve_single_curve_transform,
)


def _workbook() -> bytes:
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        for name, values in [("Heating", [1, 2, 3]), ("Cooling", [3, 2, 1])]:
            pd.DataFrame(
                {"Temperature (°C)": [10, 20, 30], "Heat Flow (W/g)": values}
            ).to_excel(writer, sheet_name=name, index=False)
    return stream.getvalue()


def test_explicit_worksheet_is_previewed_and_consumed_without_changing_source(
    tmp_path: Path,
) -> None:
    content = _workbook()
    source = tmp_path / "dsc.xlsx"
    source.write_bytes(content)
    preview = preview_table_payload(
        name=source.name, content=content, selected_sheet="Cooling"
    )
    assert preview["sheets"] == ["Heating", "Cooling"]
    assert preview["rows"][1]["values"] == ["10", "3"]
    confirmations = _selected_column_confirmations(
        [
            {
                "sheet": preview["sheet"],
                "sheet_selected": True,
                "source_sha256": preview["source_sha256"],
                "columns": preview["columns"],
            }
        ]
    )
    rule = get_rule("dsc_curve")
    with pytest.raises(ValueError, match="More than one source table"):
        resolve_single_curve_transform(source, rule=rule)
    transformed = resolve_single_curve_transform(
        source, rule=rule, column_confirmations=confirmations
    )
    assert list(transformed.series[0].points) == [(10, 3), (20, 2), (30, 1)]
    assert source.read_bytes() == content
    assert "Cooling" in transformed.series[0].diagnostics["source_table"]
    assert "Cooling" in json.dumps(transformed.contract.to_payload())


def test_stale_or_missing_worksheet_confirmation_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "dsc.xlsx"
    source.write_bytes(_workbook())
    preview = preview_table_payload(name=source.name, source_path=source)
    confirmation = {
        "sheet_selected": True,
        "source_sha256": "0" * 64,
        "sheet": "Heating",
    }
    with pytest.raises(ValueError, match="source bytes"):
        resolve_single_curve_transform(
            source, rule=get_rule("dsc_curve"), column_confirmations=[confirmation]
        )
    confirmation.update(source_sha256=preview["source_sha256"], sheet="Missing")
    with pytest.raises(ValueError, match="worksheet.*missing"):
        resolve_single_curve_transform(
            source, rule=get_rule("dsc_curve"), column_confirmations=[confirmation]
        )


def test_preview_keeps_original_column_indices_and_literal_na_labels() -> None:
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame(
            [["Temperature", None, "Response"], [1, None, 2], ["NA", None, 3]]
        ).to_excel(writer, index=False, header=False)
    preview = preview_table_payload(name="source.xlsx", content=stream.getvalue())
    assert preview["preview_columns"] == 3
    assert preview["columns"][2]["index"] == 2
    assert preview["rows"][2]["values"][0] == "NA"


@pytest.mark.parametrize(
    "failure", [RuntimeError("worker failed"), OSError("disk full")]
)
def test_execution_failures_do_not_create_a_data_cleanup_request(
    tmp_path, monkeypatch, failure
) -> None:
    from sciplot_core.intake import run

    project = tmp_path / "project"
    project.mkdir()
    request = project / "plot_request.json"
    request.write_text(json.dumps({"output": str(project / "runs" / "run_001")}))
    (project / "intake_manifest.json").write_text(
        json.dumps({"project_slug": "project"})
    )
    monkeypatch.setattr(
        run,
        "create_intake_project",
        lambda **kwargs: {
            "project_dir": str(project),
            "plot_request": str(request),
            "studio": {"status": "ready"},
        },
    )
    monkeypatch.setattr(
        run, "export_project_document", lambda **kwargs: (_ for _ in ()).throw(failure)
    )
    monkeypatch.setattr(
        run, "refresh_intake_project_zip", lambda project_dir: project / "project.zip"
    )
    result = run.create_and_run_intake_project(
        project_name="x",
        data_type_id="thermal",
        experiment_type_id="dsc_curve",
        groups=[],
    )
    assert result["run_failed"] is True
    assert result["last_run"]["ready_to_use"] is False
    assert result["last_run"]["failure_kind"] == "execution_error"
    assert result["last_run"]["needs_assisted_cleanup"] is False
    assert result["last_run"]["assisted_cleanup_request"] is None


def test_empty_explicit_worksheet_selection_is_not_discarded(tmp_path: Path) -> None:
    source = tmp_path / "empty_sheet.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame(
            {"Temperature (°C)": [10, 20], "Heat Flow (W/g)": [1, 2]}
        ).to_excel(writer, sheet_name="Heating", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Empty", index=False)
    preview = preview_table_payload(
        name=source.name, source_path=source, selected_sheet="Empty"
    )
    confirmations = _selected_column_confirmations(
        [
            {
                "sheet": preview["sheet"],
                "sheet_selected": True,
                "source_sha256": preview["source_sha256"],
                "columns": preview["columns"],
            }
        ]
    )
    assert confirmations and confirmations[0]["sheet"] == "Empty"
    with pytest.raises(ValueError):
        resolve_single_curve_transform(
            source, rule=get_rule("dsc_curve"), column_confirmations=confirmations
        )


def test_incomplete_publication_keeps_actual_failed_run_output(
    tmp_path: Path, monkeypatch
) -> None:
    from sciplot_core.intake import run
    from sciplot_core.studio_core.project_export import ProjectExportResult

    project = tmp_path / "project"
    project.mkdir()
    legacy = project / "runs" / "run_001"
    actual = project / "runs" / "studio_001"
    actual.mkdir(parents=True)
    request = project / "plot_request.json"
    request.write_text(json.dumps({"output": str(legacy)}))
    (project / "intake_manifest.json").write_text(
        json.dumps({"project_slug": "project"})
    )
    failed = {
        "output": str(actual),
        "ready_to_use": False,
        "failure_reason": "delivery verification failed",
    }
    (actual / "manifest.json").write_text(json.dumps(failed))
    monkeypatch.setattr(
        run,
        "create_intake_project",
        lambda **kwargs: {
            "project_dir": str(project),
            "plot_request": str(request),
            "studio": {"status": "ready"},
        },
    )
    monkeypatch.setattr(
        run,
        "export_project_document",
        lambda **kwargs: ProjectExportResult(
            document_sha256="a" * 64,
            ready_to_use=False,
            _export_json="{}",
            _run_json=json.dumps(failed),
        ),
    )
    monkeypatch.setattr(
        run, "refresh_intake_project_zip", lambda project_dir: project / "project.zip"
    )
    result = run.create_and_run_intake_project(
        project_name="x",
        data_type_id="thermal",
        experiment_type_id="dsc_curve",
        groups=[],
    )
    assert result["last_run"]["output"] == str(actual)
    assert result["last_run"]["failure"] == "delivery verification failed"


def test_current_export_failure_never_reuses_stale_intervention_output(
    tmp_path: Path, monkeypatch
) -> None:
    from sciplot_core.intake import run
    from sciplot_core.intake.status import intake_project_status

    project = tmp_path / "project"
    stale = project / "runs" / "run_001"
    stale.mkdir(parents=True)
    (stale / "intervention_request.json").write_text("{}")
    (stale / "manifest.json").write_text(
        json.dumps({"state": "ready", "ready_to_use": True})
    )
    request = project / "plot_request.json"
    request.write_text(
        json.dumps({"output": str(stale), "input": str(project / "source.csv")})
    )
    (project / "intake_manifest.json").write_text(
        json.dumps({"project_slug": "project", "outputs_dir": str(stale)})
    )
    monkeypatch.setattr(
        run,
        "create_intake_project",
        lambda **kwargs: {
            "project_dir": str(project),
            "plot_request": str(request),
            "studio": {"status": "ready"},
        },
    )
    monkeypatch.setattr(
        run,
        "export_project_document",
        lambda **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        run, "refresh_intake_project_zip", lambda project_dir: project / "project.zip"
    )
    result = run.create_and_run_intake_project(
        project_name="x",
        data_type_id="thermal",
        experiment_type_id="dsc_curve",
        groups=[],
    )
    assert result["last_run"]["output"] != str(stale)
    assert result["last_run"]["failure_kind"] == "execution_error"
    assert result["last_run"]["needs_assisted_cleanup"] is False
    assert intake_project_status(project)["needs_assisted_cleanup"] is False
    assert json.loads((stale / "manifest.json").read_text())["ready_to_use"] is True


def test_explicit_worksheet_cannot_be_ignored_by_another_single_curve_adapter(
    tmp_path: Path,
) -> None:
    source = tmp_path / "swelling.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["Condition A", None],
                ["1", None],
                ["Time (h)", "Swelling ratio"],
                [0, 1],
                [1, 1.2],
            ]
        ).to_excel(writer, sheet_name="Measurement", header=False, index=False)
        pd.DataFrame({"note": ["selected notes"]}).to_excel(
            writer, sheet_name="Notes", index=False
        )
    preview = preview_table_payload(
        name=source.name, source_path=source, selected_sheet="Notes"
    )
    confirmations = _selected_column_confirmations(
        [
            {
                "sheet_selected": True,
                "sheet": preview["sheet"],
                "source_sha256": preview["source_sha256"],
                "columns": preview["columns"],
            }
        ]
    )
    with pytest.raises(ValueError, match="worksheet selection is not supported"):
        resolve_single_curve_transform(
            source, rule=get_rule("swelling_curve"), column_confirmations=confirmations
        )
    unchanged = resolve_single_curve_transform(source, rule=get_rule("swelling_curve"))
    assert list(unchanged.series[0].points) == [(0, 1), (1, 1.2)]


def test_selected_worksheet_survives_intake_request_and_source_materialization(
    tmp_path: Path, monkeypatch
) -> None:
    from sciplot_core.intake import application
    from sciplot_core.intake.models import IncomingFile, IntakeGroupInput

    content = _workbook()
    preview = preview_table_payload(
        name="dsc.xlsx", content=content, selected_sheet="Cooling"
    )
    inspected = []

    def inspect_prepared_request(project_dir: Path):
        request = json.loads((project_dir / "plot_request.json").read_text())
        confirmations = request["column_confirmations"]
        assert confirmations[0]["sheet_selected"] is True
        assert confirmations[0]["sheet"] == "Cooling"
        transform = resolve_single_curve_transform(
            Path(request["input"]),
            rule=get_rule("dsc_curve"),
            series_order=request.get("series_order"),
            column_confirmations=confirmations,
        )
        inspected.append(list(transform.series[0].points))
        assert transform.selected_sources[0].read_bytes() == content
        raise RuntimeError(
            "Stop after validating the confirmed source; no renderer needed"
        )

    monkeypatch.setattr(
        application, "prepare_studio_document", inspect_prepared_request
    )
    result = application.create_intake_project(
        project_name="Worksheet binding",
        data_type_id="thermal",
        experiment_type_id="dsc_curve",
        groups=[
            IntakeGroupInput(
                sample="sample", files=(IncomingFile(name="dsc.xlsx", content=content),)
            )
        ],
        output_root=tmp_path,
        column_confirmations=[
            {
                "sample": "sample",
                "file_name": "dsc.xlsx",
                "sheet": preview["sheet"],
                "sheet_selected": True,
                "source_sha256": preview["source_sha256"],
                "columns": preview["columns"],
            }
        ],
    )
    assert inspected == [[(10, 3), (20, 2), (30, 1)]]
    assert result["studio"]["status"] == "blocked"
    assert "no renderer needed" in result["studio"]["error"]
