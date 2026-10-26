"""Source preservation uses its closed style plan; user edit policy stays strict."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import resolve_runtime_output_path
from sciplot_core.studio_core import document_edit, source_update_styles
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from test_document_style_transfer import _spec, _xy_widgets


@pytest.mark.parametrize("semantic", [False, True], ids=["ordinary-sample-style", "scientific-color-role"])
def test_closed_source_style_plan_preserves_existing_color_and_the_public_policy(tmp_path, monkeypatch, semantic):
    old, new = _spec(("Amber",)), _spec(("Amber", "Blue"))
    for spec in (old, new):
        spec["template"] = "box"
        spec["categorical"] = {"groups": [{"raw_values": [1., 2.], "replicate_count": 2}]}
        if semantic:
            spec["categorical"]["presentation_kind"] = "grouped_bar_error"
        for series in spec["series"]:
            series.update(color="black", y_values=[1., 2.])
    old["series"][0]["color"] = "purple"
    old_widgets, new_widgets = _xy_widgets(("purple",)), _xy_widgets(("black", "green"))
    project = tmp_path / "project"
    (project / "studio").mkdir(parents=True)
    (project / "plot_request.json").write_text("{}")
    (project / "studio/document.vsz").write_bytes(b"controlled new scientific native")
    (project / "studio/spec.json").write_text(json.dumps(new))
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    workers, audits = [], []

    def worker(command, document, *args):
        if command == "inspect-document-state":
            return {"document": {"sha256": file_sha256(document)}, "widgets": new_widgets}
        assert command == "edit-document"
        changes = json.loads(Path(args[1]).read_bytes())
        assert changes == [{"object_path": "/page1/graph1/series_1",
            "setting_path": "/page1/graph1/series_1/PlotLine/color", "expected_value": "black", "value": "purple"}]
        assert "--audit-spec" in args
        candidate = Path(args[args.index("--output-document") + 1])
        assert resolve_runtime_output_path(candidate) == candidate
        candidate.write_bytes(b"controlled new scientific native with preserved color")
        workers.append(changes)
        return {"candidate": {"path": str(candidate)}, "document_audit": {"status": "passed"}}

    def audited(document, spec, *, native_audit):
        assert native_audit == {"status": "passed"}
        audits.append((document.read_bytes(), json.loads(spec.read_bytes())))
        return {"status": "passed"}

    monkeypatch.setattr(source_update_styles, "run_document_worker", worker)
    monkeypatch.setattr(document_edit, "run_document_worker", worker)
    monkeypatch.setattr(document_edit, "audit_edited_document", audited)
    monkeypatch.setattr(source_update_styles, "project_figures", lambda root:
        {"primary": (root / "studio/document.vsz", root / "studio/spec.json")})
    frozen = deepcopy(new)
    with studio_preparation_candidate(store) as candidate:
        root = candidate.project_dir
        result = source_update_styles.transfer_project_styles(root, {"primary": {"spec": old, "widgets": old_widgets}})
        current = json.loads((root / "studio/spec.json").read_bytes())
        assert current["categorical"] == frozen["categorical"]
        assert [item["y_values"] for item in current["series"]] == [[1., 2.], [1., 2.]]
        assert current["series"][0]["color"] == ("black" if semantic else "purple")
        assert current["series"][1] == frozen["series"][1]
        if semantic:
            assert not workers and not audits and result[0]["applied"] == []
        else:
            assert len(workers) == len(audits) == 1 and result[0]["status"] == "passed"
        changes = [{"object_path": "/page1/graph1/series_1",
            "setting_path": "/page1/graph1/series_1/PlotLine/color", "expected_value": current["series"][0]["color"], "value": "red"}]
        with pytest.raises(ValueError, match="uniquely bound ordinary curve"):
            document_edit._candidate(root / "studio/document.vsz", root / "studio/spec.json", changes, tmp_path)
    assert (project / "studio/document.vsz").read_bytes() == b"controlled new scientific native"
