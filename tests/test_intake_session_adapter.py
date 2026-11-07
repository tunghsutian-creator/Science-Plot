"""The retired HTTP choices reach one existing local intake execution owner."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import anyio
import pandas as pd
import pytest

from sciplot_core.intake import application, session_adapter as adapter


def _reference(path):
    content = path.read_bytes()
    return {
        "name": path.name,
        "source_path": str(path),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _save(tmp_path, *, source=None):
    source = source or tmp_path / "source.csv"
    if not source.exists():
        source.write_text("Temperature (°C),Heat Flow (W/g)\n10,1\n20,2\n30,3\n")
    value = {
        "kind": "sciplot_local_intake_session",
        "version": 1,
        "request": {
            "project_name": "Confirmed",
            "data_type_id": "thermal",
            "experiment_type_id": "dsc_curve",
            "output_root": str(tmp_path / "projects"),
            "group_order_is_explicit": True,
            "groups": [{"sample": "A", "files": [_reference(source)]}],
        },
    }
    path = tmp_path / "session.json"
    path.write_text(json.dumps(value))
    return path, source, value


def _write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def calls(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(("create", kwargs))
        return {"project_dir": "controlled-prepared", "studio": {"status": "ready"}}

    def publish(project):
        calls.append(("publish", project))
        return {"ready_to_use": True, "project_dir": project["project_dir"]}

    monkeypatch.setattr(application, "create_intake_project", create)
    monkeypatch.setattr(adapter, "publish_prepared_intake_project", publish)
    return calls


def _confirmation(path, source, value, *, sheet=None):
    preview = adapter.preview_session_table(
        path, group_index=0, file_index=0, sheet=sheet
    )
    return preview["confirmation_request"]


def test_prepare_exposes_editable_request_and_existing_scientific_capabilities(
    tmp_path,
):
    source = tmp_path / "source.csv"
    source.write_text("Temperature (°C),Heat Flow (W/g)\n10,1\n20,2\n")
    original = source.read_bytes()
    result = adapter.prepare_session(
        source, output_root=tmp_path / "out", rule_id="dsc_curve"
    )
    saved = json.loads(Path(result["session"]).read_text())
    assert saved == {key: value for key, value in result.items() if key != "session"}
    assert saved["request"]["groups"][0]["files"] == [_reference(source)]
    assert saved["request"]["group_order_is_explicit"] is False
    assert "semantic" not in saved["request"] and "semantic" in saved["context"]
    capabilities = saved["capabilities"]
    assert capabilities["request_schema"]["additionalProperties"] is False
    assert "dsc_curve" in capabilities["catalog"]["ready_rule_ids"]
    assert capabilities["replicate_modes"] == ["individual", "mean", "representative"]
    assert (
        source.read_bytes() == original
        and not (tmp_path / "out" / "Confirmed").exists()
    )


def test_confirmed_choices_enter_one_preparation_and_one_publication(tmp_path, calls):
    path, source, value = _save(tmp_path)
    second = tmp_path / "other.csv"
    second.write_text("Temperature (°C),Heat Flow (W/g)\n10,4\n20,5\n30,6\n")
    request = value["request"]
    request["groups"].insert(0, {"sample": "B", "files": [_reference(second)]})
    request.update(
        replicate_mode="individual",
        exports=["pdf", "png_300"],
        render_options={"size": "120x55"},
    )
    value["context"] = {
        "semantic": {"rule_id": "invented"},
        "confidence": 100,
        "pending_rule_review": False,
    }
    value["capabilities"] = {"ready_rule_ids": ["invented"]}
    _write(path, value)
    original = {source: source.read_bytes(), second: second.read_bytes()}
    result = adapter.create_session(path)
    assert [item[0] for item in calls] == ["create", "publish"]
    kwargs = calls[0][1]
    assert [group.sample for group in kwargs["groups"]] == ["B", "A"]
    assert [group.files[0].content for group in kwargs["groups"]] == [
        original[second],
        original[source],
    ]
    assert kwargs["group_order_is_explicit"] is True
    assert kwargs["replicate_mode"] == "individual" and kwargs["exports"] == [
        "pdf",
        "png_300",
    ]
    assert kwargs["render_options"] == {"size": "120x55"}
    assert kwargs["recognition"]["rule_id"] == "dsc_curve"
    assert kwargs["recognition"]["confidence"] is None
    assert "pending_rule_review" not in kwargs["recognition"]
    assert result["selection"] == {
        "rule_id": "dsc_curve",
        "authority": "explicit_request",
        "recognition_confidence": None,
    }
    assert all(item.read_bytes() == content for item, content in original.items())


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "semantic",
        "duplicate_sample",
        "case_colliding_sample",
        "unknown_rule",
        "bad_role",
        "bad_type",
        "bad_column",
        "duplicate_column",
        "bad_header",
        "bad_sha",
        "wrong_file",
        "wrong_source_path",
        "sheet_without_confirm",
        "bad_size",
        "unsupported_template_option",
        "bad_export",
        "bad_output",
        "occupied_output",
    ],
)
def test_invalid_external_choice_rejects_before_project_creation(
    tmp_path, calls, change
):
    path, source, value = _save(tmp_path)
    request = value["request"]
    confirmation = _confirmation(path, source, value)
    request["column_confirmations"] = [confirmation]
    if change == "unknown":
        request["surprise"] = True
    elif change == "semantic":
        request["semantic"] = {"confidence": 100}
    elif change == "duplicate_sample":
        request["groups"].append(deepcopy(request["groups"][0]))
    elif change == "case_colliding_sample":
        request["groups"].append({**deepcopy(request["groups"][0]), "sample": "a"})
    elif change == "unknown_rule":
        request["experiment_type_id"] = "unknown_thermal"
    elif change == "bad_role":
        confirmation["columns"][0]["role"] = "force_x"
    elif change == "bad_type":
        confirmation["columns"][0]["confirmed_type"] = "numberish"
    elif change == "bad_column":
        confirmation["columns"][0]["index"] = 999
    elif change == "duplicate_column":
        confirmation["columns"].append(deepcopy(confirmation["columns"][0]))
    elif change == "bad_header":
        confirmation["columns"][0]["name"] = "Invented unit"
    elif change == "bad_sha":
        confirmation["source_sha256"] = "0" * 64
    elif change == "wrong_file":
        confirmation["file_name"] = "not-selected.csv"
    elif change == "wrong_source_path":
        confirmation["source_path"] = str(tmp_path / "not-selected.csv")
    elif change == "sheet_without_confirm":
        confirmation["sheet"] = "Heating"
    elif change == "bad_size":
        request["render_options"] = {"size": "invalid-size"}
    elif change == "unsupported_template_option":
        request["render_options"] = {"line_style_sequence": ["solid", "dashed"]}
    elif change == "bad_export":
        request["exports"] = ["made_up"]
    elif change == "bad_output":
        request["plot_output"] = "raw/source.csv"
    elif change == "occupied_output":
        request["plot_output"] = str(source)
    _write(path, value)
    with pytest.raises(ValueError):
        adapter.create_session(path)
    assert calls == [] and not (tmp_path / "projects").exists()


@pytest.mark.parametrize("change", ["bytes", "size", "missing"])
def test_source_binding_rejects_drift_before_creation(tmp_path, calls, change):
    path, source, value = _save(tmp_path)
    if change == "bytes":
        source.write_bytes(source.read_bytes().replace(b"10,1", b"10,9"))
    elif change == "size":
        value["request"]["groups"][0]["files"][0]["size_bytes"] += 1
    else:
        source.unlink()
    _write(path, value)
    with pytest.raises((ValueError, FileNotFoundError)):
        adapter.create_session(path)
    assert calls == [] and not (tmp_path / "projects").exists()


def test_column_and_worksheet_facts_pass_without_reinterpreting_choices(
    tmp_path, calls
):
    source = tmp_path / "source.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        for name, values in [("Heating", [1, 2]), ("Cooling", [4, 3])]:
            pd.DataFrame(
                {"Temperature (°C)": [10, 20], "Heat Flow (W/g)": values}
            ).to_excel(writer, sheet_name=name, index=False)
    path, _, value = _save(tmp_path, source=source)
    confirmation = _confirmation(path, source, value, sheet="Cooling")
    value["request"]["column_confirmations"] = [confirmation]
    _write(path, value)
    adapter.create_session(path)
    assert calls[0][1]["column_confirmations"] == [confirmation]
    assert confirmation["columns"][0]["name"] == "Temperature (°C)"
    confirmation["sheet"] = "Missing"
    _write(path, value)
    calls.clear()
    with pytest.raises(ValueError, match="worksheet|Worksheet"):
        adapter.create_session(path)
    assert calls == []


def test_readonly_preview_reads_only_exact_selected_source_and_never_creates(
    tmp_path, monkeypatch, calls
):
    path, source, value = _save(tmp_path)
    missing = _reference(source) | {"source_path": str(tmp_path / "not-present.csv")}
    value["request"]["groups"].append({"sample": "Unselected", "files": [missing]})
    _write(path, value)
    result = adapter.preview_session_table(path, group_index=0, file_index=0)
    assert result["source_sha256"] == _reference(source)["sha256"]
    assert result["creates_project"] is False and result["changes_sources"] is False
    assert calls == [] and not (tmp_path / "projects").exists()
    with pytest.raises(FileNotFoundError):
        adapter.preview_session_table(path, group_index=1, file_index=0)


@pytest.mark.parametrize(
    ("group", "file"), [(-1, 0), (0, -1), (1, 0), (0, 1), (True, 0)]
)
def test_preview_never_substitutes_unknown_selector(tmp_path, group, file):
    path, _, _ = _save(tmp_path)
    with pytest.raises(ValueError, match="exact existing"):
        adapter.preview_session_table(path, group_index=group, file_index=file)


def test_same_bytes_replacement_between_operations_is_allowed_but_during_read_is_not(
    tmp_path, monkeypatch, calls
):
    path, source, _ = _save(tmp_path)
    original = source.read_bytes()
    replacement = tmp_path / "replacement.csv"
    replacement.write_bytes(original)
    replacement.replace(source)
    adapter.preview_session_table(path, group_index=0, file_index=0)
    adapter.create_session(path)
    real_preview = adapter.preview_table_payload

    def replace_during_read(**kwargs):
        result = real_preview(**kwargs)
        replacement.write_bytes(original)
        replacement.replace(source)
        return result

    monkeypatch.setattr(adapter, "preview_table_payload", replace_during_read)
    with pytest.raises(ValueError, match="changed during exact-current"):
        adapter.preview_session_table(path, group_index=0, file_index=0)
    assert source.read_bytes() == original


def test_legacy_session_uses_the_same_request_owner_without_trusting_recognition(
    tmp_path, calls
):
    path, _, value = _save(tmp_path)
    legacy = {
        **value["request"],
        "kind": "sciplot_intake_session",
        "version": 1,
        "semantic": {"rule_id": "invented"},
        "confidence": 100,
        "pending_rule_review": False,
    }
    _write(path, legacy)
    adapter.create_session(path)
    assert calls[0][1]["recognition"]["rule_id"] == "dsc_curve"
    assert calls[0][1]["recognition"]["confidence"] is None


def test_cli_and_mcp_call_the_same_three_local_services(tmp_path, monkeypatch, capsys):
    from sciplot_core import cli
    from sciplot_core.mcp_server import server

    seen = []

    def prepare(source, **kwargs):
        seen.append(("prepare", source, kwargs))
        return {"kind": "prepared"}

    def table(session, **kwargs):
        seen.append(("table", session, kwargs))
        return {"kind": "table"}

    def create(session):
        seen.append(("create", session))
        return {"kind": "created"}

    monkeypatch.setattr(adapter, "prepare_session", prepare)
    monkeypatch.setattr(adapter, "preview_session_table", table)
    monkeypatch.setattr(adapter, "create_session", create)
    for argv in (
        [
            "prepare",
            str(tmp_path),
            "--out",
            str(tmp_path / "out"),
            "--rule",
            "dsc_curve",
        ],
        [
            "table",
            str(tmp_path / "session.json"),
            "--group",
            "0",
            "--file",
            "1",
            "--sheet",
            "Cooling",
        ],
        ["create", str(tmp_path / "session.json")],
    ):
        assert cli.main(["intake", *argv, "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["kind"] in {
            "prepared",
            "table",
            "created",
        }
    cli_calls = deepcopy(seen)
    seen.clear()

    async def scenario():
        control = server.Adapter()
        for name, arguments in [
            (
                "prepare",
                {
                    "source": str(tmp_path),
                    "output_root": str(tmp_path / "out"),
                    "rule_id": "dsc_curve",
                },
            ),
            (
                "table",
                {
                    "session": str(tmp_path / "session.json"),
                    "group_index": 0,
                    "file_index": 1,
                    "sheet": "Cooling",
                },
            ),
            ("create", {"session": str(tmp_path / "session.json")}),
        ]:
            result = await control.call("sciplot_intake_" + name, arguments)
            assert not result.is_error
        invalid = await control.call(
            "sciplot_intake_table",
            {"session": "x", "group_index": 0, "file_index": 0, "code": "bad"},
        )
        assert invalid.is_error

    anyio.run(scenario)
    assert seen == cli_calls


def test_cli_invalid_session_uses_existing_error_protocol_without_target_io(
    tmp_path, capsys, calls
):
    from sciplot_core import cli

    path, _, value = _save(tmp_path)
    value["request"]["unexpected"] = "never execute"
    _write(path, value)
    assert cli.main(["intake", "create", str(path), "--json"]) != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_code"] == "intake_session_invalid"
    assert calls == []
