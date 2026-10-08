"""Public canonical lifecycle acceptance with real native compilation and deletion."""

import json
from pathlib import Path
import re
import shutil

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, read
from managed_plot_helpers import patch, request_for_source


@pytest.mark.comprehensive
def test_managed_rebuild_theme_source_transform_and_independent_plot(tmp_path):
    request = request_for_source(tmp_path)
    request_b = request_for_source(tmp_path, "B")
    service = PlotService()
    observations = {}
    try:
        created = service.create(request)
        assert created["ready_to_use"], created
        root = Path(created["plot"])
        a = service.describe(root)
        assert a["plot_type"] == "ManagedPlot" and a["authority"]["rebuild_from_document"]
        head = load_head(root)
        native = Path(head["binding"]["document"])
        ir = read(Path(head["binding"]["ir_path"]))
        png = (native.parent / "preview.png").read_bytes()
        expected_native_state = read(native.parent / "build.json")["native_state_hash"]
        # All generated native/render/export and IR cache files are disposable.
        shutil.rmtree(Path(head["binding"]["output"]))
        shutil.rmtree(root / "ir")
        assert service.describe(root)["artifact_status"] == "missing"
        rebuilt = service.export(root)
        assert rebuilt["ready_to_use"] and rebuilt["revision"] == 0
        assert read(Path(head["binding"]["ir_path"])) == ir
        assert (native.parent / "preview.png").read_bytes() == png
        assert read(native.parent / "build.json")["native_state_hash"] == expected_native_state
        assert rebuilt["scientific_hash"] == a["scientific_hash"] and rebuilt["ir_hash"] == a["ir_hash"]
        observations["A"] = {"created": created, "rebuilt": rebuilt, "pixels_equal": True,
                             "native_state_equal": True, "ir_equal": True}

        b_created = service.create(request_b)
        b_root = Path(b_created["plot"])
        b_before = service.describe(b_root)
        theme = {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "presentation", "rules": [
            {"target": ["axis:x", "axis:y"], "property": "font.size", "value": "10pt"},
            {"target": ["series:A"], "property": "style.line.width", "value": "1.2pt"}]}
        themed = service.patch(root, patch(a, "theme", "theme", theme, "figure:main"))
        assert themed["ready_to_use"] and themed["scientific_hash"] == a["scientific_hash"]
        assert themed["presentation_hash"] != a["presentation_hash"] and themed["ir_hash"] != a["ir_hash"]
        assert service.describe(b_root)["revision"] == b_before["revision"]
        observations["B"] = themed

        parameters = {"columns": ["column:1"], "method": "constant", "constant": 16, "output_unit": "1"}
        normalized = service.patch(root, patch(themed, "normalize", "transform.parameters", parameters,
                                               "transform:normalize-A", scientific=True))
        assert normalized["ready_to_use"] and normalized["scientific_hash"] != themed["scientific_hash"]
        assert normalized["transform_execution"]["executed"] == ["normalize-A"]
        b_after = service.describe(b_root)
        assert b_after["scientific_hash"] == b_before["scientific_hash"] and b_after["dependencies"]["invalidated"] == []
        observations["D"] = normalized

        source = Path(request["data_binding"]["data_sources"][0]["path"])
        source.write_text(source.read_text().replace("2,8", "2,6"))
        dirty = service.describe(root)
        assert {"source:A", "transform:normalize-A", "compile", "render", "export"} <= set(dirty["dependencies"]["invalidated"])
        assert service.describe(b_root)["status"] == "current"
        with pytest.raises(EngineError):
            service.patch(root, patch(normalized, "stale-style", "style.line.width", ".8pt", "series:A"))
        refreshed = service.patch(root, patch(normalized, "source", "source.sha256", file_sha256(source), "source:A", scientific=True))
        assert refreshed["ready_to_use"] and refreshed["scientific_hash"] != normalized["scientific_hash"]
        assert service.describe(b_root)["dependencies"]["invalidated"] == []
        observations["C"] = {"dirty": dirty, "refreshed": refreshed, "unrelated_plot_current": True}

        native = Path(load_head(root)["binding"]["document"])
        # A native-only unrepresented marker-size change cannot enter canonical state.
        original = native.read_text()
        changed, count = re.subn(r"Set\('markerSize', '[^']+'\)", "Set('markerSize', '19pt')", original)
        assert count == 1
        native.write_text(changed)
        stale = service.describe(root)
        assert stale["external_mutation"]["classification"] == "opaque_native_change"
        with pytest.raises(EngineError):
            service.export(root)
        assert load_head(root)["document"]["revision"] == refreshed["revision"]
        assert service.describe(b_root)["status"] == "current"
        observations["F_managed"] = stale
        evidence = REPO_ROOT / ".tmp_verify/managed_architecture_20261008/engine_acceptance.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(observations, ensure_ascii=False, indent=2))
    finally:
        service.close()
