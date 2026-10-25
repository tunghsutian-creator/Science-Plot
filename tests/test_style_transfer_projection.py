"""Literal represented-value and failed-install controls, without native fixtures."""

from copy import deepcopy
import json

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.veusz_worker.style_projection import project_transferred_styles
from sciplot_core.studio_core import style_transfer_storage as storage


def _operation(path, setting, value):
    return {"current_widget": "/page1/graph1/" + path, "setting": setting, "after": value}


def test_existing_slots_preserve_science_and_do_not_promote_opaque_native_state():
    original = {"axes": {"x": {"label": "Charge (C)", "label_size_pt": 7., "line_width_pt": .8}},
                "series": [{"name": "series_1", "color": "red", "x_values": [0., -0.],
                            "y_values": [1., None], "source_binding": {"source_id": "group-A"}}],
                "style": {"font_family": "Arial", "legend_font_size_pt": 7.},
                "legend": {"horz_position": "left", "horz_manual": .2},
                "direct_labels": [{"name": "label_1", "label": "A", "text_size_pt": 7.}]}
    frozen = deepcopy(original)
    result = project_transferred_styles(original, [
        _operation("x", "Label/size", "9pt"), _operation("x", "Line/width", "0.254mm"),
        _operation("x", "TickLabels/size", "12pt"), _operation("x", "Label/font", "Opaque Font"),
        _operation("series_1", "PlotLine/color", "purple"), _operation("series_1", "Label/size", "12pt"),
        _operation("key1", "horzManual", .4), _operation("key1", "Text/size", "8pt"),
        _operation("label_1", "Text/size", "10pt"), _operation("unbound", "Text/size", "30pt"),
    ])
    assert original == frozen
    assert result["axes"]["x"] == {"label": "Charge (C)", "label_size_pt": 9., "line_width_pt": pytest.approx(.72)}
    assert result["series"][0]["color"] == "purple"
    assert "label_size_pt" not in result["series"][0]
    assert result["style"] == {"font_family": "Arial", "legend_font_size_pt": 8.}
    assert result["legend"] == {"horz_position": "left", "horz_manual": .4}
    assert result["direct_labels"] == [{"name": "label_1", "label": "A", "text_size_pt": 10.}]
    for field in ("x_values", "y_values", "source_binding"):
        assert json.dumps(result["series"][0][field]) == json.dumps(original["series"][0][field])


def _stager(_document, target, *, staged_validator):
    path = target.with_suffix(".stage.vsz")
    path.write_bytes(b"new-native")
    try:
        valid = staged_validator(path)
    except Exception:
        path.unlink()
        raise
    return {"staged": str(path), "reopen_validated": valid, "sha256": file_sha256(path)}


@pytest.mark.parametrize("failure", ["staged_audit", "second_install"])
def test_failed_pair_validation_or_install_preserves_both_files(tmp_path, monkeypatch, failure):
    target, spec_path = tmp_path / "document.vsz", tmp_path / "document.spec.json"
    target.write_bytes(b"old-native")
    spec_path.write_bytes(b'{"version":1}\n')
    original = {path: path.read_bytes() for path in (target, spec_path)}
    monkeypatch.setattr(storage, "stage_veusz_document", _stager)
    audits = []

    def audit(path, candidate_spec, *, check_presentation):
        audits.append((path.read_bytes(), json.loads(candidate_spec.read_text()), check_presentation))
        if failure == "staged_audit":
            raise ValueError("literal staged rejection")
        return {"status": "passed"}

    monkeypatch.setattr(storage, "audit_spec_data", audit)
    if failure == "second_install":
        from sciplot_core.project_store import state
        boundary = state.boundary
        def fail(name):
            if name == "before_head" and audits:
                raise ValueError("literal second installation rejection")
            boundary(name)
        monkeypatch.setattr(state, "boundary", fail)
    with pytest.raises(ValueError, match="literal"):
        storage.save_transferred_style_pair(object(), target, spec_path, {"version": 2},
                                            input_hashes={str(path): file_sha256(path) for path in original})
    assert audits == [(b"new-native", {"version": 2}, True)]
    assert all(path.read_bytes() == data for path, data in original.items())
    assert sorted(path.name for path in tmp_path.iterdir() if not path.name.startswith(".sciplot-pair-") and path.name != ".sciplot_session_locks") == ["document.spec.json", "document.vsz"]
    roots = list(tmp_path.glob(".sciplot-pair-*"))
    assert len(roots) == 1
    from sciplot_core.project_store import FileProjectStore, ResourceRoot
    store = FileProjectStore(roots[0], locations={"pair": ResourceRoot(tmp_path, (target.name, spec_path.name))})
    assert set(store.snapshot()["files"]) == {"@pair/document.vsz", "@pair/document.spec.json"}


def test_private_style_candidates_create_no_store_and_preserve_input_bytes(tmp_path, monkeypatch):
    target, spec = tmp_path / "old.vsz", tmp_path / "old.spec.json"
    target.write_bytes(b"old-native")
    spec.write_text('{"version":1}')
    output = tmp_path / "private"
    output.mkdir()
    monkeypatch.setattr(storage, "stage_veusz_document", _stager)
    monkeypatch.setattr(storage, "audit_spec_data", lambda *_a, **_kw: {"status": "passed"})
    result = storage.stage_transferred_style_pair(object(), target, spec, {"version": 2},
        output_document=output / "candidate.vsz", output_spec=output / "candidate.spec.json",
        input_hashes={str(target): file_sha256(target), str(spec): file_sha256(spec)})
    assert result["reopen_validated"]
    assert target.read_bytes() == b"old-native" and json.loads(spec.read_text()) == {"version": 1}
    assert (output / "candidate.vsz").read_bytes() == b"new-native"
    assert json.loads((output / "candidate.spec.json").read_text()) == {"version": 2}
    assert not list(tmp_path.rglob(".sciplot_store")) and not list(tmp_path.rglob(".sciplot-pair-*"))


def test_private_style_worker_skip_still_freezes_pair_without_project_writes(tmp_path, capsys):
    from sciplot_core.veusz_worker import cli
    previous, current = tmp_path / "before.vsz", tmp_path / "current.vsz"
    old_spec, new_spec = tmp_path / "before.json", tmp_path / "current.json"
    previous.write_bytes(b"before unchanged")
    current.write_bytes(b"current unchanged")
    old_spec.write_text('{"template":"old"}')
    new_spec.write_text('{"template":"new"}')
    output = tmp_path / "private"
    args = ["preview-transfer-styles", str(previous), str(current), str(old_spec), str(new_spec),
            "--output-document", str(output / "candidate.vsz"), "--output-spec", str(output / "candidate.json")]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["transfer_status"] == "skipped"
    assert current.read_bytes() == (output / "candidate.vsz").read_bytes() == b"current unchanged"
    assert new_spec.read_bytes() == (output / "candidate.json").read_bytes()
    assert not list(tmp_path.rglob(".sciplot_store"))
    with pytest.raises(ValueError, match="fresh exclusive"):
        cli.main(args)
