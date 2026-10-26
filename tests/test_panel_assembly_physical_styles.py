"""Native relative typography/strokes cannot silently resize scientific styles."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.panel_assembly.errors import AssemblyError
from sciplot_core.panel_assembly.export import export_document
from sciplot_core.panel_assembly.model import new_document
from sciplot_core.panel_assembly.sources import capture_source
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.veusz_runtime import veusz_worker_environment


@pytest.mark.comprehensive
@pytest.mark.parametrize("style", ["axis-font", "inherited-font", "curve-stroke"])
def test_actual_native_relative_physical_style_refuses_export_with_actionable_details(tmp_path, style):
    from test_panel_assembly_export import add
    from sciplot_core.studio_core.project_query import inspect_project
    from sciplot_core.task_control import start_task

    raw = tmp_path / "UVvis.csv"
    raw.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n")
    created = start_task({"version": 1, "action": "create", "source": str(raw)}, task_dir=tmp_path / "create",
                         defer_creation_export=True)
    assert created["status"] == "complete", created
    project = Path(created["project"])
    native = project / "studio/document.vsz"
    target = "/page1/graph1/series_1/PlotLine/width" if style == "curve-stroke" else "/page1/graph1/x/Label/size"
    script = tmp_path / "native-relative-style.py"
    if style == "inherited-font":
        statements = (" doc.resolveSettingPath(None,'/StyleSheet/Font/size').set('3%')\n"
                      f" doc.resolveSettingPath(None,{target!r}).set(Reference('/StyleSheet/Font/size'))\n")
    else:
        statements = f" doc.resolveSettingPath(None,{target!r}).set('3%')\n"
    script.write_text("from pathlib import Path\nfrom sciplot_core.veusz_worker.document_edit import loaded_native_document\n"
        "from sciplot_core.studio_core.persistence import atomic_save_veusz_document, project_save_binding\n"
        f"path=Path({str(native)!r})\nbaseline=project_save_binding(Path({str(project)!r}),path)\n"
        "with loaded_native_document(path) as doc:\n"
        " doc._sciplot_project_read_set=baseline\n"
        " from veusz.setting import Reference\n" + statements + " atomic_save_veusz_document(doc,path)\n")
    modified = subprocess.run([sys.executable, str(script)], env=veusz_worker_environment(), capture_output=True, text=True, timeout=120)
    assert modified.returncode == 0, modified.stderr
    source = capture_source({"kind": "project", "project": str(project),
                             "figure_id": inspect_project(project)["primary_figure_id"]})
    before = {str(path): file_inventory(path) for path in (project, raw)}
    document = add(new_document(rows=1, columns=1, width_mm=90, height_mm=75), source, name="relative-plot")
    with pytest.raises(AssemblyError) as error:
        export_document(document, tmp_path / "must-not-publish")
    assert error.value.code == "assembly_relative_physical_style"
    assert "Panel a (relative-plot)" in str(error.value)
    assert "3%" in str(error.value) and target in str(error.value)
    assert "fixed physical size in pt" in str(error.value)
    assert "Use current source version" in str(error.value)
    assert "retry export" in str(error.value)
    issue = error.value.issues[0]
    assert issue["panel_id"] == "relative-plot" and issue["panel_label"] == "a"
    assert issue["setting_path"] == target and issue["value"] == "3%"
    assert json.loads(json.dumps(issue))["repair"] == issue["repair"]
    assert not (tmp_path / "must-not-publish").exists()
    assert {str(path): file_inventory(path) for path in (project, raw)} == before
