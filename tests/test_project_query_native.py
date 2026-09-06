from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.project_query import (
    inspect_project,
    resolve_project_figure,
)


def _inventory(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): file_sha256(p) for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.comprehensive
def test_real_project_query_reopens_saved_native_objects_without_mutating_delivery(
    tmp_path: Path,
):
    source = tmp_path / "UVvis.csv"
    source.write_text(
        "Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
        "A,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n",
        encoding="utf-8",
    )
    visible = tmp_path / "UVvis_SciPlot"
    completed = subprocess.run(
        [
            str(REPO_ROOT / "skill/scripts/sciplot"),
            "studio",
            str(source),
            "--out",
            str(visible),
            "--rule",
            "uvvis_spectrum",
            "--export",
            "pdf,tiff_300",
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    exported = json.loads(completed.stdout)
    assert exported["studio_run"]["ready_to_use"] is True
    project = Path(exported["project_dir"])
    before = _inventory(tmp_path)
    summary = inspect_project(visible / "Open_in_Veusz.command")
    assert summary["project"] == str(project)
    assert summary["source"]["current"] is True
    assert summary["qa"]["current"] is True, summary["qa"]
    assert summary["delivery"]["current"] is True, summary["delivery"]
    assert summary["ready_to_use"] is None and summary["readiness_evaluated"] is False
    figure = resolve_project_figure(project)
    detail = inspect_project(
        project, figure_id=figure["figure_id"], object_path="/page1/graph1/x"
    )
    axis = detail["selected_figure"]["objects"]["/page1/graph1/x"]
    assert axis["type"] == "axis"
    assert axis["target"]["document_sha256"] == file_sha256(Path(exported["document"]))
    assert any(
        field["setting_path"].endswith("/Label/size")
        for field in axis["editable_fields"]
    )
    assert not any(
        field["setting_path"].endswith("/log") for field in axis["editable_fields"]
    )
    assert _inventory(tmp_path) == before

    # A visible artifact mutation does not change ownership or revive old QA.
    pdf = next((visible / "figures").glob("*.pdf"))
    pdf.write_bytes(b"changed delivery artifact")
    stale = inspect_project(visible)
    assert stale["delivery"]["binding_current"] is True
    assert stale["delivery"]["current"] is False
    assert stale["qa"]["current"] is True  # The private, exported artifacts are intact.
    assert file_sha256(source) == before["UVvis.csv"]
