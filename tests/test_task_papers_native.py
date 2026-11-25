from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_control import start_task
from sciplot_core.task_papers import paper_capabilities, start_paper, resume_paper
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.veusz_runtime import veusz_worker_environment


def _public(*args):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "task", "paper", *map(str, args), "--json"],
                            capture_output=True, text=True, timeout=240,
                            env={**os.environ, "SCIPLOT_PYTHON": sys.executable, "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", ""))))})
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _projects(tmp_path):
    sources = []
    projects = []
    for name, text in (
        ("UVvis", "Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n"),
        ("FTIR", "Wavenumber,Absorbance\ncm-1,a.u.\nF3,F3\n1000,2\n1250,3\n1500,2\n"),
    ):
        source = tmp_path / f"{name}.csv"
        source.write_text(text)
        sources.append(source)
        # These paper v1 controls require saved native authority.
        display = "raw_overlay" if name == "UVvis" else "stacked_offset"
        created = start_task({"version": 1, "action": "create", "source": str(source), "curve_display": display},
                             task_dir=tmp_path / f"create-{name}", defer_creation_export=False)
        assert created["status"] == "complete", created
        projects.append(Path(created["project"]))
    return sources, projects


def _request(tmp_path, projects):
    return {"version": 1, "title": "Two exact final figures", "out": str(tmp_path / "selected-paper"),
            "items": [{**paper_capabilities(project=project, figure_id=inspect_project(project)["primary_figure_id"])["selection"], "label": label}
                      for project, label in zip(projects, ("Fig2", "Fig1"), strict=True)]}


@pytest.mark.comprehensive
def test_public_paper_cli_packages_two_native_figures_and_relocated_editable_export(tmp_path):
    sources, projects = _projects(tmp_path)
    # Native manual presentation state is current authority, even without project re-export.
    selected = projects[0] / "studio/document.vsz"
    native_script = tmp_path / "manual-save.py"
    native = run_document_worker("inspect-document-state", selected)
    curve = next(path for path, widget in native["widgets"].items() if widget["type"] == "xy")
    linked = tmp_path / "native-linked.txt"
    spec = json.loads((projects[0] / "studio/spec.json").read_text())
    series = spec["series"][0]
    linked.write_text("".join(f"{x:.17g} {y:.17g}\n" for x, y in zip(series["x_values"], series["y_values"], strict=True)))
    native_script.write_text("from pathlib import Path\nfrom sciplot_core.veusz_worker.document_edit import loaded_native_document\n"
        "from sciplot_core.studio_core.persistence import atomic_save_veusz_document, project_save_binding\n"
        "from sciplot_core.project_host_factory import project_store\n"
        f"path=Path({str(selected)!r})\nproject=Path({str(projects[0])!r})\nstore=project_store(project)\nbaseline=project_save_binding(project,path,store=store)\n"
        "with loaded_native_document(path) as doc:\n"
        " doc._sciplot_project_read_set=baseline\n"
        " doc._sciplot_project_store=store\n"
        " from veusz.document import CommandInterface\n"
        f" doc.resolveSettingPath(None,{(curve + '/PlotLine/color')!r}).set('#A34455')\n"
        f" CommandInterface(doc).ImportFile({str(linked)!r},{(series['x_name'] + '(numeric), ' + series['y_name'] + '(numeric)')!r},linked=True)\n"
        " atomic_save_veusz_document(doc,path)\n")
    saved = subprocess.run([sys.executable, str(native_script)], env=veusz_worker_environment(), capture_output=True, text=True, timeout=120)
    assert saved.returncode == 0, saved.stdout + saved.stderr
    # The changed original must be explicitly published by its existing export
    # owner before the paper can consume those sealed bytes; paper never exports.
    published = start_task({"version": 1, "action": "export", "project": str(projects[0])}, task_dir=tmp_path / "publish-manual-save")
    assert published["status"] == "complete", published
    before = {p: file_inventory(p) for p in [*sources, *projects, linked]}
    request = _request(tmp_path, projects)
    for item in request["items"]:
        item.pop("source_files")
        item.pop("document_authority")
    path = tmp_path / "paper.json"
    path.write_text(json.dumps(request))
    result = _public("start", "--request", path, "--paper-dir", tmp_path / "paper-task")
    assert result["status"] == "complete", result
    out = Path(request["out"])
    assert sorted(p.name for p in (out / "figures").glob("*.pdf")) == ["001_Fig2.pdf", "002_Fig1.pdf"]
    assert sorted(p.name for p in (out / "project").glob("*.vsz")) == ["001_Fig2.vsz", "002_Fig1.vsz"]
    manifest = json.loads((out / "data/figure_sources.json").read_text())
    assert [i["label"] for i in manifest["items"]] == ["Fig2", "Fig1"]
    assert all(i["portable_native"]["native_state_sha256"] == i["portable_native"]["reopened_native_state_sha256"] for i in manifest["items"])
    assert result["result"]["verification"]["passed"] is True
    assert manifest["items"][0]["portable_native"]["imports"]
    assert str(linked) in manifest["items"][0]["source_files"]
    copy = tmp_path / "relocated"
    shutil.copytree(out, copy)
    held = linked.with_suffix(".hidden")
    linked.rename(held)
    try:
        for item in manifest["items"]:
            editable = copy / item["editable"]
            audit = run_document_worker("audit-spec-data", editable, editable.with_suffix(".spec.json"), "--allow-presentation-edits")
            from sciplot_core.foundation.json_hashing import canonical_json_sha256

            assert canonical_json_sha256(audit["units"], allow_nan=False) == item["scientific_sha256"]
            exported = run_document_worker("export-document", editable, "--out", copy / "reexports" / item["stem"])
            assert len(exported["exports"]) == 2
            assert all(Path(export["path"]).is_file() for export in exported["exports"])
    finally:
        held.rename(linked)
    copied_state = run_document_worker("inspect-document-state", copy / "project/001_Fig2.vsz")
    assert copied_state["widgets"][curve]["settings"]["PlotLine/color"] == "#A34455"
    assert all(file_inventory(p) == before[p] for p in before)
    assert _public("resume", tmp_path / "paper-task")["status"] == "complete"
    assert _public("inspect", tmp_path / "paper-task")["delivery_current"] is True


@pytest.mark.comprehensive
def test_native_second_capture_failure_and_exact_retry_only_captures_unsealed_figure(tmp_path, monkeypatch):
    sources, projects = _projects(tmp_path)
    before = {p: file_inventory(p) for p in [*sources, *projects]}
    request = _request(tmp_path, projects)
    for item in request["items"]:
        item.pop("source_files")
        item.pop("document_authority")
    from sciplot_core.delivery import native_snapshot

    portable = native_snapshot.capture_native
    calls = []

    def failure(source, target, imports, *, original_sha256, selected_imports):
        calls.append(target.name)
        if target.name == "002_Fig1.vsz":
            raise RuntimeError("injected native capture failure after first sealed item")
        return portable(source, target, imports, original_sha256=original_sha256, selected_imports=selected_imports)

    monkeypatch.setattr(native_snapshot, "capture_native", failure)
    first = start_paper(request, paper_dir=tmp_path / "paper-task")
    assert first["status"] == "blocked", first
    assert [i["status"] for i in first["items"]] == ["sealed", "exporting"]
    assert not Path(request["out"]).exists()

    def restored(source, target, imports, *, original_sha256, selected_imports):
        calls.append(target.name)
        return portable(source, target, imports, original_sha256=original_sha256, selected_imports=selected_imports)

    monkeypatch.setattr(native_snapshot, "capture_native", restored)
    from sciplot_core.delivery import install

    atomic_install = install.install_new_delivery

    def lost_reply(candidate, destination):
        atomic_install(candidate, destination)
        raise RuntimeError("injected lost reply after exclusive atomic publication")

    monkeypatch.setattr(install, "install_new_delivery", lost_reply)
    published_without_reply = resume_paper(tmp_path / "paper-task")
    assert published_without_reply["status"] == "blocked"
    assert Path(request["out"]).is_dir()
    monkeypatch.setattr(install, "install_new_delivery", atomic_install)
    final = resume_paper(tmp_path / "paper-task")
    assert final["status"] == "complete", final
    assert calls == ["001_Fig2.vsz", "002_Fig1.vsz", "002_Fig1.vsz"]
    assert all(file_inventory(p) == before[p] for p in before)
    assert all(file_sha256(Path(i["path"])) == i["delivery_sha256"] for i in final["result"]["figures"])


@pytest.mark.comprehensive
def test_public_completed_group_freezes_once_and_reuses_current_native_publications(tmp_path, capsys, monkeypatch):
    from sciplot_core import task_papers as owner, task_paper_sources as sources_owner
    from sciplot_core.cli import main
    from sciplot_core.studio_core.project_session import ProjectSessionBusy, external_project_session
    from sciplot_core.task_group_storage import save_group

    sources, projects = _projects(tmp_path)
    root = tmp_path / 'finished-group'
    root.mkdir()
    entries = []
    for source, name in zip(sources, ('UVvis', 'FTIR'), strict=True):
        request = {'version': 1, 'action': 'create', 'source': str(source),
                   'curve_display': 'raw_overlay' if name == 'UVvis' else 'stacked_offset'}
        entries.append({'id': name, 'label': {'UVvis': 'P0.3/0.7 log', 'FTIR': 'P0.5/0.5 linear'}[name], 'request': request})
    group = {'kind': 'sciplot_task_group', 'version': 1, 'group_dir': str(root),
             'request': {'version': 1, 'title': 'Two current original publications', 'items': entries},
             'items': [{'id': entry['id'], 'label': entry['label'], 'status': 'complete', 'finished': True,
                        'steps': [{'name': 'initial', 'request': entry['request'],
                                   'task_dir': str(tmp_path / ('create-' + entry['id']))}]} for entry in entries]}
    save_group(root, group)
    originals = {path: file_inventory(path) for path in [*sources, *projects, root]}
    captures = []
    native_links = sources_owner.native_link_sources

    def inspect_links(document):
        with pytest.raises(ProjectSessionBusy):
            with external_project_session(checkpoint):
                pytest.fail("Native inventory must run under the paper owner lease.")
        captures.append(document)
        return native_links(document)

    def cli(*args, expected=0):
        code = main(["task", "paper", *map(str, args), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == expected, payload
        return payload

    monkeypatch.setattr(sources_owner, "native_link_sources", inspect_links)
    documents = [project / "studio/document.vsz" for project in projects]
    checkpoint = tmp_path / "forward-paper"
    forward = cli('start', '--group', root, '--out', tmp_path / 'forward-publication', '--paper-dir', checkpoint)
    assert captures == documents
    assert forward['ready_to_use'] is True and forward['readiness_evaluated'] is True
    assert forward['source_versions_current'] is True and forward['delivery_current'] is True
    assert 'no fresh native audit' in forward['readiness_scope']
    assert [item['stem'] for item in forward['items']] == ['001_P0_3_0_7_log', '002_P0_5_0_5_linear']
    out, paper = tmp_path / 'group-publication', tmp_path / 'group-paper'
    checkpoint = paper
    captures.clear()
    result = cli('start', '--group', root, '--out', out, '--paper-dir', paper, '--item-id', 'FTIR', '--item-id', 'UVvis')
    assert captures == list(reversed(documents))
    assert result['status'] == 'complete' and result['ready_to_use'] is True, result
    assert [Path(item['project']) for item in result['items']] == list(reversed(projects))
    assert [item['stem'] for item in result['items']] == ['001_P0_5_0_5_linear', '002_P0_3_0_7_log']
    assert sorted(path.name for path in (out / 'figures').glob('*.pdf')) == ['001_P0_5_0_5_linear.pdf', '002_P0_3_0_7_log.pdf']
    manifest = json.loads((out / 'data/figure_sources.json').read_text())
    assert [item['label'] for item in manifest['items']] == ['P0_5_0_5_linear', 'P0_3_0_7_log']
    state = json.loads((paper / 'paper.json').read_text())
    assert state['selection_origin']['group_state_sha256'] == group['state_sha256']
    for source, item, requested in zip(state['selections'], state['items'], state['request']['items'], strict=True):
        assert requested["expected_version"] == source["version"]
        assert set(source["version"]) == {"request_sha256", "document_sha256", "spec_sha256", "source_sha256"}
        assert item['exports']['mode'] == 'copied_current_sealed_publication'
        for exported in item['exports']['exports']:
            original = next(record for record in source['publication']['exports'] if record['format'] == exported['format'])
            assert file_sha256(Path(exported['path'])) == original['sha256']
    assert all(file_inventory(path) == before for path, before in originals.items())
    frozen = (paper / 'paper.json').read_bytes()
    # A changed group cannot select a new revision during same-checkpoint replay.
    group['request']['title'] = 'New later group title'
    save_group(root, group)
    captures.clear()
    repeated = cli('start', '--group', root, '--out', out, '--paper-dir', paper, '--item-id', 'FTIR', '--item-id', 'UVvis')
    assert cli("inspect", paper)["ready_to_use"] is True
    assert cli("resume", paper)["ready_to_use"] is True
    assert not captures
    assert repeated['ready_to_use'] is True and repeated['title'] == result['title']
    assert (paper / 'paper.json').read_bytes() == frozen

    # Modify a selected source after its publication receipt has been captured
    # but before the owner can write the frozen paper checkpoint or any outputs.
    capture_publication = owner.capture_publication
    uv_selection = state["selections"][-1]
    captured_source = Path(next(iter(uv_selection["source_files"])))
    for index, changed in enumerate((captured_source, Path(uv_selection["document"]), Path(uv_selection["spec"]))):
        original = changed.read_bytes()
        original_stat = changed.stat()

        def mutate_after_capture(selection, path=changed, content=original):
            publication = capture_publication(selection)
            path.write_bytes(content + b" ")
            return publication

        checkpoint = tmp_path / f"drift-paper-{index}"
        drift_out = tmp_path / f"drift-out-{index}"
        captures.clear()
        with monkeypatch.context() as patch:
            patch.setattr(owner, "capture_publication", mutate_after_capture)
            try:
                blocked = cli("start", "--group", root, "--out", drift_out, "--paper-dir", checkpoint,
                              "--item-id", "UVvis", expected=1)
            finally:
                changed.write_bytes(original)
                os.utime(changed, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        assert blocked["reason_code"] == "paper_selection_changed"
        assert captures == documents[:1]
        assert not checkpoint.exists() and not drift_out.exists()


def _never_rebuild(*_args, **_kwargs):
    pytest.fail("Paper capture/retry must not compile or export original plots.")


def _cold_managed_paper(args, *, resume=False):
    script = """import sys
from sciplot_core.cli import main
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_protocol.server import make_service
from sciplot_core.task_semantic_owner import local_managed_actions

def forbidden(*args, **kwargs):
    raise AssertionError("Cold paper retry cannot compile or export original plots.")

ManagedVeuszCompiler.compile_ir = ManagedVeuszCompiler.export_ir = forbidden
service = make_service()
try:
    with local_managed_actions(forbidden, service.describe, service.deliver):
        code = main(sys.argv[1:])
finally:
    service.close()
sys.exit(code)
"""
    command = ["-c", script] if resume else ["-m", "sciplot_core.cli"]
    return subprocess.run([sys.executable, *command, *args, "--json"], env=veusz_worker_environment(),
                          capture_output=True, text=True, timeout=160, check=False)


def _check_native_pair(out, selected, uv_head):
    import pymupdf
    from PIL import Image

    items = json.loads((out / "index.json").read_bytes())["items"]
    assert [item["order"] for item in items] == [1, 2]
    assert [item["local_managed_continuation"] for item in items] == selected
    assert items[0]["scientific_hash"] == uv_head["document"]["scientific_hash"]
    assert items[0]["presentation_hash"] == uv_head["document"]["presentation_hash"]
    for item in items:
        ir_path = out / item["plotted_data"]["ir"]["path"]
        ir = json.loads(ir_path.read_bytes())
        width, height = ir["layout"]["width_mm"], ir["layout"]["height_mm"]
        with pymupdf.open(out / item["files"]["pdf"]) as pdf:
            assert len(pdf) == 1
            assert tuple(pdf[0].rect)[2:] == pytest.approx((width * 72 / 25.4, height * 72 / 25.4), abs=1)
        with Image.open(out / item["files"]["tiff_300"]) as image:
            assert image.info["dpi"] == pytest.approx((300, 300), abs=.1)
            assert image.size == pytest.approx((width * 300 / 25.4, height * 300 / 25.4), abs=2)
        process = subprocess.run([sys.executable, "-m", "sciplot_core.veusz_worker", "inspect-plot-ir",
                                  str(ir_path), str(out / item["files"]["editable"])],
                                 env=veusz_worker_environment(), capture_output=True, text=True, timeout=90, check=False)
        assert process.returncode == 0, process.stdout + process.stderr
        evidence = json.loads(process.stdout)
        assert evidence["status"] == "unchanged" and evidence["scientific_audit"]["status"] == "passed"
    uv_ir = json.loads((out / items[0]["plotted_data"]["ir"]["path"]).read_bytes())
    from sciplot_core.plot_backends.figure_marks import coordinates

    layer, = uv_ir["views"][0]["layers"]
    assert coordinates(uv_ir, layer)["x"] == [460.0, 400.0, 500.0]
    assert coordinates(uv_ir, layer)["y"] == [5.0, 2.0, 1.0]
    assert [scale["unit"] for scale in uv_ir["scales"]] == ["nm", "a.u."]
    assert layer["marks"][0]["style"]["line_color"] == "#2277aa"


@pytest.mark.comprehensive
def test_public_paper_group_and_explicit_secondary_use_current_saved_figures(tmp_path, capsys, monkeypatch):
    from sciplot_core.cli import main
    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
    from sciplot_core.plot_engine.storage import load_head
    from sciplot_core.plot_protocol.server import make_service
    from sciplot_core.project_lifecycle.managed_figure_observation import observe_frequency_figures
    from sciplot_core.task_semantic_owner import local_managed_actions
    from managed_plot_helpers import read_managed_head_and_ir
    from test_rheology_mean_suite_publication import _mean_input

    frequency_raw, _ = _mean_input(tmp_path)
    uv = tmp_path / "UVvis.csv"
    raw_bytes = b"Wavelength,Absorbance\nnm,a.u.\nA,A\n460,5\n400,2\n500,1\n"
    uv.write_bytes(raw_bytes)
    group_dir, group_request = tmp_path / "group", tmp_path / "group-request.json"
    uv_out, frequency_out = tmp_path / "uv", tmp_path / "frequency"
    group_request.write_text(json.dumps({"version": 1, "title": "Manuscript", "items": [
        {"id": "UV", "label": "UV-vis", "request": {
            "version": 1, "action": "create", "source": str(uv), "out": str(uv_out)}},
        {"id": "frequency", "label": "Frequency", "request": {
            "version": 1, "action": "create", "source": str(frequency_raw), "out": str(frequency_out),
            "rule_id": "rheology_frequency_sweep"}},
    ]}))

    def cli(args, expected=0):
        code = main([*args, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == expected, payload
        return payload

    service = make_service()
    try:
        with local_managed_actions(service.create, service.describe, service.deliver):
            group = cli(["task", "group", "start", "--request", str(group_request), "--group-dir", str(group_dir)])
        uv_item, freq_item = group["items"]
        assert group["status"] == "complete", group
        uv_handle, = uv_item["plot_objects"]
        uv_plot = Path(uv_handle["plot"])
        original, ir = read_managed_head_and_ir(uv_plot)
        mark = ir["views"][0]["layers"][0]["marks"][0]["id"]
        edited = service.patch(uv_plot, {"plot_id": uv_handle["plot_id"], "base_revision": 0,
            "idempotency_key": "paper-uv-revised", "intent_class": "presentation",
            "changes": [{"op": "set", "target": [mark], "property": "style", "value": {"line_color": "#2277aa"}}]})
        assert edited["revision"] == 1 and edited["ready_to_use"], edited
        revised = load_head(uv_plot)
        assert revised["document"]["scientific_hash"] == original["document"]["scientific_hash"]
        assert revised["document"]["presentation_hash"] != original["document"]["presentation_hash"]
        frozen_uv_output = file_inventory(uv_out)

        registered = observe_frequency_figures(Path(freq_item["project"])).figures
        assert [entry["plot"] for entry in registered] == [entry["plot"] for entry in freq_item["figures"]]
        primary, secondary, *_ = registered
        assert primary["figure_id"] == "storage_modulus_vs_frequency"
        assert secondary["figure_id"] == "loss_modulus_vs_frequency"
        # Break only the primary member's saved PDF. The exact secondary is
        # cold, with only its generation-owned archived export-cache.
        primary_pdf, = (Path(freq_item["project"]) / "figures" / primary["figure_id"]).glob("*.pdf")
        original_pdf = primary_pdf.read_bytes()
        primary_pdf.unlink()
        selection = [{"plot": uv_handle["plot"], "plot_id": uv_handle["plot_id"], "revision": 1},
                     {"plot": secondary["plot"], "plot_id": secondary["plot_id"], "revision": 0}]
        explicit_out, request_file = tmp_path / "exact-two", tmp_path / "delivery-request.json"
        request_file.write_text(json.dumps({"idempotency_key": "ordered-secondary", "mode": "native_snapshot",
            "out": str(explicit_out), "title": "Exact paper pair",
            "items": [{**item, "label": label} for item, label in zip(selection, ("UV revision", "Secondary"), strict=True)]}))

        monkeypatch.setattr(ManagedVeuszCompiler, "compile_ir", _never_rebuild)
        monkeypatch.setattr(ManagedVeuszCompiler, "export_ir", _never_rebuild)
        # Actual closed CLI selection, with the existing direct transport.
        explicit = cli(["plot", "deliver", "--request", str(request_file), "--direct"])
        assert explicit["status"] == "complete"
        _check_native_pair(explicit_out, selection, revised)

        paper_dir, paper_out = tmp_path / "paper", tmp_path / "paper-out"
        start = ["task", "paper", "start", "--group", str(group_dir), "--item-id", "frequency", "--item-id", "UV",
                 "--out", str(paper_out), "--paper-dir", str(paper_dir)]
        with local_managed_actions(_never_rebuild, service.describe, service.deliver):
            partial = cli(start, expected=1)
        assert partial["status"] == "partial" and partial["ready_to_use"] is False and not paper_out.exists(), partial
        expected_plots = [entry["plot"] for entry in registered] + [str(uv_plot)]
        assert [item["plot"] for item in partial["items"]] == expected_plots
        assert [item["revision"] for item in partial["items"]] == [0, 0, 0, 0, 1]
        failed, = [item for item in partial["items"] if item.get("error")]
        assert failed["plot"] == primary["plot"]
        assert failed["error"]["export_command"] == ["sciplot", "plot", "export", primary["plot"], "--json"]
        owner = Path(partial["checkpoint"])
        before = {path: file_inventory(path) for path in (paper_dir, owner, group_dir, Path(freq_item["project"]), uv_plot)}
        check = _cold_managed_paper(["task", "paper", "inspect", str(paper_dir)])
        assert check.returncode == 1, check.stdout + check.stderr
        assert json.loads(check.stdout)["status"] == "partial"
        assert before == {path: file_inventory(path) for path in before}
        primary_pdf.write_bytes(original_pdf)
        frozen = (paper_dir / "paper.json").read_bytes()
        assert json.loads(frozen)["request"] == partial["delivery_request"]
        sealed_attempts = [item["attempt"] for item in json.loads((owner / "delivery.json").read_bytes())["items"][1:]]

        def lose_reply(request):
            assert request == partial["delivery_request"]
            assert service.deliver(request)["status"] == "complete"
            raise RuntimeError("Simulated missing reply after the existing publisher installed its package")

        with local_managed_actions(_never_rebuild, service.describe, lose_reply):
            lost = cli(["task", "paper", "resume", str(paper_dir)], expected=1)
            assert "missing reply" in lost["message"]
        paper_inventory = file_inventory(paper_out)
        assert (paper_dir / "paper.json").read_bytes() == frozen
        assert [item["attempt"] for item in json.loads((owner / "delivery.json").read_bytes())["items"][1:]] == sealed_attempts

        # Start replay and inspect must not use delivery, even with no local
        # actions bound. A cold resume uses the exact same frozen request.
        assert cli(start)["recorded_status"] == "complete"
        proc = _cold_managed_paper(["task", "paper", "resume", str(paper_dir)], resume=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        completed = json.loads(proc.stdout)
        assert completed["delivery_request"] == partial["delivery_request"] and completed["ready_to_use"]
        index = json.loads((paper_out / "index.json").read_bytes())
        assert [item["local_managed_continuation"]["plot"] for item in index["items"]] == expected_plots
        assert index["items"][-1]["local_managed_continuation"] == selection[0]
        assert file_inventory(paper_out) == paper_inventory and file_inventory(uv_out) == frozen_uv_output

        # Currentness is a read, not a promise to restore edited native files.
        native = Path(revised["binding"]["document"])
        native_bytes = native.read_bytes()
        changed_native = native_bytes + b"\n# local native edit\n"
        native.write_bytes(changed_native)
        result = cli(["task", "paper", "inspect", str(paper_dir)], expected=1)
        assert result["status"] == "blocked" and result["recorded_status"] == "complete"
        assert result["items"][-1]["error"]["selection"]["plot"] == str(uv_plot)
        assert native.read_bytes() == changed_native
        native.write_bytes(native_bytes)
        uv.write_bytes(raw_bytes + b"480,8\n")
        result = cli(["task", "paper", "inspect", str(paper_dir)], expected=1)
        assert result["status"] == "blocked" and result["ready_to_use"] is False
        assert file_inventory(paper_out) == paper_inventory and (paper_dir / "paper.json").read_bytes() == frozen
    finally:
        service.close()
