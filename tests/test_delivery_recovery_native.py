from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT, resolve_fixture_path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.studio_core.delivery_recovery import (
    apply_delivery_recovery,
    preview_delivery_recovery,
)
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.veusz_runtime import veusz_worker_environment


def _edit_native(path: Path, *, dataset: str | None = None) -> None:
    mutation = (
        f"values = list(i.GetData({dataset!r})[0])\nvalues[0] += 1\ni.SetData({dataset!r}, values)"
        if dataset is not None
        else "i.To('/page1/graph1/x')\ni.Set('Label/size', '8pt')"
    )
    code = f"""
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document, dataimport, widgets
from veusz.document import CommandInterface
app = QtWidgets.QApplication([])
doc = document.Document()
doc.load({str(path)!r})
i = CommandInterface(doc)
{mutation}
i.Save({str(path)!r})
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        env=veusz_worker_environment(),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.comprehensive
def test_visible_native_style_recovery_then_normal_project_delivery(tmp_path: Path):
    source = tmp_path / "DSC.csv"
    shutil.copy2(resolve_fixture_path(str(get_rule("dsc_curve").fixture_path)), source)
    visible = tmp_path / "DSC_SciPlot"
    command = [
        str(REPO_ROOT / "skill/scripts/sciplot"),
        "studio",
        str(source),
        "--out",
        str(visible),
        "--rule",
        "dsc_curve",
        "--export",
        "pdf,tiff_300",
        "--json",
    ]
    first = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert first.returncode == 0, first.stdout + first.stderr
    payload = json.loads(first.stdout)
    assert payload["studio_run"]["ready_to_use"] is True
    project, document = Path(payload["project_dir"]), Path(payload["document"])
    candidate = Path(
        payload["studio_run"]["delivery_package"]["project_documents"][0]["path"]
    )
    original = document.read_bytes()
    raw_hashes = {
        str(p): file_sha256(p) for p in (project / "raw").rglob("*") if p.is_file()
    }
    spec = json.loads((project / "studio/spec.json").read_text())

    _edit_native(candidate, dataset=spec["series"][0]["y_name"])
    rejected = preview_delivery_recovery(project)
    assert rejected["ready_to_apply"] is False
    assert "audit" in rejected["message"].lower()
    assert document.read_bytes() == original
    assert not (project / ".recovery").exists()

    # Restore the exact fixture baseline, then edit through native Veusz only.
    candidate.write_bytes(original)
    _edit_native(candidate)
    edited = candidate.read_bytes()
    assert edited != original
    preview = preview_delivery_recovery(project)
    assert preview["status"] == "ready", preview
    recovered = apply_delivery_recovery(project, preview)
    assert Path(recovered["archive"]).read_bytes() == original
    assert document.read_bytes() == candidate.read_bytes() == edited

    published = export_project_document(
        project_dir=project, formats=["pdf", "tiff_300"]
    )
    assert published.ready_to_use is True, published.run_payload
    run = published.run_payload
    assert run["delivery_package"]["path"] == str(visible)
    delivered = Path(run["delivery_package"]["project_documents"][0]["path"])
    assert delivered.name != candidate.name
    assert not candidate.exists()
    assert delivered.read_bytes() == document.read_bytes() == edited
    assert published.document_sha256 == file_sha256(document)
    assert run["delivery_verification"]["passed"] is True
    assert {
        str(p): file_sha256(p) for p in (project / "raw").rglob("*") if p.is_file()
    } == raw_hashes
