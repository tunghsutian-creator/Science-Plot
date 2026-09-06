from __future__ import annotations

import json
import csv
import io
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from sciplot_core import cli
import sciplot_core.autoplot.run as autoplot_module
import sciplot_core.plan_preview as preview_module
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plan_identity import preview_identity_for
from sciplot_core.plan_preview import verify_expected_plan


def _source(root: Path) -> Path:
    source = root / "source.csv"
    source.write_text(
        "Wavelength,Absorbance\nnm,a.u.\nPDA-I,PDA-I\n400,0.1\n450,0.2\n500,0.3\n"
    )
    return source


def _preview(source: Path) -> dict[str, Any]:
    result = preview_module.build_plan_preview(
        source, request={"rule_id": "uvvis_spectrum", "template": "curve"}
    )
    assert result["status"] == "planned", result
    return dict(result)


def test_preview_identity_is_repeatable_and_changes_with_source_bytes(tmp_path):
    source = _source(tmp_path)
    first = _preview(source)
    assert _preview(source) == first
    assert first["preview_identity"]["source_tree_sha256"] == source_tree_sha256(source)
    assert verify_expected_plan(source, first, rule_id=None, template=None) == first
    source.write_text(source.read_text().replace("450,0.2", "450,0.25"))
    assert _preview(source)["preview_identity"] != first["preview_identity"]
    with pytest.raises(ValueError, match="Source changed since"):
        verify_expected_plan(source, first, rule_id="uvvis_spectrum", template="curve")


def test_expected_directory_plan_tracks_the_whole_relative_source_inventory(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    _source(folder)
    expected = _preview(folder)
    (folder / "new_measurement.csv").write_text("new source bytes")
    with pytest.raises(ValueError, match="Source changed since"):
        verify_expected_plan(
            folder, expected, rule_id="uvvis_spectrum", template="curve"
        )


@pytest.mark.parametrize("recompute_identity", [False, True])
def test_expected_plan_checks_scientific_contents_not_just_claimed_digest(
    tmp_path, recompute_identity
):
    source = _source(tmp_path)
    expected = _preview(source)
    expected["scientific_transform"]["output"]["series"][0]["point_count"] = 999
    if recompute_identity:
        expected["preview_identity"] = preview_identity_for(
            expected,
            source_sha256=expected["preview_identity"]["source_tree_sha256"],
        )
    with pytest.raises(
        ValueError, match="contents or identity changed|selections changed"
    ):
        verify_expected_plan(
            source, expected, rule_id="uvvis_spectrum", template="curve"
        )


@pytest.mark.parametrize("field,value", [("rule_id", "dsc_curve"), ("template", "box")])
def test_expected_plan_rejects_different_execution_choices(tmp_path, field, value):
    source = _source(tmp_path)
    arguments = {"rule_id": "uvvis_spectrum", "template": "curve", field: value}
    with pytest.raises(ValueError, match="can no longer execute|selections changed"):
        verify_expected_plan(source, _preview(source), **arguments)


@pytest.mark.parametrize("mutation", ["no_identity", "blocked", "extra_field"])
def test_expected_plan_rejects_old_blocked_or_modified_payload(tmp_path, mutation):
    source = _source(tmp_path)
    expected = _preview(source)
    if mutation == "no_identity":
        expected.pop("preview_identity")
    elif mutation == "blocked":
        expected["status"] = "blocked"
    else:
        expected["unreviewed_choice"] = "different"
    with pytest.raises(ValueError):
        verify_expected_plan(
            source, expected, rule_id="uvvis_spectrum", template="curve"
        )


def test_source_changes_during_plan_produce_blocked_preview(tmp_path, monkeypatch):
    source = _source(tmp_path)
    classify = preview_module.classify_source

    def changing_classify(*args, **kwargs):
        result = classify(*args, **kwargs)
        source.write_text(source.read_text().replace("450,0.2", "450,0.25"))
        return result

    monkeypatch.setattr(preview_module, "classify_source", changing_classify)
    result = preview_module.build_plan_preview(
        source, request={"rule_id": "uvvis_spectrum", "template": "curve"}
    )
    assert result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == "plan_source_changed_during_preview"
    assert result["preview_identity"] is None


def test_expected_plan_rechecks_source_after_scientific_comparison(
    tmp_path, monkeypatch
):
    source = _source(tmp_path)
    expected = _preview(source)
    build = preview_module.build_plan_preview

    def changing_preview(*args, **kwargs):
        result = build(*args, **kwargs)
        source.write_text(source.read_text().replace("450,0.2", "450,0.25"))
        return result

    monkeypatch.setattr(preview_module, "build_plan_preview", changing_preview)
    with pytest.raises(ValueError, match="during expected-plan validation"):
        verify_expected_plan(
            source, expected, rule_id="uvvis_spectrum", template="curve"
        )


def test_autoplot_expected_plan_preflight_runs_before_project_creation(
    tmp_path, monkeypatch
):
    source = _source(tmp_path)
    expected = _preview(source)
    source.write_text(source.read_text().replace("450,0.2", "450,0.25"))

    def forbidden_run(*args, **kwargs):
        pytest.fail("Stale expected plan reached project creation")

    monkeypatch.setattr(autoplot_module, "run_one_step", forbidden_run)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Source changed since"):
        autoplot_module.run_autoplot(
            source,
            output_root=output,
            rule_id="uvvis_spectrum",
            template="curve",
            expected_plan=expected,
        )
    assert not output.exists()


def test_autoplot_without_expected_plan_does_not_add_preview_work(
    tmp_path, monkeypatch
):
    source = _source(tmp_path)
    captured = []

    class ReachedExistingRunner(Exception):
        pass

    def existing_runner(*args, **kwargs):
        captured.append(kwargs)
        raise ReachedExistingRunner

    def forbidden_preview(*args, **kwargs):
        pytest.fail("Legacy invocation unexpectedly rebuilt a plan")

    monkeypatch.setattr(autoplot_module, "run_one_step", existing_runner)
    monkeypatch.setattr(preview_module, "build_plan_preview", forbidden_preview)
    with pytest.raises(ReachedExistingRunner):
        autoplot_module.run_autoplot(source, output_root=tmp_path / "output")
    assert captured[0]["rule_id"] is None and captured[0]["template"] is None


def test_cli_passes_expected_plan_as_payload_without_persisting_path(
    tmp_path, monkeypatch, capsys
):
    source = _source(tmp_path)
    expected = _preview(source)
    preview_path = tmp_path / "expected.json"
    preview_path.write_text(json.dumps(expected))
    captured = []

    def capture(*args, **kwargs):
        captured.append(kwargs)
        return {"state": "ready", "ready_to_use": True}

    monkeypatch.setattr(cli, "run_autoplot", capture)
    assert (
        cli.main(
            [
                "autoplot",
                str(source),
                "--rule",
                "uvvis_spectrum",
                "--template",
                "curve",
                "--expected-plan",
                str(preview_path),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ready_to_use"] is True
    assert captured[0]["expected_plan"] == expected
    assert str(preview_path) not in json.dumps(captured[0]["expected_plan"])


@pytest.mark.parametrize("payload", [None, [], True])
def test_cli_cannot_bypass_expected_plan_with_null_or_nonobject(
    tmp_path, monkeypatch, capsys, payload
):
    source = _source(tmp_path)
    preview_path = tmp_path / "invalid_plan.json"
    preview_path.write_text(json.dumps(payload))

    def forbidden(*args, **kwargs):
        pytest.fail("Malformed --expected-plan reached autoplot")

    monkeypatch.setattr(cli, "run_autoplot", forbidden)
    assert (
        cli.main(
            ["autoplot", str(source), "--expected-plan", str(preview_path), "--json"]
        )
        == 1
    )
    failure = json.loads(capsys.readouterr().out)
    assert failure["category"] == "expected_runtime_failure"
    assert "plan JSON object" in failure["message"]


@pytest.mark.comprehensive
def test_real_uvvis_cli_expected_plan_accepts_current_and_rejects_changed_source(
    tmp_path,
):
    repo = Path(__file__).resolve().parents[1]
    original = (
        repo / ".local/reference_data/real_world/uvvis_spectrum/pda_uvvis_spectra.csv"
    )
    if not original.is_file():
        pytest.skip("Local real UV-vis fixture is not installed")
    source = tmp_path / original.name
    shutil.copy2(original, source)
    original_bytes = original.read_bytes()
    preview_path = tmp_path / "plan.json"
    base = [str(repo / "skill/scripts/sciplot")]
    planned = subprocess.run(
        base
        + [
            "plan",
            str(source),
            "--rule",
            "uvvis_spectrum",
            "--template",
            "curve",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert planned.returncode == 0, planned.stderr
    preview_path.write_text(planned.stdout)
    command = base + [
        "autoplot",
        str(source),
        "--rule",
        "uvvis_spectrum",
        "--template",
        "curve",
        "--expected-plan",
        str(preview_path),
        "--json",
    ]
    blocked_output = tmp_path / "blocked_delivery"
    rows = list(csv.reader(io.StringIO(source.read_text())))
    rows[3][1] = str(float(rows[3][1]) + 0.01)
    with source.open("w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    existing_paths = set(tmp_path.rglob("*"))
    stale = subprocess.run(
        command + ["--out", str(blocked_output)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert stale.returncode == 1
    assert "Source changed since" in json.loads(stale.stdout)["message"]
    assert not blocked_output.exists()
    assert set(tmp_path.rglob("*")) == existing_paths
    source.write_bytes(original_bytes)
    accepted = subprocess.run(
        command + ["--out", str(tmp_path / "delivery")],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    payload = json.loads(accepted.stdout)
    assert payload["state"] == "ready" and payload["ready_to_use"] is True
    assert original.read_bytes() == original_bytes
    request = json.loads(Path(payload["request_path"]).read_text())
    assert "expected_plan" not in request and str(preview_path) not in json.dumps(
        request
    )
