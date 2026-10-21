"""Generated zero-SD bars retain native outlines and exact source values."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.guide_contracts import categorical_line_contracts


@pytest.mark.parametrize("kind", ["bar_error", "grouped_bar_error"])
@pytest.mark.parametrize(
    "error,draw_error",
    [(0.0, False), (2.0, True), (float("nan"), False), (float("inf"), False)],
    ids=["zero", "positive", "nan", "infinite"],
)
def test_bar_outline_contract_is_independent_of_error_segment_eligibility(
    kind: str, error: float, draw_error: bool
) -> None:
    spec = {
        "categorical": {
            "presentation_kind": kind,
            "visual_style": {
                "bar_width_fraction": 0.4,
                "error_cap_to_bar_ratio": 0.5,
            },
            "groups": [{
                "position": 1.0, "bar_mean": 6.0, "bar_error": error,
                "color": "#123456", "keyline_color": "#102030",
            }],
        }
    }
    lines = categorical_line_contracts(spec)
    outlines = [f"categorical_bar_outline_1_{index}" for index in (1, 2, 3)]
    errors = (
        [f"categorical_bar_error_1_{index}" for index in (1, 2, 3)]
        if draw_error else []
    )
    assert [line["name"] for line in lines] == errors + outlines
    assert [
        (line["xPos"], line["yPos"], line["xPos2"], line["yPos2"])
        for line in lines[-3:]
    ] == [
        ([0.8], [0.0], [0.8], [6.0]),
        ([1.2], [0.0], [1.2], [6.0]),
        ([0.8], [6.0], [1.2], [6.0]),
    ]
    assert all(
        line["line_color"] == "#102030" and not line["hide"] and not line["line_hide"]
        for line in lines[-3:]
    )
    if draw_error:
        assert [
            (line["xPos"], line["yPos"], line["xPos2"], line["yPos2"])
            for line in lines[:3]
        ] == [
            ([1.0], [4.0], [1.0], [8.0]),
            ([0.9], [8.0], [1.1], [8.0]),
            ([0.9], [4.0], [1.1], [4.0]),
        ]


def _cli(evidence: Path, *args: str | Path) -> dict[str, Any]:
    argv = [str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"]
    receipt: dict[str, Any] = {
        "argv": argv,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "actual subprocess wait; no access-capture or reusable-pass claim",
    }
    with evidence.with_suffix(".stdout").open("w") as stdout, evidence.with_suffix(
        ".stderr"
    ).open("w") as stderr:
        with subprocess.Popen(argv, cwd=REPO_ROOT, stdout=stdout, stderr=stderr) as process:
            receipt["pid"] = process.pid
            evidence.with_suffix(".run.json").write_text(json.dumps(receipt, indent=2))
            try:
                receipt["exit_code"] = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                process.kill()
                receipt["exit_code"] = process.wait()
                raise
            finally:
                receipt["ended_at"] = datetime.now(timezone.utc).isoformat()
                evidence.with_suffix(".run.json").write_text(json.dumps(receipt, indent=2))
    output = evidence.with_suffix(".stdout").read_text()
    assert receipt["exit_code"] == 0, output + evidence.with_suffix(".stderr").read_text()
    result: dict[str, Any] = json.loads(output)
    return result


@pytest.mark.comprehensive
@pytest.mark.parametrize("mode", ["mean_sample_sd", "mean_sample_sd_n"])
def test_public_zero_sd_grouped_bar_preserves_replicates_and_passes_create_and_cold_export(
    tmp_path: Path, mode: str
) -> None:
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source = tmp_path / "zero_sd.csv"
    source.write_text(
        "Sample,Condition,Strength (MPa),Replicate\n"
        "A,dry,2,1\nA,dry,2,2\nA,wet,6,1\nA,wet,6,2\n"
        "B,dry,4,1\nB,dry,4,2\nB,wet,8,1\nB,wet,8,2\n"
    )
    original = file_sha256(source)
    binding = {
        "source_sha256": original, "mode": mode,
        "sample_column": 0, "condition_column": 1,
        "value_columns": [{"column_index": 2}],
        "category_order": ["A", "B"], "condition_order": ["dry", "wet"],
        "table_selection": {
            "sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 9,
        },
    }
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "version": 1, "action": "create", "source": str(source), "categorical": binding,
    }))
    created = _cli(
        tmp_path / "create", "task", "start", "--request", request,
        "--task-dir", tmp_path / "task",
    )
    assert created["status"] == "complete", created
    document = Path(created["current_project"]["figures"][0]["document"])
    spec_path = document.with_name("spec.json")
    spec = json.loads(spec_path.read_text())
    groups = spec["categorical"]["groups"]
    raw_values = [[2.0, 2.0], [6.0, 6.0], [4.0, 4.0], [8.0, 8.0]]
    assert [group["raw_values"] for group in groups] == raw_values
    assert [group["replicate_count"] for group in groups] == [2] * 4
    assert [group["bar_mean"] for group in groups] == [2.0, 6.0, 4.0, 8.0]
    assert [group["bar_error"] for group in groups] == [0.0] * 4
    contracts = categorical_line_contracts(spec)
    assert [line["name"] for line in contracts] == [
        f"categorical_bar_outline_{bar}_{segment}"
        for bar in range(1, 5) for segment in range(1, 4)
    ]
    geometry = ("xPos", "yPos", "xPos2", "yPos2", "hide")
    with loaded_native_document(document) as native:
        graph = native.resolveWidgetPath(None, "/page1/graph1")
        actual = [{
            "name": widget.name,
            **{key: native.resolveSettingPath(
                None, f"/page1/graph1/{widget.name}/{key}"
            ).get() for key in geometry},
        } for widget in graph.children if widget.typename == "line"]
        native_values = [native.data[series["y_name"]].data.tolist() for series in spec["series"]]
    assert actual == [{key: line[key] for key in ("name", *geometry)} for line in contracts]
    assert native_values == raw_values
    audit = run_document_worker("audit-spec-data", document, spec_path)
    assert audit["status"] == "passed"
    doc_hash, spec_hash = file_sha256(document), file_sha256(spec_path)
    (tmp_path / "native-evidence.json").write_text(json.dumps({
        "source_sha256": original, "native_lines": actual, "native_raw_values": native_values,
        "native_audit": audit, "document_sha256": doc_hash, "spec_sha256": spec_hash,
    }, indent=2))
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"version": 1, "action": "export", "project": created["project"]}))
    cold = _cli(
        tmp_path / "cold", "task", "start", "--request", export,
        "--task-dir", tmp_path / "cold-task",
    )
    assert cold["status"] == "complete", cold
    delivery = Path(cold["current_project"]["delivery"]["path"])
    summaries = list((delivery / "data").glob("*_replicate_summary.csv"))
    if mode == "mean_sample_sd_n":
        assert len(summaries) == 1
        with summaries[0].open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [float(row["sample_sd"]) for row in rows] == [0.0] * 4
        assert [int(row["valid_n"]) for row in rows] == [2] * 4
        assert [row["sample"] for row in rows] == ["A", "A", "B", "B"]
        assert [row["condition"] for row in rows] == ["dry", "wet", "dry", "wet"]
    else:
        assert summaries == []
    assert all(cold["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert file_sha256(document) == doc_hash and file_sha256(spec_path) == spec_hash
    assert file_sha256(source) == original
