"""Headless scientific curation keeps exact source windows and saved contracts."""

import json
from pathlib import Path
import subprocess
import webbrowser
import zipfile

import pandas as pd
import pytest

from sciplot_core import cli, curate, studio
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.torque_sources import _load_torque_curation
from test_torque_source_contract import _CURATION_POINTS, _write_torque_source
from curation_fixture_helpers import _generated_torque_sources, _points


def test_real_curation_pipeline_keeps_full_scientific_series_and_only_machine_selection(
    tmp_path, monkeypatch
):
    source = tmp_path / "original"
    original = _generated_torque_sources(source)
    preparations, before_curation = [], []
    original_curation = curate._prepare_torque_curation

    def observe_curation(project, **options):
        before_curation.append(json.loads((project / "plot_request.json").read_text()))
        return original_curation(project, **options)

    def native_port(project, **options):
        # The real intake/source/selection/packaging chain runs; only the native
        # Studio port is controlled. This is not native acceptance evidence.
        request = json.loads((project / "plot_request.json").read_text())
        selection = project / request["curation"] if "curation" in request else None
        prepared = prepare_semantic_source(
            request["input"],
            output_dir=tmp_path / f"controlled-native-port-{len(preparations)}",
            semantic={"semantic_family": "torque_curve", "rule_id": "torque_curve"},
            curation_path=selection,
            series_order=request.get("series_order"),
        )
        preparations.append(
            {"request": request, "options": options, "prepared": prepared}
        )
        return {
            "studio": {
                "status": "ready",
                "scope": "controlled native port; no native proof",
            }
        }

    monkeypatch.setattr(studio, "prepare_studio_document", native_port)
    monkeypatch.setattr(curate, "_prepare_torque_curation", observe_curation)
    result = curate.curate_torque_project(
        source, output_root=tmp_path / "projects", project_name="Generated torque"
    )
    assert len(preparations) == 1
    assert preparations[0]["options"] == {"_new_creation": True}
    assert "curation" not in before_curation[0]
    project = Path(result["project_dir"])
    selection_path = Path(result["selection_path"])
    selection = json.loads(selection_path.read_text())
    assert "review_html" not in result and "review_html" not in selection["files"]
    assert not list(project.rglob("*.html"))
    assert len(result["samples"]) == 2
    assert result["samples"] == selection["samples"]
    expected = []
    for item in selection["samples"]:
        raw = Path(item["source_path"])
        original_path, original_bytes, full_points = original[file_sha256(raw)]
        assert raw.read_bytes() == original_bytes == original_path.read_bytes()
        assert curate._read_torque_full_series(raw).points == full_points
        assert item["start_s"] == 0 and item["feed_peak_s"] == 600
        assert item["source"] == "auto_detected" and item["time_zero"] == "start_s"
        selected = tuple(
            (x - item["start_s"], y)
            for x, y in full_points
            if item["start_s"] <= x <= item["end_s"]
        )
        assert 1200 < len(selected) < len(full_points)
        expected.append(selected)
    assert _points(result["plot_data_path"]) == expected
    assert (
        Path(result["plot_data_path"]).read_bytes()
        == Path(preparations[0]["prepared"]["processed_source"]).read_bytes()
    )
    table = pd.read_csv(result["plot_data_path"], header=None)
    assert table.iloc[1].tolist() == ["s", "N·m", "s", "N·m"]
    labels = [item["plot_label"] for item in selection["samples"]]
    request = preparations[0]["request"]
    assert request["curation"] == "curation/torque_selection.json"
    assert (
        request["series_order"] == request["render_options"]["series_order"] == labels
    )
    assert request["study_model"]["sample_order"] == labels
    for key in (
        "input",
        "rule_id",
        "template",
        "publication_intent",
        "transform_ledger",
    ):
        assert request[key] == before_curation[0][key]
    manifest = json.loads((project / "intake_manifest.json").read_text())
    assert manifest["curation"]["samples"] == selection["samples"]
    assert (
        "review_html" not in manifest["curation"]
        and "review_html" not in manifest["files"]
    )
    with zipfile.ZipFile(result["zip_path"]) as archive:
        assert not any(name.endswith(".html") for name in archive.namelist())
        for name in (
            "plot_request.json",
            "curation/torque_selection.json",
            "processed/torque_curated_plot_data.csv",
        ):
            assert f"{project.name}/{name}" in archive.namelist()
        assert (
            archive.read(f"{project.name}/processed/torque_curated_plot_data.csv")
            == Path(result["plot_data_path"]).read_bytes()
        )
    assert all(path.read_bytes() == content for path, content, _ in original.values())
    from sciplot_core.project_host_factory import project_store

    store = project_store(project, with_snapshot=True)
    assert store.snapshot()["outside_changes"] == {}
    assert (
        store.read_bytes("curation/torque_selection.json")
        == selection_path.read_bytes()
    )


def test_old_selection_and_html_remain_readonly_compatible_with_scientific_preparation(
    tmp_path,
):
    source = tmp_path / "old.csv"
    _write_torque_source(source, _CURATION_POINTS)
    html = tmp_path / "torque_review.html"
    html.write_bytes(b"historical user review; do not rewrite or delete")
    selection = tmp_path / "torque_selection.json"
    selection.write_text(
        json.dumps(
            {
                "kind": "sciplot_torque_curation",
                "version": 1,
                "samples": [
                    {
                        "source_path": str(source),
                        "start_s": 20,
                        "end_s": 40,
                        "time_zero": "absolute",
                    }
                ],
                "files": {"review_html": str(html)},
            }
        )
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in (source, selection, html)
    }
    assert _load_torque_curation(selection)["files"]["review_html"] == str(html)
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"semantic_family": "torque_curve", "rule_id": "torque_curve"},
        curation_path=selection,
    )
    assert _points(prepared["processed_source"]) == [((20, 18), (30, 12), (40, 7))]
    assert {
        path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in before
    } == before


@pytest.mark.parametrize("json_output", [False, True])
def test_retired_open_option_is_rejected_during_parsing_without_target_io(
    tmp_path, monkeypatch, capsys, json_output
):
    source, output = tmp_path / "missing-source", tmp_path / "never-created-output"

    def forbidden(*_args, **_kwargs):
        pytest.fail("Retired --open reached curation, a runtime or browser")

    monkeypatch.setattr(curate, "curate_torque_project", forbidden)
    monkeypatch.setattr(studio, "maybe_reexec_with_qt_runtime", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    argv = [
        "curate",
        "torque",
        str(source),
        "--name",
        "Generated",
        "--out",
        str(output),
        "--open",
    ]
    if json_output:
        assert cli.main([*argv, "--json"]) == 2
        error = json.loads(capsys.readouterr().out)
        assert (
            error["reason_code"] == "cli_invalid_arguments"
            and "--open" in error["message"]
        )
    else:
        with pytest.raises(SystemExit) as stopped:
            cli.main(argv)
        assert stopped.value.code == 2 and "--open" in capsys.readouterr().err
    assert not source.exists() and not output.exists()


@pytest.mark.parametrize("json_output", [False, True])
def test_current_cli_reports_selection_path_without_browser_parameter(
    tmp_path, monkeypatch, capsys, json_output
):
    source, output, selection = (
        tmp_path / "input",
        tmp_path / "output",
        tmp_path / "selection.json",
    )
    calls = []

    def curate_port(input_path, *, output_root, project_name):
        calls.append((input_path, output_root, project_name))
        return {"selection_path": str(selection), "scope": "controlled CLI routing"}

    monkeypatch.setattr(curate, "curate_torque_project", curate_port)
    monkeypatch.setattr(studio, "maybe_reexec_with_qt_runtime", lambda _argv: None)
    argv = [
        "curate",
        "torque",
        str(source),
        "--name",
        "Generated",
        "--out",
        str(output),
    ]
    assert cli.main([*argv, *(["--json"] if json_output else [])]) == 0
    text = capsys.readouterr().out
    assert (json.loads(text)["selection_path"] if json_output else text.strip()) == str(
        selection
    )
    assert calls == [(source, output, "Generated")]


@pytest.mark.parametrize("old_option", [False, True])
def test_old_python_browser_parameter_is_rejected_before_source_or_project_work(
    tmp_path, monkeypatch, old_option
):
    monkeypatch.setattr(
        curate,
        "prepare_intake_session",
        lambda *_a, **_k: pytest.fail("old browser parameter reached source IO"),
    )
    with pytest.raises(TypeError, match="open_review"):
        curate.curate_torque_project(
            tmp_path / "source", output_root=tmp_path / "output", open_review=old_option
        )
    assert not (tmp_path / "output").exists()


def test_acceptance_consumer_uses_headless_selection_contract(tmp_path, monkeypatch):
    from sciplot_core.acceptance import three_dpa_runs

    calls = []

    def curate_port(input_path, *, output_root, project_name):
        calls.append((input_path, output_root, project_name))
        return {
            "plot_request": str(tmp_path / "plot_request.json"),
            "selection_path": "selection.json",
            "plot_data_path": "plot.csv",
        }

    monkeypatch.setattr(three_dpa_runs, "curate_torque_project", curate_port)
    monkeypatch.setattr(
        three_dpa_runs, "run_request", lambda _request: {"controlled": True}
    )
    monkeypatch.setattr(three_dpa_runs, "_manifest_summary", lambda manifest: manifest)
    result = three_dpa_runs._run_torque_acceptance(
        project_dir=tmp_path / "project", torque_dir=tmp_path / "source"
    )
    assert (
        result["curation"]["selection_path"] == "selection.json"
        and "review_html" not in result["curation"]
    )
    assert calls == [
        (
            tmp_path / "source",
            tmp_path / "project/_torque_curation_projects",
            "3D PA torque acceptance",
        )
    ]


@pytest.mark.parametrize("failed_port", ["selection", "native"])
def test_curation_preparation_failure_keeps_original_cause_and_blocked_receipt(
    tmp_path, monkeypatch, failed_port
):
    source = tmp_path / "original"
    original = _generated_torque_sources(source)
    failure = OSError("generated curation preparation failed")
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(failed_port)
        raise failure

    def native_port(*_args, **_kwargs):
        pytest.fail("Failed selection reached native preparation")

    if failed_port == "selection":
        monkeypatch.setattr(curate, "_auto_torque_event_selection", fail)
        monkeypatch.setattr(studio, "prepare_studio_document", native_port)
    else:
        monkeypatch.setattr(studio, "prepare_studio_document", fail)
    output = tmp_path / "projects"
    with pytest.raises(OSError) as stopped:
        curate.curate_torque_project(
            source, output_root=output, project_name="Failed torque"
        )
    assert stopped.value is failure
    assert calls == [failed_port]
    manifests = list(output.glob("*/intake_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_bytes())
    assert manifest["kind"] == "sciplot_intake_project"
    assert manifest["studio"]["status"] == "blocked"
    assert manifest["studio"]["reason_code"] == "studio_preparation_failed"
    assert manifest["studio"]["error"] == str(failure)
    assert "curation" not in manifest and "files" not in manifest
    assert not list(output.rglob("*.html"))
    assert all(path.read_bytes() == content for path, content, _ in original.values())
