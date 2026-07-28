from __future__ import annotations

import json
from pathlib import Path

from sciplot_core.autoplot.evidence import AutoplotRunEvidence


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

    evidence = AutoplotRunEvidence.load(
        {
            "status": "ready",
            "run_output": str(run_output),
            "project_dir": str(tmp_path),
            "one_step": {"state": "ready", "source_package": {"source_kind": "stale"}},
        }
    )

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
