"""Retained native export evidence and conflict recovery for generated categories."""

from pathlib import Path
import csv
import hashlib
import json
import shutil
import subprocess
import sys

from test_task_ordinary_categorical_native import _cli
from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.categorical_display import KEY
from sciplot_core.studio_core.document_edit_state import history_directory


def given_value_series_ids(source, binding, spec, targets):
    """Bind this fixture's retained widgets to original columns and conditions."""
    assert binding["sample_column"] == 0 and binding["condition_column"] == 1
    assert binding["value_columns"] == [{"column_index": 2}]
    assert binding["table_selection"] == {
        "sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 5
    }
    cells = list(csv.reader(source.read_text().splitlines()))
    namespace = str(source.resolve())
    assert spec["source_request"]["categorical_binding"] == {
        **binding, "source_identity_version": 1, "source_namespace": namespace
    }
    assert spec["source_category_ids"] == ["P", "Q"]
    series = {item["name"]: item for item in spec["series"]}
    advertised = {item["series_id"]: item for item in targets}
    expected = {}
    for condition in ("dry", "wet"):
        selector = {
            "source_namespace": namespace, "sheet": None,
            "data_start_row": 1, "data_end_row": 5, "columns": [0, 1, 2],
            "selector": {"condition": condition},
        }
        series_id = "group_" + hashlib.sha256(json.dumps(
            selector, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()[:32]
        item = series[series_id]
        assert item["source_binding"] == {
            "version": 2, "source_id": series_id, "source_namespace": namespace,
            "categories": ["P", "Q"], "condition": condition, "value_column": 2,
        }
        assert item["source_artifacts"] == [{"path": namespace, "sha256": binding["source_sha256"]}]
        assert advertised[series_id]["source_selector"] == {
            "source_label": condition, "condition_label": condition, "value_column_index": 2
        }
        values = []
        for sample in ("P", "Q"):
            rows = [row for row in cells[1:5] if row[:2] == [sample, condition]]
            assert len(rows) == 1
            values.append(float(rows[0][2]))
        assert [float(value).hex() for value in item["x_values"]] == [float(value).hex() for value in (1, 2)]
        assert [float(value).hex() for value in item["y_values"]] == [value.hex() for value in values]
        expected[condition] = series_id
    assert set(series) == set(advertised) == set(expected.values())
    return expected


def _exports(project, delivery):
    return {
        path: path.read_bytes()
        for root in (delivery.parent, Path(project) / "studio/exports")
        for path in root.rglob("*")
        if path.is_file()
    }


def verify_exports_and_conflicts(
    tmp_path,
    *,
    project,
    document,
    spec_path,
    source,
    original,
    plot_request,
    second_review,
    mode,
    created,
    saved,
    cold,
    given_series_ids,
):
    import fitz

    delivery = tmp_path / "readings_SciPlot/figures"
    with fitz.open(delivery / "document.pdf") as pdf:
        text = pdf[0].get_text()
        assert "Control" in text and "Treated" in text and "Initial" not in text
    retained = REPO_ROOT / ".tmp_verify/categorical-display" / mode
    retained.mkdir(parents=True, exist_ok=True)
    for path, name in [
        (document, "document.vsz"),
        (spec_path, "spec.json"),
        (source, "readings.csv"),
        (Path(project) / "plot_request.json", "plot_request.json"),
    ]:
        shutil.copyfile(path, retained / name)
    (retained / "signed-review.json").write_text(json.dumps(second_review, indent=2))
    (retained / "cold.json").write_text(json.dumps(cold, indent=2))
    (retained / "matched-hashes.json").write_text(
        json.dumps(
            {
                "native_sha256": file_sha256(document),
                "spec_sha256": file_sha256(spec_path),
                "source_sha256": file_sha256(source),
                "review_native_sha256": second_review["candidate"]["sha256"],
                "review_spec_sha256": second_review["candidate_spec"]["sha256"],
            },
            indent=2,
        )
    )
    for path in delivery.iterdir():
        if path.suffix.lower() in {".tif", ".tiff", ".pdf"}:
            shutil.copyfile(path, retained / path.name)
    native_bytes = document.read_bytes()
    applied_history = sorted(
        history_directory(Path(project), second_review["operation_id"]).parent.glob(
            "*/outcome.json"
        )
    )
    preserved_exports = _exports(project, delivery)
    native_path = (
        f"/page1/graph1/{given_series_ids['dry']}/MarkerFill/color"
        if mode == "given_values"
        else "/page1/graph1/categorical_bar_fill_1/Fill/color"
    )
    native_save = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path
from sciplot_core.veusz_worker.document_edit import loaded_native_document
with loaded_native_document(Path(sys.argv[1])) as document:
    from veusz.document import CommandInterface
    from veusz.document.operations import OperationSettingSet
    document.applyOperation(OperationSettingSet(sys.argv[2], '#109876'))
    CommandInterface(document).Save(sys.argv[1])
""",
            str(document),
            native_path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert native_save.returncode == 0, native_save.stderr
    export_request = tmp_path / "tamper-export.json"
    export_request.write_text(
        json.dumps({"version": 1, "action": "export", "project": project})
    )
    blocked = _cli(
        "task",
        "start",
        "--request",
        export_request,
        "--task-dir",
        tmp_path / "external",
        success=False,
    )
    assert blocked["status"] == "blocked", blocked
    assert blocked["blocker"]["reason_code"] == "categorical_presentation_conflict", (
        blocked
    )
    assert (
        json.loads((tmp_path / "external/task.json").read_text())["status"] == "blocked"
    )
    assert _exports(project, delivery) == preserved_exports
    document.write_bytes(native_bytes)
    retry = tmp_path / "retry.json"
    retry.write_text(json.dumps({"retry": True}))
    assert (
        _cli("task", "resume", tmp_path / "external", "--response", retry)["status"]
        == "complete"
    )
    preserved_exports = _exports(project, delivery)
    source.write_bytes(original + b"\n")
    changed = _cli(
        "task",
        "start",
        "--request",
        export_request,
        "--task-dir",
        tmp_path / "changed",
        success=False,
    )
    assert changed["status"] == "blocked", changed
    assert _exports(project, delivery) == preserved_exports
    source.write_bytes(original)
    assert (
        _cli("task", "resume", tmp_path / "changed", "--response", retry)["status"]
        == "complete"
    )
    assert document.read_bytes() == native_bytes
    assert (Path(project) / "plot_request.json").read_bytes() == plot_request
    assert (
        sorted(
            history_directory(Path(project), second_review["operation_id"]).parent.glob(
                "*/outcome.json"
            )
        )
        == applied_history
    )
    (retained / "report.json").write_text(
        json.dumps(
            {
                "created": created,
                "saved": saved,
                "cold": cold,
                "external_native_save_rejected": blocked,
                "raw_drift_rejected": changed,
                "source_sha256": file_sha256(source),
                "overlay": json.loads(spec_path.read_text())[KEY],
            },
            indent=2,
        )
    )
