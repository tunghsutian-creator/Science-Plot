"""Generated public late category edits retain native science across processes."""

from copy import deepcopy
from categorical_display_native_helpers import (
    given_value_series_ids,
    verify_exports_and_conflicts,
)
import json
from pathlib import Path

import numpy as np
import pytest

from test_task_ordinary_categorical_native import (
    _binding,
    _cli,
    _document,
    _request,
    _cold_export,
)
from sciplot_core.studio_core import document_edit_commit as commit
from sciplot_core.studio_core.categorical_display import KEY
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.document_edit_state import (
    audit_edited_document,
    history_directory,
)
from sciplot_core.veusz_worker.document_edit import loaded_native_document


def _context(project):
    return _cli(
        "task",
        "edit-context",
        project,
        "--operation",
        "set_category_display_labels",
        "--operation",
        "set_categorical_display_style",
    )


def _start(tmp_path, context, operations, name):
    request = tmp_path / (name + ".json")
    request.write_text(
        json.dumps(
            {**context["request_template"], "operations": operations, "export": False}
        )
    )
    return request, _cli(
        "task", "start", "--request", request, "--task-dir", tmp_path / name
    )


def _accept(tmp_path, review):
    response = tmp_path / (Path(review["task_dir"]).name + "-response.json")
    response.write_text(json.dumps(review["next_step"]["response_template"]))
    saved = _cli("task", "resume", review["task_dir"], "--response", response)
    assert saved["status"] == "complete", saved
    assert _cli("task", "resume", review["task_dir"], "--response", response) == saved
    return saved


def _datasets(document):
    with loaded_native_document(document) as loaded:
        return {
            name: np.asarray(value.data).copy()
            for name, value in loaded.data.items()
            if name != "category_axis_display_labels"
        }


@pytest.mark.comprehensive
@pytest.mark.parametrize("mode", ["given_values", "mean_sample_sd_n"])
def test_public_late_categorical_display_preview_recovery_cold_export_and_source_audit(
    tmp_path, monkeypatch, mode
):
    source = tmp_path / "readings.csv"
    source.write_text(
        "Sample,Condition,Strength (MPa)\nQ,dry,1.3\nP,wet,3.2\nQ,wet,2.1\nP,dry,1.8\n"
        + (
            "Q,dry,1.7\nP,wet,3.6\nQ,wet,2.5\nP,dry,2.2\nQ,dry,1.5\n"
            if mode != "given_values"
            else ""
        )
    )
    original = source.read_bytes()
    binding = _binding(
        source,
        mode,
        category_order=["P", "Q"],
        condition_order=["dry", "wet"],
        category_aliases={"P": "Initial"},
    )
    created = _cli(
        "task",
        "start",
        "--request",
        _request(tmp_path, source, binding),
        "--task-dir",
        tmp_path / "create",
    )
    assert created["status"] == "complete", created
    project = created["project"]
    document, spec_path, baseline = _document(created)
    if mode != "given_values":
        assert [
            group["replicate_count"] for group in baseline["categorical"]["groups"]
        ] == [2, 2, 3, 2]
    plot_request = (Path(project) / "plot_request.json").read_bytes()
    before_datasets, before_document, before_spec = (
        _datasets(document),
        document.read_bytes(),
        spec_path.read_bytes(),
    )
    context = _context(project)
    targets = context["categorical_display"]
    given_series_ids = (
        given_value_series_ids(source, binding, baseline, targets["style_targets"])
        if mode == "given_values" else None
    )
    assert targets["categories"] == [
        {"category_id": "P", "label": "Initial"},
        {"category_id": "Q", "label": "Q"},
    ]
    assert context["capabilities"]["operation_names"] == [
        "set_category_display_labels",
        "set_categorical_display_style",
    ]
    first_target = targets["style_targets"][0]
    invalid_operations = [
        {
            "op": "set_category_display_labels",
            "changes": [
                {"category_id": "ghost", "expected_label": "Q", "label": "Extra"}
            ],
        },
        {
            "op": "set_category_display_labels",
            "changes": [
                {"category_id": "P", "expected_label": "stale", "label": "Extra"}
            ],
        },
        {
            "op": "set_categorical_display_style",
            "changes": [
                {
                    "series_id": first_target["series_id"],
                    "expected_style": {
                        **first_target["current_style"],
                        "color": "#010203",
                    },
                    "style": {"color": "#112233"},
                }
            ],
        },
    ]
    if mode != "given_values":
        invalid_operations.append(
            {
                "op": "set_categorical_display_style",
                "changes": [
                    {
                        "series_id": first_target["series_id"],
                        "expected_style": first_target["current_style"],
                        "style": {"marker": "square"},
                    }
                ],
            }
        )
    else:
        invalid_operations.append(
            {
                "op": "set_categorical_display_style",
                "legend": {
                    "position": "upper_right",
                    "columns": 2,
                    "expected": {
                        **targets["legend"]["current"],
                        "columns": targets["legend"]["current"]["columns"] + 1,
                    },
                },
            }
        )
    for index, invalid in enumerate(invalid_operations):
        invalid_path = tmp_path / f"invalid-{index}.json"
        invalid_path.write_text(
            json.dumps(
                {
                    **context["request_template"],
                    "operations": [invalid],
                    "export": False,
                }
            )
        )
        rejected = _cli(
            "task",
            "start",
            "--request",
            invalid_path,
            "--task-dir",
            tmp_path / f"invalid-{index}",
            success=False,
        )
        assert rejected["status"] == "blocked", rejected
        assert (
            document.read_bytes() == before_document
            and spec_path.read_bytes() == before_spec
        )
    changes = []
    for target in targets["style_targets"]:
        dry = target["source_selector"].get("condition_label") == "dry"
        style = {"color": "#215977" if dry else "#B65B43"}
        if mode == "given_values":
            style.update(
                marker="circle" if dry else "square",
                marker_fill_mode="filled" if dry else "open",
            )
        else:
            assert target["editable_fields"] == ["color"]
        changes.append(
            {
                "series_id": target["series_id"],
                "expected_style": target["current_style"],
                "style": style,
            }
        )
    style_operation = {"op": "set_categorical_display_style", "changes": changes}
    if mode == "given_values":
        style_operation["legend"] = {
            "position": "upper_right",
            "columns": 2,
            "expected": targets["legend"]["current"],
        }
    else:
        assert targets["legend"] is None
    aliases = {
        "op": "set_category_display_labels",
        "changes": [
            {"category_id": "P", "expected_label": "Initial", "label": "Control"},
            {"category_id": "Q", "expected_label": "Q", "label": "Treatment"},
        ],
    }
    request, review = _start(tmp_path, context, [aliases, style_operation], "late")
    assert review["status"] == "needs_review", review
    assert review["preview"]["scientific_audit"]["status"] == "passed"
    assert (
        document.read_bytes() == before_document
        and spec_path.read_bytes() == before_spec
    )
    assert (
        _cli("task", "start", "--request", request, "--task-dir", tmp_path / "late")[
            "operation_id"
        ]
        == review["operation_id"]
    )
    saved = _accept(tmp_path, review)
    after = json.loads(spec_path.read_text())
    assert {key: value for key, value in after.items() if key != KEY} == baseline
    assert (Path(project) / "plot_request.json").read_bytes() == plot_request
    assert audit_edited_document(document, spec_path)["status"] == "passed"
    inspected = _cli("project", "annotations", project)
    assert inspected["categorical_display"]["categories"][1]["label"] == "Treatment"
    second_context = _context(project)
    assert (
        second_context["categorical_display"]["style_targets"][0]["current_style"][
            "color"
        ]
        == "#215977"
    )
    _, second = _start(
        tmp_path,
        second_context,
        [
            {
                "op": "set_category_display_labels",
                "changes": [
                    {
                        "category_id": "Q",
                        "expected_label": "Treatment",
                        "label": "Treated",
                    }
                ],
            }
        ],
        "second",
    )
    assert second["status"] == "needs_review", second
    second_review = json.loads(Path(second["preview"]["review_path"]).read_text())
    # Fail replacement after the companion spec was installed: existing owner must restore both files.
    pair = document.read_bytes(), spec_path.read_bytes()
    with monkeypatch.context() as fault:

        def reject_replace(*args):
            raise OSError("generated replacement failure")

        fault.setattr(commit, "_replace_current_document", reject_replace)
        with pytest.raises(OSError, match="generated replacement failure"):
            apply_document_edit(Path(project), second_review)
    assert (document.read_bytes(), spec_path.read_bytes()) == pair
    apply_document_edit(Path(project), second_review)
    outcome = (
        history_directory(Path(project), second_review["operation_id"]) / "outcome.json"
    )
    record = json.loads(outcome.read_text())
    record["status"] = (
        "pending"  # Process lost its success reply after durable native+spec replacement.
    )
    outcome.write_text(json.dumps(record))
    _accept(tmp_path, second)
    assert json.loads(outcome.read_text())["status"] == "applied"
    cold = _cold_export(tmp_path, project)
    assert cold["status"] == "complete", cold
    after_datasets = _datasets(document)
    assert set(after_datasets) == set(before_datasets)
    for name, values in before_datasets.items():
        assert (
            np.array_equal(values, after_datasets[name], equal_nan=True)
            if np.issubdtype(values.dtype, np.number)
            else np.array_equal(values, after_datasets[name])
        )
    with loaded_native_document(document) as native:
        assert list(native.data["category_axis_labels"].data) == ["Initial", "Q"]
        assert list(native.data["category_axis_display_labels"].data) == [
            "Control",
            "Treated",
        ]
        assert (
            native.resolveSettingPath(
                None, "/page1/graph1/category_axis_label_provider/labels"
            ).get()
            == "category_axis_display_labels"
        )
        if mode == "given_values":
            for condition, shape, fill in [
                ("dry", "circle", "#215977"),
                ("wet", "square", "white"),
            ]:
                series_id = given_series_ids[condition]
                assert (
                    native.resolveSettingPath(
                        None, f"/page1/graph1/{series_id}/marker"
                    ).get()
                    == shape
                )
                assert (
                    native.resolveSettingPath(
                        None, f"/page1/graph1/{series_id}/MarkerFill/color"
                    ).get()
                    == fill
                )
            assert (
                native.resolveSettingPath(None, "/page1/graph1/key1/columns").get() == 2
            )
            assert (
                native.resolveSettingPath(None, "/page1/graph1/key1/horzPosn").get()
                == "right"
            )
        else:
            for index, color in enumerate(["#215977", "#B65B43"] * 2, 1):
                assert (
                    native.resolveSettingPath(
                        None, f"/page1/graph1/categorical_bar_fill_{index}/Fill/color"
                    ).get()
                    == color
                )
    assert audit_edited_document(document, spec_path)["status"] == "passed"
    for tamper in ["overlay", "alias", "numeric", "n"]:
        altered = deepcopy(json.loads(spec_path.read_text()))
        if tamper == "overlay":
            altered[KEY]["arbitrary_setting"] = "none"
        elif tamper == "alias":
            altered[KEY]["aliases"]["P"] = "Unauthorised"
        elif tamper == "numeric":
            altered["series"][0]["y_values"][0] += 1
        elif mode != "given_values":
            altered["categorical"]["groups"][0]["replicate_count"] += 1
        else:
            continue
        path = tmp_path / (tamper + "-spec.json")
        path.write_text(json.dumps(altered))
        with pytest.raises(ValueError):
            audit_edited_document(document, path)
    verify_exports_and_conflicts(
        tmp_path,
        project=project,
        document=document,
        spec_path=spec_path,
        source=source,
        original=original,
        plot_request=plot_request,
        second_review=second_review,
        mode=mode,
        created=created,
        saved=saved,
        cold=cold,
        given_series_ids=given_series_ids,
    )
