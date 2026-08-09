from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.autoplot.evidence import AutoplotRunEvidence


pytestmark = pytest.mark.focused


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_autoplot_evidence_prefers_the_persisted_one_step_record(
    tmp_path: Path,
) -> None:
    run_output = tmp_path / "run_001"
    run_output.mkdir()
    one_step = {
        "state": "ready",
        "source_package": {
            "source_kind": "table",
            "confidence_band": "high",
        },
        "mapping_package": {
            "semantic_family": "rheology",
            "rule_id": "rheology_frequency_sweep",
        },
        "render_request": {
            "recipe": "auto",
            "template": "curve",
            "exports": ["pdf"],
        },
        "figure_qa_report": {"status": "passed"},
    }
    _write_json(run_output / "one_step_status.json", one_step)
    _write_json(
        run_output / "manifest.json",
        {
            "kind": "sciplot_run",
            "state": "ready",
            "one_step": one_step,
            "semantic": {"semantic_family": "ignored_fallback"},
        },
    )

    reported = {
        "status": "ready",
        "run_output": str(run_output),
        "project_dir": str(tmp_path),
        "one_step": {"state": "ready", "source_package": {"source_kind": "stale"}},
    }
    before = deepcopy(reported)

    evidence = AutoplotRunEvidence.load(reported)

    assert evidence.status_valid is True
    assert evidence.manifest_valid is True
    assert evidence.effective_one_step == one_step
    assert evidence.figure_qa == {"status": "passed"}
    assert evidence.route_package() == {
        "mode": "one_step",
        "source_kind": "table",
        "semantic_family": "rheology",
        "rule_id": "rheology_frequency_sweep",
        "confidence_band": "high",
        "recipe": "auto",
        "template": "curve",
        "figure_size": None,
        "exports": ["pdf"],
    }
    assert evidence.preparation_state_claims == ("ready", "ready", "ready")
    assert evidence.publish_state_claims == ("ready", "ready")
    assert reported == before


def test_autoplot_evidence_fails_closed_on_invalid_persisted_json(
    tmp_path: Path,
) -> None:
    run_output = tmp_path / "run_002"
    run_output.mkdir()
    (run_output / "one_step_status.json").write_text("{broken", encoding="utf-8")
    _write_json(run_output / "manifest.json", {"kind": "wrong"})

    evidence = AutoplotRunEvidence.load(
        {
            "status": "unknown",
            "run_output": str(run_output),
            "one_step": {"state": "needs_rule_repair"},
        }
    )

    assert evidence.status_valid is False
    assert evidence.manifest_valid is False
    assert evidence.effective_one_step == {"state": "needs_rule_repair"}
    assert evidence.delivery_package == {}


@pytest.mark.parametrize(
    ("status_text", "manifest_text"),
    [
        (None, None),
        ("{broken", "{broken"),
        ("[]", '"not-an-object"'),
    ],
)
def test_missing_malformed_and_non_object_json_use_reported_fallback(
    tmp_path: Path,
    status_text: str | None,
    manifest_text: str | None,
) -> None:
    run_output = tmp_path / "run"
    run_output.mkdir()
    if status_text is not None:
        (run_output / "one_step_status.json").write_text(
            status_text,
            encoding="utf-8",
        )
    if manifest_text is not None:
        (run_output / "manifest.json").write_text(
            manifest_text,
            encoding="utf-8",
        )
    reported = {
        "run_output": str(run_output),
        "one_step": {"state": "needs_rule_repair"},
    }

    evidence = AutoplotRunEvidence.load(reported)

    assert evidence.persisted_status == {}
    assert evidence.manifest == {}
    assert evidence.status_valid is False
    assert evidence.manifest_valid is False
    assert evidence.effective_one_step == reported["one_step"]


def test_reported_and_manifest_fallbacks_have_one_explicit_precedence(
    tmp_path: Path,
) -> None:
    run_output = tmp_path / "run"
    run_output.mkdir()
    manifest_one_step = {
        "state": "ready",
        "figure_qa_report": {"status": "manifest"},
        "intervention_package": {"required": True},
        "validated_envelope": {"state": "manifest"},
        "source_package": {"source_kind": "manifest_source"},
        "mapping_package": {
            "semantic_family": "manifest_mapping",
            "rule_id": "manifest_rule",
        },
        "render_request": {},
    }
    _write_json(
        run_output / "manifest.json",
        {
            "kind": "sciplot_run",
            "state": "ready",
            "one_step": manifest_one_step,
            "delivery_package": {"path": "manifest_delivery"},
            "semantic": {
                "semantic_family": "semantic_fallback",
                "rule_id": "semantic_rule",
            },
            "result": {"template": "result_fallback"},
        },
    )
    reported = {
        "status": "needs_human_confirmation",
        "run_output": str(run_output),
        "one_step": {
            "state": "needs_rule_repair",
            "figure_qa_report": {"status": "reported"},
            "intervention_package": [],
            "source_package": {
                "source_kind": "reported_source",
                "confidence_band": "high",
            },
            "mapping_package": {
                "semantic_family": "reported_mapping",
                "rule_id": "reported_rule",
                "confidence_band": "medium",
            },
            "render_request": {
                "recipe": "auto",
                "template": "reported_template",
                "figure_size": "60x55",
                "exports": ["pdf", "tiff_300"],
            },
        },
    }

    evidence = AutoplotRunEvidence.load(reported)

    assert evidence.effective_one_step == reported["one_step"]
    assert evidence.preparation_state_claims == ("needs_rule_repair", "ready")
    assert evidence.publish_state_claims == (
        "needs_human_confirmation",
        "ready",
    )
    assert evidence.figure_qa == {"status": "reported"}
    assert evidence.intervention == {"required": True}
    assert evidence.validated_envelope == {"state": "manifest"}
    assert evidence.delivery_package == {"path": "manifest_delivery"}
    assert evidence.manifest_delivery_package == {"path": "manifest_delivery"}
    assert evidence.route_package() == {
        "mode": "one_step",
        "source_kind": "reported_source",
        "semantic_family": "reported_mapping",
        "rule_id": "reported_rule",
        "confidence_band": "high",
        "recipe": "auto",
        "template": "reported_template",
        "figure_size": "60x55",
        "exports": ["pdf", "tiff_300"],
    }

    manifest_only = AutoplotRunEvidence.load(
        {"run_output": str(run_output), "one_step": []}
    )
    assert manifest_only.effective_one_step == manifest_one_step
    assert manifest_only.figure_qa == {"status": "manifest"}
    assert manifest_only.route_package()["template"] == "result_fallback"


def test_manifest_one_step_and_path_defaults_are_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    reported: dict[str, object] = {"one_step": []}
    before = deepcopy(reported)

    evidence = AutoplotRunEvidence.load(reported)

    assert evidence.run_output == Path(".")
    assert evidence.project_dir == Path(".")
    assert evidence.status_path == Path("one_step_status.json")
    assert evidence.manifest_path == Path("manifest.json")
    assert evidence.effective_one_step == {}
    assert evidence.route_package() == {
        "mode": "one_step",
        "source_kind": "unknown",
        "semantic_family": "unknown",
        "rule_id": None,
        "confidence_band": "unknown",
        "recipe": None,
        "template": None,
        "figure_size": None,
        "exports": [],
    }
    assert reported == before
