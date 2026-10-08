"""A human-saved VSZ can rejoin semantic history without being regenerated."""

import json
from pathlib import Path
import re
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head


@pytest.mark.comprehensive
@pytest.mark.parametrize("opaque", [False, True])
def test_native_save_reimport_keeps_actual_bytes_and_reopens_editable_state(tmp_path, opaque):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    original = source.read_bytes()
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
                              "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
                             capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    project = Path(json.loads(created.stdout)["project_dir"])
    service = PlotService()
    try:
        opened = service.open(project)
        root = Path(opened["plot"])
        head = load_head(root)
        native = Path(head["binding"]["document"])
        text, count = re.subn(r"Set\('PlotLine/width', '[^']+'\)", "Set('PlotLine/width', '0.63pt')", native.read_text())
        assert count == 2
        if opaque:
            text, margins = re.subn(r"Set\('rightMargin', '[^']+'\)", "Set('rightMargin', '0.91cm')", text)
            assert margins == 1
        native.write_text(text)
        saved = native.read_bytes()
        stale = service.describe(root)
        assert stale["status"] == "stale"
        review = service.decide(root, stale["next_step"]["request"])
        assert review["status"] == "needs_review" and review["scientific_audit"]["status"] == "passed"
        transaction = json.loads(Path(review["evidence"]).read_text())
        mutation = transaction["external_mutation"]
        assert mutation["authority"] == "LegacyPlot"
        assert mutation["classification"] == ("opaque_native_change" if opaque else "known_semantic_delta")
        assert mutation["represented_diff"] == [{"target": name, "property": "style.line.width",
            "before": opened["objects"][name]["properties"]["style.line.width"], "after": "0.63pt"}
            for name in ("series:E2", "series:E4")]
        service.close()
        service = PlotService()
        result = service.decide(root, review["next_step"]["request"])
        assert result["ready_to_use"] and result["revision"] == 1
        assert result["scientific_hash"] == opened["scientific_hash"]
        assert native.read_bytes() == saved and source.read_bytes() == original
        current = service.describe(root)
        assert current["objects"]["series:E2"]["properties"]["style.line.width"] == "0.63pt"
        assert service.decide(root, stale["next_step"]["request"])["replayed"]
        patched = service.patch(root, {"plot_id": opened["plot_id"], "base_revision": 1,
            "idempotency_key": "after-human-save", "intent_class": "presentation", "changes": [
                {"op": "set", "target": ["series:E2"], "property": "style.line.width", "value": "0.7pt"}]})
        assert patched["ready_to_use"] and patched["revision"] == 2
        evidence = REPO_ROOT / f".tmp_verify/document_migration_20261007/external_mutation_legacy_{'opaque' if opaque else 'known'}.json"
        evidence.write_text(json.dumps({"stale": stale, "review": review, "accepted": result,
                                       "external_mutation": mutation, "subsequent_patch": patched,
                                       "source_unchanged": source.read_bytes() == original},
                                      ensure_ascii=False, indent=2))
    finally:
        service.close()
