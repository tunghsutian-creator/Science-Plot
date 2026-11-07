"""Local AI confirmation adapter; the existing intake and project owners execute."""

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, ValidationError

from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.path_names import slug
from sciplot_core.contract import load_plot_contract
from sciplot_core.materials_rules import get_rule
from sciplot_core.request_contract import normalize_exports, normalize_render_options
from sciplot_core.source_coverage.file_snapshots import _assert_snapshot_current
from sciplot_core.semantic_sources.confirmation_contract import confirmation_capabilities, has_column_intent, require_supported_confirmations
from . import application
from .catalog import intake_catalog_payload
from .config import _REPLICATE_MODES
from .models import IntakeGroupInput
from .project.session_project import read_confirmed_source_file
from .run import publish_prepared_intake_project
from .session import prepare_intake_session
from .session_contract import session_request_schema, session_schema
from .table_preview import preview_table_payload


class IntakeSessionError(ValueError):
    reason_code = "intake_session_invalid"


def prepare_session(source: Path, *, output_root: Path, rule_id: str | None = None) -> dict[str, Any]:
    observed = prepare_intake_session(source, output_root=output_root, requested_rule_id=rule_id)
    fields = ("project_name", "data_type_id", "experiment_type_id", "output_root", "groups", "group_order_is_explicit")
    request = {key: observed[key] for key in fields}
    envelope = {"kind": "sciplot_local_intake_session", "version": 1, "request": request,
                "context": {key: value for key, value in observed.items() if key not in fields},
                "capabilities": {
                    "request_schema": session_request_schema(observed["rule_id"]), "catalog": intake_catalog_payload(),
                    "scientific_choices": (confirmation_capabilities(get_rule(observed["rule_id"]))
                                           if observed.get("rule_id") else {"requires_ready_rule_selection": True}),
                    "template_editable_options": {name: list(spec.editable_options)
                                                  for name, spec in load_plot_contract().templates.items()},
                    "replicate_modes": sorted(_REPLICATE_MODES),
                    "source_binding": "Each original source_path/size_bytes/sha256 is verified by the existing session reader.",
                    "authority": "Edit request choices only; context/capabilities are non-authoritative and never enter execution.",
                    "creation": "A new directory is atomically reserved using the existing name/suffix behavior. A repeated create is another creation, not a native retry.",
                    "table_preview": "intake table SESSION.json --group N --file N [--sheet EXACT_NAME] --json uses zero-based request indices and never substitutes another worksheet.",
                    "next_step": "Confirm sample/file grouping and order, rule navigation, columns, dimensions and exports in request; then intake create SESSION.json --json."}}
    path = Path(observed["session_path"])
    atomic_write_json(path, envelope)
    return {"session": str(path), **envelope}


def _checked_request(value: Any) -> dict[str, Any]:
    if (isinstance(value, dict) and value.get("kind") == "sciplot_intake_session"
            and type(value.get("version")) is int and value["version"] == 1):
        fields = set(session_request_schema()["properties"])
        context = {"kind", "version", "created_at", "session_id", "session_path", "input_path",
                   "data_type_label", "experiment_label", "rule_id", "confidence", "reason", "warnings",
                   "semantic", "pending_rule_review"}
        if set(value) - fields - context:
            raise IntakeSessionError("The legacy intake session contains unknown fields.")
        request = {key: item for key, item in value.items() if key in fields and item is not None}
        request.setdefault("group_order_is_explicit", True)
        value = {"kind": "sciplot_local_intake_session", "version": 1, "request": request}
    try:
        json.dumps(value, allow_nan=False)
        Draft202012Validator(session_schema()).validate(value)
    except (ValidationError, ValueError, TypeError) as exc:
        if isinstance(exc, ValidationError):
            field = "/" + "/".join(map(str, exc.absolute_path))
            raise IntakeSessionError(f"Invalid intake session {field}: {exc.message}") from None
        raise IntakeSessionError("The intake session must contain finite JSON values.") from exc
    request = cast(dict[str, Any], value["request"])
    seen = set()
    for group in request["groups"]:
        key = slug(group["sample"]).casefold()
        if key in seen:
            raise IntakeSessionError("Sample groups must have distinct names and project-local folder identities.")
        seen.add(key)
    normalize_exports(request.get("exports"))
    return request


def _new_plot_output(request: dict[str, Any]) -> None:
    output = request.get("plot_output")
    if output:
        path = Path(output).expanduser()
        if path.is_absolute():
            if path.exists() or path.is_symlink():
                raise IntakeSessionError("plot_output must name a new output, never an existing file, directory or symlink.")
        elif not path.parts or ".." in path.parts or path.parts[0] in {"raw", "source", "studio"}:
            raise IntakeSessionError("Relative plot_output must stay in the new project's output area.")


def _selected_rule(request: dict[str, Any]) -> str:
    catalog = intake_catalog_payload()
    for data_type in catalog["data_types"]:
        if data_type["id"] == request["data_type_id"]:
            for experiment in data_type["experiments"]:
                if experiment["id"] == request["experiment_type_id"]:
                    rule = experiment.get("rule_id")
                    if isinstance(rule, str) and rule in catalog["ready_rule_ids"]:
                        return rule
    raise IntakeSessionError("Choose a currently ready data_type_id/experiment_type_id from the local intake catalog.")


def _validate_columns(request: dict[str, Any], groups: list[IntakeGroupInput], *, rule_id: str) -> None:
    files = [(group.sample.strip(), item.name, reference, item.content)
             for group, declared in zip(groups, request["groups"], strict=True)
             for item, reference in zip(group.files, declared["files"], strict=True)]
    seen = set()
    for confirmation in request.get("column_confirmations", []):
        matches = [(reference, content) for sample, name, reference, content in files
                   if sample == confirmation["sample"].strip() and name == confirmation["file_name"]
                   and (not confirmation.get("source_path")
                        or Path(reference["source_path"]).expanduser().resolve() == Path(confirmation["source_path"]).expanduser().resolve())]
        if len(matches) != 1:
            raise IntakeSessionError("Every column confirmation must identify exactly one selected sample/file.")
        reference, content = matches[0]
        if confirmation["source_sha256"] != reference["sha256"]:
            raise IntakeSessionError("A column/worksheet confirmation belongs to changed source bytes.")
        key = (confirmation["sample"].strip(), confirmation["file_name"], reference["source_path"])
        if key in seen:
            raise IntakeSessionError("A file must have one complete column/worksheet confirmation.")
        seen.add(key)
        preview = preview_table_payload(name=confirmation["file_name"], content=content,
                                        selected_sheet=confirmation.get("sheet"))
        columns = {column["index"]: column for column in preview["columns"]}
        indices = set()
        for column in confirmation["columns"]:
            actual = columns.get(column["index"])
            if (actual is None or column["index"] in indices or column["name"] != actual["name"]
                    or ("inferred_type" in column and column["inferred_type"] != actual["inferred_type"])):
                raise IntakeSessionError("Column identities must match the original preview; indices must be unique.")
            indices.add(column["index"])
        if has_column_intent(confirmation):
            from sciplot_core.semantic_sources.rheology_confirmation import check_confirmed_rheology_bytes

            check_confirmed_rheology_bytes(confirmation["file_name"], content, confirmation, rule_id=rule_id)


def create_session(session: Path) -> dict[str, Any]:
    path = session.expanduser().resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    request = _checked_request(value)
    rule = _selected_rule(request)
    require_supported_confirmations(get_rule(rule), request.get("column_confirmations"))
    normalize_render_options(request.get("render_options"), template=get_rule(rule).template)
    _new_plot_output(request)
    # Only explicit choices enter the existing reader. Model-supplied recognition,
    # confidence, ready flags and context never become scientific observations.
    payload = {**request, "rule_id": rule, "reason": "Explicit local intake selection, not recognition confidence."}

    def checked_factory(**arguments: Any) -> dict[str, Any]:
        _validate_columns(request, arguments["groups"], rule_id=rule)
        return application.create_intake_project(**arguments)

    prepared = application.create_intake_project_from_session(payload, project_factory=checked_factory)
    result = publish_prepared_intake_project(prepared)
    failed = bool(result.get("run_failed") or (result.get("last_run") or {}).get("ready_to_use") is False)
    return {**result, "status": "failed" if failed else "complete", "ready_to_use": not failed,
            "confirmed_session": str(path),
            "selection": {"rule_id": rule, "authority": "explicit_request", "recognition_confidence": None},
            "context_is_non_authoritative": True}


def preview_session_table(session: Path, *, group_index: int, file_index: int,
                          sheet: str | None = None) -> dict[str, Any]:
    value = json.loads(session.expanduser().read_text(encoding="utf-8"))
    request = _checked_request(value)
    if (type(group_index) is not int or type(file_index) is not int or group_index < 0 or file_index < 0
            or group_index >= len(request["groups"]) or file_index >= len(request["groups"][group_index]["files"])):
        raise IntakeSessionError("Select an exact existing group/file index; no other table is substituted.")
    group = request["groups"][group_index]
    reference = group["files"][file_index]
    original, captured = read_confirmed_source_file(reference)
    preview = preview_table_payload(name=original.name, content=original.content, selected_sheet=sheet)
    _assert_snapshot_current(captured, label="Intake table preview", expected_sha256=reference["sha256"])
    confirmation = {"sample": group["sample"], "file_name": reference["name"],
                    "source_path": reference["source_path"], "source_sha256": reference["sha256"],
                    "sheet": preview["sheet"], "sheet_selected": preview["sheet"] is not None,
                    "columns": [{"index": column["index"], "name": column["name"],
                                 "inferred_type": column["inferred_type"], "confirmed_type": "auto", "role": "auto"}
                                for column in preview["columns"]]}
    return {**preview, "group_index": group_index, "file_index": file_index,
            "sample": group["sample"], "source_path": reference["source_path"],
            "confirmation_request": confirmation,
            "creates_project": False, "changes_sources": False}
