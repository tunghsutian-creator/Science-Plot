"""Generated public CLI controls for source-bound performance scatter selection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import pytest

from test_performance_metric_selection import generated_table, selection_for


ROOT = Path(__file__).resolve().parents[1]


def cli(*arguments: str, expected: int = 0) -> dict:
    environment = dict(os.environ)
    environment.update({"QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"})
    result = subprocess.run(
        [str(ROOT / "skill/scripts/sciplot"), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout)


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def plan(source: Path, selection_path: Path, *, expected: int = 0) -> dict:
    return cli(
        "plan",
        str(source),
        "--rule",
        "performance_comparison",
        "--template",
        "scatter",
        "--performance-selection",
        str(selection_path),
        "--json",
        expected=expected,
    )


def test_public_metadata_and_unit_clarification_continue_in_same_plan_route(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path, missing_units=True)
    before = source.read_bytes()
    facts = cli("inspect", str(source), "--performance", "--json")
    assert facts["read_only"] is True
    assert facts["metrics"][1]["metric_id"] == "specific_impact_strength"
    assert facts["metrics"][1]["missing_unit_count"] == 7
    selection = selection_for(source)
    selected = write_json(tmp_path / "selection.json", selection)
    blocked = plan(source, selected, expected=1)
    assert (
        blocked["blocker"]["reason_code"]
        == "performance_metric_unit_confirmation_required"
    )
    selection = selection_for(source, declarations=True)
    write_json(selected, selection)
    confirmed = plan(source, selected)
    assert confirmed["status"] == "planned"
    assert confirmed["source_options"]["performance_selection"] == selection
    task = confirmed["resolved_figure_plan"]["tasks"][0]
    assert task["metric_binding"] == {
        "kind": "cartesian_xy",
        "x_metric": "density",
        "y_metric": "specific_impact_strength",
    }
    assert len(task["sample_order"]) == 6
    selection["y_metric"] = "unknown_metric"
    selection["unit_declarations"] = selection["unit_declarations"][:1]
    write_json(selected, selection)
    rejected = plan(source, selected, expected=1)
    assert rejected["blocker"]["reason_code"] == "performance_metric_unknown"
    assert source.read_bytes() == before
    assert not (tmp_path / "observed_SciPlot").exists()


@pytest.mark.comprehensive
@pytest.mark.parametrize("label_case", ["underscores", "markup", "na_identifiers"])
def test_public_selected_scatter_native_creation_and_cold_export(
    tmp_path: Path,
    label_case: str,
) -> None:
    source = generated_table(tmp_path, missing_units=True)
    metric_ids = {
        "markup": ("rho_{lab}", "energy_[obs]^2"),
        "na_identifiers": ("NA", "N/A"),
    }.get(label_case)
    if metric_ids is not None:
        source.write_text(
            source.read_text()
            .replace("density", metric_ids[0])
            .replace("specific_impact_strength", metric_ids[1])
        )
    if label_case == "na_identifiers":
        source.write_text(
            source.read_text().replace("Material 0", "NA").replace("Material 1", "N/A")
        )
    original = source.read_bytes()
    selected = selection_for(source, declarations=True)
    if metric_ids is not None:
        selected.update({"x_metric": metric_ids[0], "y_metric": metric_ids[1]})
        for declaration, metric in zip(
            selected["unit_declarations"], metric_ids, strict=True
        ):
            declaration["metric_id"] = metric
            declaration["user_statement"] = (
                f"I confirm the original {metric} unit is {declaration['unit']}."
            )
    selection_path = write_json(tmp_path / "selection.json", selected)
    expected = plan(source, selection_path)
    plan_path = write_json(tmp_path / "plan.json", expected)
    created = cli(
        "project",
        "create",
        str(source),
        "--expected-plan",
        str(plan_path),
        "--out",
        str(tmp_path / "selected_delivery"),
        "--json",
    )
    write_json(tmp_path / "created_response.json", created)
    assert created["status"] == "created"
    assert created["studio_run"]["ready_to_use"] is True
    document = Path(created["document"])
    spec_path = (
        document.with_name("spec.json")
        if document.name == "document.vsz"
        else document.with_suffix(".spec.json")
    )
    spec = json.loads(spec_path.read_text())
    assert spec["source_request"]["performance_selection"] == selected
    assert spec["performance_comparison"]["valid_pair_count"] == 6
    assert spec["performance_comparison"]["missing_pair_count"] == 1
    assert spec["visual_data_transforms"] == []
    expected_label = {
        "underscores": r"specific\_impact\_strength",
        "markup": r"energy\_\[obs\]\^2",
        "na_identifiers": "N/A",
    }[label_case]
    assert spec["axes"]["y"]["label"].startswith(expected_label + " (")
    assert "kg⁻¹" in spec["axes"]["y"]["label"]
    assert [spec["series"][i]["x_values"][0] for i in range(3)] == [
        float("1.2345678901234567")
    ] * 3
    # Each CLI invocation is a fresh process. The saved source request and VSZ
    # must remain sufficient for exact native export and source/QA publication.
    exported = cli(
        "studio", str(created["project_dir"]), "--export", "pdf,tiff_300", "--json"
    )
    write_json(tmp_path / "cold_export_response.json", exported)
    assert exported["studio_run"]["ready_to_use"] is True
    assert source.read_bytes() == original
    assert document.is_file()
    delivery = Path(created["studio_run"]["delivery_package"]["path"])
    assert list(delivery.rglob("*.pdf"))
    assert list(delivery.rglob("*.tiff")) or list(delivery.rglob("*.tif"))
    source.write_bytes(original + b"\n")
    drift = cli(
        "studio",
        str(created["project_dir"]),
        "--export",
        "pdf,tiff_300",
        "--json",
        expected=1,
    )
    write_json(tmp_path / "source_drift_rejection.json", drift)
    assert drift["reason_code"] == "performance_selection_source_changed"
    source.write_bytes(original)


def test_public_plan_accepts_per_metric_units_when_unit_column_is_absent(
    tmp_path: Path,
) -> None:
    source = generated_table(tmp_path)
    source.write_text(
        "\n".join(line.rsplit(",", 1)[0] for line in source.read_text().splitlines())
        + "\n"
    )
    selection = selection_for(source, declarations=True)
    selected = write_json(tmp_path / "selection.json", selection)
    preview = plan(source, selected)
    assert preview["source_options"]["performance_selection"] == selection
