from __future__ import annotations

import json
from pathlib import Path

import pytest

import sciplot_core.autoplot.run as run_module


def test_run_autoplot_forwards_request_and_persists_exact_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "source.csv"
    output_root = tmp_path / "outputs"
    delivery_root = tmp_path / "delivery"
    run_output = output_root / "project" / "run"
    one_step_result = {"state": "ready", "result": {"figure": "figure.pdf"}}
    captured: dict[str, object] = {}

    def fake_run_one_step(source: Path, **kwargs: object) -> dict[str, object]:
        captured["source"] = source
        captured.update(kwargs)
        return one_step_result

    def fake_build_summary(result: dict[str, object]) -> dict[str, object]:
        assert result is one_step_result
        return {
            "kind": "sciplot_autoplot_result",
            "state": "ready",
            "ready_to_use": True,
            "run_output": str(run_output),
            "nested": {"value": 1},
        }

    monkeypatch.setattr(run_module, "run_one_step", fake_run_one_step)
    monkeypatch.setattr(run_module, "build_autoplot_summary", fake_build_summary)

    result = run_module.run_autoplot(
        input_path,
        output_root=output_root,
        project_name="project",
        delivery_root=delivery_root,
        template="box_strip",
    )

    summary_path = run_output / "autoplot_summary.json"
    assert captured == {
        "source": input_path,
        "output_root": output_root,
        "project_name": "project",
        "delivery_root": delivery_root,
        "template": "box_strip",
    }
    assert result["summary_path"] == str(summary_path)
    assert json.loads(summary_path.read_text(encoding="utf-8")) == result
