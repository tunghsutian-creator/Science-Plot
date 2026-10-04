"""Explicit display text is caller-owned and cannot mutate scientific arrays."""

from copy import deepcopy
import json

import pytest

from sciplot_core import cli
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.rheology_tts_style import prepare_tts_presentation
from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
from sciplot_core.workflow.rheology_tts_style_update import (
    _assert_same_science, _encoding_values, _presentation_plan, apply_suite_style,
)


def _plan():
    return prepare_tts_presentation({"version": 1, "figure_layout": "separate_polymer_modulus",
        "source_binding": {"sources": []}, "transform_ledger": {"actual_mean_C": 219.83},
        "figures": [{"id": "Caller_Supplied", "panels": [{"id": "graph1", "title": "Original data",
            "x_label": "ω", "y_label": "G′", "legend": "lower_right", "series": [
                {"label": "219.8 °C", "role": "measured_curve", "x": [10, 1, .1], "y": [93.1, 64.2, 5.01]},
                {"label": "209.9 °C", "role": "measured_curve", "x": [10, 1, .1], "y": [81.3, 55.6, 4.02]},
            ]}]}]})


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_prepared_display_labels_and_legend_move_keep_science_and_ids_exact(tmp_path):
    old = _plan()
    supplied = deepcopy(old)
    panel = supplied["figures"][0]["panels"][0]
    panel["series"][0]["label"], panel["series"][1]["label"] = "220 °C", "210 °C"
    panel["legend"] = "upper_left"
    path = _write(tmp_path / "explicit_labels.json", supplied)
    candidate, binding = _presentation_plan(old, path, authoritative_paths=())
    assert candidate == supplied and old == _plan()
    assert binding == {"path": str(path), "sha256": file_sha256(path)}
    before, after = [compile_tts_spec(plan)["figures"][0] for plan in (old, candidate)]
    _assert_same_science(before, after)
    assert _encoding_values(before) != _encoding_values(after)
    assert [s["name"] for s in before["panels"][0]["series"]] == [s["name"] for s in after["panels"][0]["series"]]
    assert [s["legend_key"] for s in after["panels"][0]["series"]] == ["220 °C", "210 °C"]
    assert candidate["transform_ledger"]["actual_mean_C"] == 219.83


@pytest.mark.parametrize("change", ["value", "axis", "source", "transform", "title", "role", "position", "hidden", "identity"])
def test_display_plan_rejects_any_unrelated_change_before_native_work(tmp_path, change):
    old = _plan()
    modified = deepcopy(old)
    panel = modified["figures"][0]["panels"][0]
    if change == "value":
        panel["series"][0]["y"][0] += 1
    elif change == "axis":
        panel["x_min"] = 0
    elif change == "source":
        modified["source_binding"]["sources"] = [{"path": "different", "sha256": "changed"}]
    elif change == "transform":
        modified["transform_ledger"]["actual_mean_C"] = 220
    elif change == "title":
        panel["title"] = "New interpretation"
    elif change == "role":
        panel["series"][0]["role"] = "master_points"
    elif change == "position":
        panel["legend"] = "arbitrary"
    elif change == "hidden":
        panel["legend"] = False
    else:
        panel["series"][0]["series_id"] = "changed"
    with pytest.raises(ValueError):
        _presentation_plan(old, _write(tmp_path / "plan.json", modified), authoritative_paths=())


def test_compiled_science_guard_ignores_only_display_text_and_legend_position():
    old = compile_tts_spec(_plan())["figures"][0]
    new = deepcopy(old)
    new["panels"][0]["series"][0]["legend_key"] = "220 °C"
    _assert_same_science(old, new)
    new["panels"][0]["series"][0]["name"] = "renamed_native_widget"
    with pytest.raises(ValueError):
        _assert_same_science(old, new)


def test_plan_dependency_change_blocks_apply_before_publication(tmp_path, monkeypatch):
    from sciplot_core.workflow import rheology_tts_style_update as update
    from sciplot_core.workflow import rheology_tts_suite as suite

    workspace = tmp_path / "suite"
    delivery = tmp_path / "delivery"
    directory = workspace / "style_previews" / "case"
    directory.mkdir(parents=True)
    external = _write(tmp_path / "provided.json", _plan())
    preview = {"workspace": str(workspace), "delivery": str(delivery), "sources": [],
        "presentation_plan": {"path": str(external), "sha256": file_sha256(external)}}
    path = _write(directory / "preview.json", preview)
    (directory / "preview.sha256").write_text(canonical_json_sha256(preview))
    external.write_text("changed after preview")
    monkeypatch.setattr(update, "_load", lambda _: (workspace, {"delivery": str(delivery)}))
    monkeypatch.setattr(suite, "_check_sources", lambda _: None)
    monkeypatch.setattr(update, "publish_files", lambda *a, **kw: pytest.fail("must reject before publishing"))
    with pytest.raises(ValueError, match="Stale external presentation plan"):
        apply_suite_style(workspace, path)
    assert not (directory / "backup").exists()


def test_public_cli_and_capabilities_advertise_and_forward_explicit_plan(tmp_path, monkeypatch):
    from sciplot_core.cli.dispatch.rheology import dispatch_rheology
    from sciplot_core.workflow import rheology_tts_style_update as update

    workspace, plan = tmp_path / "suite", tmp_path / "labels.json"
    args = cli._build_parser().parse_args(["rheology", "style-preview", str(workspace),
                                           "--presentation-plan", str(plan), "--json"])
    seen = []
    monkeypatch.setattr(update, "preview_suite_style", lambda w, **kw: seen.append((w, kw)) or {"status": "no_change"})
    assert dispatch_rheology(args) == 0
    assert seen == [(workspace, {"presentation_plan": plan})]
    capability = rheology_capabilities()
    assert "--presentation-plan" in capability["actions"]["style_preview"]
    assert capability["presentation_update"]["allowed_changes"] == ["series.label", "panel.legend"]
    assert "never rounds" in capability["presentation_update"]["temperature_labels"]
