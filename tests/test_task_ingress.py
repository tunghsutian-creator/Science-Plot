"""Malformed transport and obvious invalid style values stop before native work."""

import json
import subprocess

import pytest

from sciplot_core import cli
from sciplot_core.cli.parsers import build_parser
from sciplot_core.native_settings import _bounded_style_value
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, validate_operation_batch
from sciplot_core.style_values import normalize_physical_size, validate_physical_size


@pytest.mark.parametrize("arguments,constraint,detail", [
    (["task", "style", "/saved", "--width", "0.7pt"], "one_of_required", {"options": ["--all-samples", "--sample"]}),
    (["task", "start"], "required", {"missing": ["--request"]}),
    (["task", "capabilities", "--section", "unknown"], "choice", {"argument": "--section", "allowed": ["request", "response", "operations", "table_region"]}),
    (["task", "find", "/source", "--limit", "many"], "type", {"argument": "--limit", "expected": "int"}),
    (["task", "style", "/saved", "--all-samples", "--sample", "A"], "mutually_exclusive", {"argument": "--sample", "options": ["--all-samples", "--sample"]}),
    (["task", "style", "/saved", "--all-samples", "--width"], "value_required", {"argument": "--width"}),
    (["task", "style", "/saved", "--all-samples", "--wid", "0.7pt"], "unrecognized_arguments", {"unsupported_options": ["--wid"]}),
])
def test_json_parser_failures_are_one_bounded_actionable_object(arguments, constraint, detail, capsys):
    assert cli.main([*arguments, "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.err == "" and "usage:" not in captured.out
    payload = json.loads(captured.out)
    assert payload["kind"] == "sciplot_cli_runtime_error"
    assert payload["reason_code"] == "cli_invalid_arguments"
    assert payload["status"] == "failed" and payload["repair"]["action"] == "correct_arguments"
    issue = payload["repair"]["issues"][0]
    assert issue["constraint"] == constraint
    for key, value in detail.items():
        assert issue[key] == value
    assert len(captured.out.encode()) < 1600


def test_json_nested_command_choices_need_no_help_query(capsys):
    assert cli.main(["task", "not-an-action", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    issue = payload["repair"]["issues"][0]
    assert issue["argument"] == "task_action"
    assert "create" in issue["allowed"] and "style" in issue["allowed"]


@pytest.mark.parametrize("arguments", [["task", "style", "--help"], ["task", "style", "--help", "--json"]])
def test_explicit_help_keeps_normal_human_behavior(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    captured = capsys.readouterr()
    assert error.value.code == 0 and "usage:" in captured.out and captured.err == ""


def test_non_json_parse_errors_keep_human_usage(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["task", "style", "/saved", "--all-samples", "--wid", "0.7pt"])
    captured = capsys.readouterr()
    assert error.value.code == 2 and captured.out == "" and "usage:" in captured.err


def test_every_parser_disables_implicit_option_abbreviations():
    import argparse

    pending = [build_parser()]
    while pending:
        parser = pending.pop()
        assert parser.allow_abbrev is False
        pending.extend(child for action in parser._actions if isinstance(action, argparse._SubParsersAction)
                       for child in action.choices.values())


@pytest.mark.parametrize("value", ["0pt", "-1pt", "nanpt", "infpt", "0.7", "0.7PT", "1e3pt", "abc", "9" * 400 + "pt"])
def test_invalid_width_uses_same_preflight_and_native_grammar(value):
    with pytest.raises(ValueError):
        validate_physical_size(value)
    with pytest.raises(ValueError):
        _bounded_style_value({"editor": "distance"}, value)
    with pytest.raises(AnnotationOperationError) as error:
        validate_operation_batch([{"op": "set_sample_style", "samples": ["Exact A"], "style": {"width": value}}])
    assert error.value.field == "operations/0/style/width"
    assert error.value.issues == [{"path": "/operations/0/style/width", "constraint": "positive_physical_size",
                                   "allowed_units": ["pt", "mm", "cm", "in", "inch"], "example": "0.7pt"}]


@pytest.mark.parametrize("value,expected", [(" .70 pt ", ".70pt"), ("\t01.00mm\n", "01.00mm"), ("3. cm", "3.cm"), (".3in", ".3in"), (".3inch", ".3inch")])
def test_only_native_accepted_whitespace_is_normalized(value, expected):
    assert normalize_physical_size(value) == expected
    _bounded_style_value({"editor": "distance"}, value)
    operations = [{"op": "set_sample_style", "samples": ["Exact A"], "style": {"width": value}}]
    validate_operation_batch(operations)
    assert operations[0]["style"]["width"] == value


def test_operation_error_preserves_exact_field_and_allowed_keys_without_echoing_values():
    with pytest.raises(AnnotationOperationError) as error:
        validate_operation_batch([{"op": "set_sample_style", "samples": ["Exact A"],
                                   "style": {"linewidth": "untrusted payload " * 1000}}])
    assert error.value.field == "operations/0/style"
    assert error.value.issues == [{"path": "/operations/0/style", "constraint": "additionalProperties",
                                   "unsupported": ["linewidth"], "allowed": ["color", "width"]}]
    assert len(str(error.value)) < 600 and len(json.dumps(error.value.issues)) < 250


@pytest.fixture
def source_bound_edit(tmp_path, monkeypatch):
    from sciplot_core import task_edit_context
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio_core import project_query

    project = tmp_path / "project"
    (project / "studio").mkdir(parents=True)
    raw = tmp_path / "original.csv"
    raw.write_text("x,y\n400,1\n450,3\n")
    prepared = project / "source.csv"
    prepared.write_bytes(raw.read_bytes())
    (project / "plot_request.json").write_text(json.dumps({"input": str(raw), "study_model": {"samples": [
        {"replicates": [{"source_file": {"raw_path": str(raw), "sha256": file_sha256(raw)}}]}]}}))
    document = project / "studio/document.vsz"
    document.write_text("original native document")
    (project / "studio/spec.json").write_text(json.dumps({"template": "curve", "series": [
        {"name": "series_1", "label": "Exact A", "presentation_kind": "curve",
         "source_artifacts": [{"path": str(prepared), "sha256": file_sha256(prepared)}]}]}))
    native_calls = []
    def native(path):
        native_calls.append(path)
        return {"document": {"path": str(path), "sha256": file_sha256(path)}, "widgets": {}}
    monkeypatch.setattr(project_query, "_inspect_document", native)
    monkeypatch.setattr(task_edit_context, "doctor_payload", lambda: {
        "kind": "sciplot_doctor", "status": "ready", "checks": []})
    return project, raw, document, native_calls


def test_context_rejects_actual_original_source_change_but_preserves_unknown_evidence(source_bound_edit):
    from sciplot_core.task_edit_context import edit_context

    project, raw, document, native_calls = source_bound_edit
    first = edit_context(project, operations=["set_sample_style"])
    assert first["status"] == "ok" and first["current_project"]["source"]["current"] is None
    assert first["current_project"]["ready_to_use"] is None
    original_document = document.read_bytes()
    raw.write_text("x,y\n400,9\n450,3\n")
    with pytest.raises(AnnotationOperationError) as error:
        edit_context(project, operations=["set_sample_style"])
    assert error.value.reason_code == "source_changed"
    assert error.value.repair["action"] == "resolve_source_change"
    assert error.value.issues[0]["changed_paths"] == [str(raw)]
    assert not native_calls and document.read_bytes() == original_document


def test_raw_source_change_during_timeout_stops_before_second_candidate(source_bound_edit, tmp_path, monkeypatch):
    from sciplot_core import task_control
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio_core import annotation_operations, document_edit

    project, raw, document, native_calls = source_bound_edit
    original_document = document.read_bytes()
    candidates = []
    monkeypatch.setattr(annotation_operations, "expand_sample_styles", lambda spec, objects, operations: operations)
    def interrupted_candidate(*args, **kwargs):
        candidates.append(kwargs["output_dir"])
        raw.write_text("x,y\n400,9\n450,3\n")
        raise subprocess.TimeoutExpired(["worker"], 120)
    monkeypatch.setattr(document_edit, "preview_document_edit", interrupted_candidate)
    task = tmp_path / "task"
    result = task_control.start_task({"version": 1, "action": "edit", "project": str(project),
        "expected_document_sha256": file_sha256(document), "operations": [
            {"op": "set_sample_style", "samples": ["Exact A"], "style": {"width": "0.7pt"}}]}, task_dir=task)
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "source_changed"
    assert len(candidates) == 1 and len(native_calls) == 2
    assert result["blocker"]["issues"][0]["changed_paths"] == [str(raw)]
    assert document.read_bytes() == original_document
    assert not (task / "preview_002").exists()
    assert json.loads((task / "task.json").read_text())["preview_timeout_retries"] == 1
