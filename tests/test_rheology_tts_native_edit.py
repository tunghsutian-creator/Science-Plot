"""Bounded native legend edits retain saved data, conflicts and manual authority."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_render import (
    audit_tts_document,
    export_tts_document,
    render_tts_figures,
    restyle_tts_document,
)
from test_rheology_tts_render import _native_settings, _spec


@pytest.fixture
def native_figure(tmp_path):
    result = render_tts_figures(_spec(), tmp_path / "original")["figures"][0]
    return (
        Path(result["document"]),
        json.loads(Path(result["spec_path"]).read_text())["figure"],
    )


def test_legend_labels_positions_and_empty_keys_use_native_candidate(
    native_figure, tmp_path
):
    source, old = native_figure
    new = deepcopy(old)
    new["panels"][0]["legend"] = "lower_right"
    new["panels"][0]["series"][0].update(label="210", legend_key="210")
    new["panels"][1]["series"][0]["legend_key"] = "Summary"
    source_sha = file_sha256(source)
    candidate = tmp_path / "candidate.vsz"
    result = restyle_tts_document(source, candidate, old, new, source_sha)
    assert file_sha256(source) == source_sha
    assert result["candidate_audit"]["dataset_count"] == 6
    assert result["candidate_audit"]["presentation"]["template_match"] is True
    assert {change["field"] for change in result["changes"]} == {
        "key",
        "keys",
        "horzPosn",
        "vertPosn",
    }
    assert _native_settings(
        candidate,
        reads=[
            "/page1/a/series_1/key",
            "/page1/b/series_1/keys",
            "/page1/a/key1/horzPosn",
            "/page1/a/key1/vertPosn",
        ],
    ) == {
        "/page1/a/series_1/key": "210",
        "/page1/b/series_1/keys": ["Summary"],
        "/page1/a/key1/horzPosn": "right",
        "/page1/a/key1/vertPosn": "bottom",
    }
    blank = deepcopy(new)
    blank["panels"][0]["series"][0]["legend_key"] = ""
    blank["panels"][1]["series"][0]["legend_key"] = ""
    hidden = tmp_path / "blank_keys.vsz"
    restyle_tts_document(candidate, hidden, new, blank, file_sha256(candidate))
    assert _native_settings(
        hidden, reads=["/page1/a/series_1/key", "/page1/b/series_1/keys"]
    ) == {"/page1/a/series_1/key": "", "/page1/b/series_1/keys": [""]}
    assert (
        audit_tts_document(hidden, blank, check_presentation=True)["status"] == "passed"
    )


@pytest.mark.parametrize("target", ["label", "position"])
def test_native_legend_target_conflicts_preserve_document(
    native_figure, tmp_path, target
):
    source, old = native_figure
    new = deepcopy(old)
    if target == "label":
        new["panels"][0]["series"][0]["legend_key"] = "210"
        edit = ("/page1/a/series_1/key", "Manual text")
    else:
        new["panels"][0]["legend"] = "lower_right"
        edit = ("/page1/a/key1/horzPosn", "centre")
    _native_settings(source, edits=[edit])
    current_sha = file_sha256(source)
    candidate = tmp_path / "rejected.vsz"
    with pytest.raises((ValueError, RuntimeError), match="Native style conflict"):
        restyle_tts_document(source, candidate, old, new, current_sha)
    assert not candidate.exists()
    assert file_sha256(source) == current_sha


def test_label_only_edit_preserves_manual_legend_and_exact_reexport(
    native_figure, tmp_path
):
    source, old = native_figure
    manual = [
        ("/page1/a/key1/horzPosn", "right"),
        ("/page1/a/key1/Text/size", "9pt"),
        ("/page1/a/x/label", "Manual axis label"),
    ]
    _native_settings(source, edits=manual)
    new = deepcopy(old)
    new["panels"][0]["series"][0]["legend_key"] = "T_210"
    candidate = tmp_path / "candidate.vsz"
    result = restyle_tts_document(source, candidate, old, new, file_sha256(source))
    assert [change["field"] for change in result["changes"]] == ["key"]
    values = _native_settings(
        candidate, reads=[p for p, _ in manual] + ["/page1/a/series_1/key"]
    )
    assert all(values[path] == value for path, value in manual)
    assert values["/page1/a/series_1/key"] == r"T\_210"
    with pytest.raises((ValueError, RuntimeError), match="presentation differs"):
        audit_tts_document(candidate, new, check_presentation=True)
    _native_settings(candidate, edits=[("/page1/a/series_1/key", "Human label")])
    before_export = file_sha256(candidate)
    exported = export_tts_document(candidate, tmp_path / "export" / candidate.stem, new)
    assert file_sha256(candidate) == before_export == exported["document_sha256"]
    differences = exported["native_audit"]["presentation"]["differences"]
    assert {"key", "horzPosn"} <= {item["field"] for item in differences}


def test_restyle_rejects_nonlegend_layout_and_legend_inventory_changes(
    native_figure, tmp_path
):
    source, old = native_figure
    cases = []
    for field, value in (
        ("legend", False),
        ("legend", "manual"),
        ("rect_mm", [1, 0, 80, 80]),
    ):
        changed = deepcopy(old)
        changed["panels"][0][field] = value
        cases.append(changed)
    changed = deepcopy(old)
    changed["panels"][0]["axes"]["x"]["label"] = "Changed scientific label"
    cases.append(changed)
    current_sha = file_sha256(source)
    for index, new in enumerate(cases):
        candidate = tmp_path / f"rejected_{index}.vsz"
        with pytest.raises((ValueError, RuntimeError), match="Restyle"):
            restyle_tts_document(source, candidate, old, new, current_sha)
        assert not candidate.exists()
        assert file_sha256(source) == current_sha
