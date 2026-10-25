"""Real saved Veusz creation/reuse keeps scientific identities outside staging."""

import json
import subprocess

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.studio_prepare import prepare_studio_document


@pytest.mark.comprehensive
def test_native_private_creation_and_exact_reuse_publish_only_complete_generations(tmp_path):
    project = tmp_path / "project"
    (project / "source").mkdir(parents=True)
    source = project / "source/data.csv"
    source.write_text("x,y\n0,1\n1,2\n2,4\n", encoding="utf-8")
    original = file_sha256(source)
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": "source/data.csv", "template": "curve"}), encoding="utf-8")
    try:
        result = prepare_studio_document(request)
    except subprocess.CalledProcessError as exc:
        # Retain the real native error without dumping inherited environment.
        pytest.fail(f"native child exit={exc.returncode}: {exc.stderr}", pytrace=False)
    store = FileProjectStore(project)
    after = store.snapshot()
    assert after["sequence"] == 1
    assert result["document"] == str(project / "studio/document.vsz")
    assert result["project_command"]["generation"] == after["generation"]
    assert file_sha256(source) == original
    saved_request = json.loads(request.read_text())
    assert saved_request["input"] == "source/data.csv"
    assert saved_request["transform_ledger"]["source_root"] == str(source)
    native = project / "studio/document.vsz"
    native_hash = file_sha256(native)
    try:
        reopened = prepare_studio_document(project)
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"reopen child exit={exc.returncode}: {exc.stderr}", pytrace=False)
    assert reopened["preserved_existing_document"] is True
    assert file_sha256(native) == native_hash
    assert file_sha256(source) == original
    assert not any("sciplot-studio-candidate-" in name for name in store.snapshot()["files"])
    assert not (project / "studio/.sciplot_store").exists()
