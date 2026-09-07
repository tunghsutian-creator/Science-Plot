from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import task_control, task_execution, task_planning
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def _table(path: Path, *, sample: str = "E3", peak: int = 3) -> Path:
    path.write_text(f"Wavelength,Absorbance\nnm,a.u.\n{sample},{sample}\n400,1\n450,{peak}\n500,2\n")
    return path


@pytest.fixture
def creation_calls(tmp_path, monkeypatch):
    calls = []

    def create(source, **kwargs):
        calls.append({"source": source, **kwargs})
        return {"project_dir": str(tmp_path / "managed"), "studio_run": {"ready_to_use": True}}

    monkeypatch.setattr(task_execution, "create_project", create)
    return calls


def test_profile_does_not_override_conflicting_or_missing_source_evidence(tmp_path, creation_calls):
    source = tmp_path / "FTIR.csv"
    source.write_text("Wavenumber,Absorbance\ncm-1,a.u.\nA,A\n400,1\n450,3\n500,2\n")
    first = task_control.start_task({"version": 1, "action": "create", "source": str(source), "rule_id": "ftir_spectrum"}, task_dir=tmp_path / "first")
    assert first["status"] == "complete"
    # Before the fix this passed profile applicability and drew wavelength
    # values on a wavenumber axis because the forced rule validated itself.
    current = tmp_path / "UVvis.csv"
    current.write_text("400,1\n450,3\n500,2\n")
    second = task_control.start_task({"version": 1, "action": "create", "source": str(current), "profile": first["profile"]}, task_dir=tmp_path / "second")
    assert second["status"] == "needs_input"
    assert len(creation_calls) == 1
    assert second["question"]["reason_code"] == "profile_unavailable"
    # Also reject a fully structured, recognisable source from another family.
    _table(current)
    third = task_control.start_task({"version": 1, "action": "create", "source": str(current), "profile": first["profile"]}, task_dir=tmp_path / "third")
    assert third["status"] == "needs_input"
    assert third["question"]["reason_code"] == "profile_not_applicable"
    assert len(creation_calls) == 1
    resumed = task_control.resume_task(tmp_path / "third", {"rule_id": "uvvis_spectrum"})
    assert resumed["status"] == "complete"
    assert creation_calls[-1]["expected_plan"]["rule_id"] == "uvvis_spectrum"


def test_profile_reuses_headers_but_never_sample_names_or_values(tmp_path, creation_calls):
    source = _table(tmp_path / "UVvis.csv")
    first = task_control.start_task({"version": 1, "action": "create", "source": str(source)}, task_dir=tmp_path / "first")
    profile = json.loads(Path(first["profile"]).read_text())
    assert profile["version"] == 2
    assert profile["signature"]["column_names"] == ["Wavelength", "Absorbance"]
    assert profile["signature"]["declared_units"] == ["nm", "a.u."]
    assert "E3" not in json.dumps(profile["signature"])
    current = _table(tmp_path / "next.csv", sample="E9", peak=10)
    second = task_control.start_task({"version": 1, "action": "create", "source": str(current), "profile": first["profile"]}, task_dir=tmp_path / "second")
    assert second["status"] == "complete"
    plan = creation_calls[-1]["expected_plan"]
    assert plan["scientific_transform"]["output"]["series_order"] == ["E9"]
    assert plan["preview_identity"] != creation_calls[0]["expected_plan"]["preview_identity"]


def test_changed_declared_units_require_a_new_choice(tmp_path, creation_calls):
    source = _table(tmp_path / "UVvis.csv")
    first = task_control.start_task({"version": 1, "action": "create", "source": str(source)}, task_dir=tmp_path / "first")
    current = _table(tmp_path / "next.csv")
    current.write_text(current.read_text().replace("nm,a.u.", "um,a.u."))
    second = task_control.start_task({"version": 1, "action": "create", "source": str(current), "profile": first["profile"]}, task_dir=tmp_path / "second")
    assert second["status"] == "needs_input" and len(creation_calls) == 1


def test_old_rule_default_profile_is_not_treated_as_source_evidence(tmp_path, creation_calls):
    source = _table(tmp_path / "UVvis.csv")
    profile = {"kind": "sciplot_task_profile", "version": 1,
        "selection": {"rule_id": "uvvis_spectrum", "template": "curve"}, "signature": {"source_type": ".csv"}}
    profile["sha256"] = canonical_json_sha256(profile, allow_nan=False)
    path = tmp_path / "old_profile.json"
    path.write_text(json.dumps(profile))
    result = task_control.start_task({"version": 1, "action": "create", "source": str(source), "profile": str(path)}, task_dir=tmp_path / "task")
    assert result["status"] == "needs_input" and not creation_calls


def test_headerless_creation_still_works_without_claiming_reusable_profile(tmp_path, creation_calls):
    source = tmp_path / "FTIR.csv"
    source.write_text("400,1\n450,3\n500,2\n")
    result = task_control.start_task({"version": 1, "action": "create", "source": str(source), "rule_id": "ftir_spectrum"}, task_dir=tmp_path / "task")
    assert result["status"] == "complete" and len(creation_calls) == 1
    assert result["profile"] is None and result["profile_unavailable"]


@pytest.mark.parametrize("answer", [{"rule_id": "not_a_real_rule"}, {"rule_id": "uvvis_spectrum", "template": "pie"}])
def test_wrong_scientific_choice_remains_answerable(tmp_path, monkeypatch, creation_calls, answer):
    source = _table(tmp_path / "UVvis.csv")
    monkeypatch.setattr(task_planning, "inspect_payload", lambda _: {})
    task = tmp_path / "task"
    initial = task_control.start_task({"version": 1, "action": "create", "source": str(source)}, task_dir=task)
    assert initial["status"] == "needs_input"
    rejected = task_control.resume_task(task, answer)
    assert rejected["status"] == "needs_input" and not creation_calls
    assert "question" in rejected and "blocker" not in rejected
    completed = task_control.resume_task(task, {"rule_id": "uvvis_spectrum"})
    assert completed["status"] == "complete" and len(creation_calls) == 1
