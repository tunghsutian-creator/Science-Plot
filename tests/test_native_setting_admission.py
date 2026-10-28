"""Native setting admission is readonly; unknown effects never revalidate."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_project_query import project as project
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process.protocol import validate_request
from sciplot_core.project_commands import (
    ProjectCommands,
    ProjectCommand,
    ProjectCommandUnknown,
)
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core import document_edit as edits
from sciplot_core.studio_core.document_edit_commands import preview_native_edit


def changes(value="6mm"):
    return [
        {
            "object_path": "/page1/graph1/key1",
            "setting_path": "/page1/graph1/key1/keyLength",
            "expected_value": "0.40cm",
            "value": value,
        }
    ]


@pytest.fixture
def admitted(project, tmp_path, monkeypatch):
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    document = project / "studio/document.vsz"
    validated, effects = [], []

    def validate(document, spec, supplied, **expected):
        validated.append(supplied)
        assert not store.commands(), (
            "Readonly validation must precede durable effect admission."
        )
        assert file_sha256(document) == expected["expected_document_sha256"]
        assert file_sha256(spec) == expected["expected_spec_sha256"]
        if supplied[0]["value"] == "100cm":
            raise ValueError(
                "The complete native legend must fit inside its physical page."
            )

    def candidate(document, spec, supplied, output, **_kwargs):
        effects.append(supplied)
        (record,) = store.commands()
        assert record["phase"] == "unknown"
        saved, image = output / "candidate.vsz", output / "candidate.png"
        saved.write_bytes(document.read_bytes())
        image.write_bytes(b"controlled native preview")
        return {
            "changes": supplied,
            "candidate": {"path": str(saved), "sha256": file_sha256(saved)},
            "preview": {"path": str(image), "sha256": file_sha256(image)},
            "scientific_audit": {"status": "passed"},
        }

    def preview(value, name="preview", **kwargs):
        return preview_native_edit(
            project,
            changes(value),
            output_dir=tmp_path / name,
            figure_id="first",
            expected_document_sha256=file_sha256(document),
            operations=None,
            expected_spec_sha256=None,
            candidate_builder=candidate,
            audit_document=lambda *_a: {"status": "passed"},
            validate_settings=validate,
            **kwargs,
        )

    return SimpleNamespace(
        project=project,
        store=store,
        before=before,
        document=document,
        validated=validated,
        effects=effects,
        preview=preview,
        candidate=candidate,
        validate=validate,
    )


def test_known_geometry_rejection_has_no_pending_command_and_next_valid_batch_can_complete(
    admitted,
):
    f = admitted
    before = f.document.read_bytes()
    with pytest.raises(ValueError, match="fit inside"):
        f.preview("100cm", "overflow")
    assert f.store.commands() == () and f.effects == []
    assert (
        f.store.snapshot()["generation"] == f.before["generation"]
        and f.document.read_bytes() == before
    )
    review = f.preview("6mm")
    (record,) = f.store.commands()
    assert (
        record["phase"] == "needs_review"
        and len(f.validated) == 2
        and len(f.effects) == 1
    )
    ProjectCommands(f.store).decide(
        ProjectCommand.from_payload(record["metadata"]),
        decision_id=review["decision_id"],
        accept=True,
    )
    assert f.store.commands()[0]["phase"] == "complete"


@pytest.mark.parametrize(
    "phase", ["needs_review", "accepted", "complete", "unknown", "reserved"]
)
def test_existing_command_phase_never_repeats_readonly_validation_or_native_effect(
    admitted, tmp_path, phase
):
    f = admitted
    review = f.preview("6mm")
    (record,) = f.store.commands()
    command = ProjectCommand.from_payload(record["metadata"])
    if phase == "accepted":
        f.store.decide(
            command.key,
            command.command_digest,
            decision_id=review["decision_id"],
            accept=True,
        )
    elif phase == "complete":
        ProjectCommands(f.store).decide(
            command, decision_id=review["decision_id"], accept=True
        )
    elif phase in {"unknown", "reserved"}:
        # Separate exact key generated from the next explicit request identity.
        request_id = ("a" if phase == "unknown" else "b") * 64
        from sciplot_core.studio_core.document_edit_state import native_edit_request_key
        from sciplot_core.studio_core.project_command_scope import figure_binding
        from sciplot_core.studio_core.project_query import resolve_project_figure

        binding = figure_binding(
            f.project, resolve_project_figure(f.project, "first"), store=f.store
        )
        payload = {
            **command.to_payload(),
            "key": native_edit_request_key(binding["project_id"], request_id),
            "request": {**record["metadata"]["request"], "request_id": request_id},
        }
        command = ProjectCommand.from_payload(payload)
        f.store.reserve(
            command.key,
            command.command_digest,
            expected_generation=command.expected_generation,
            read_set=dict(command.read_set),
            write_set=command.write_set,
            metadata=command.to_payload(),
            projected_reads=[item.to_payload() for item in command.projected_reads],
        )
        if phase == "unknown":
            f.store.mark_applying(command.key, command.command_digest)
        with pytest.raises((ProjectCommandUnknown, ValueError)):
            f.preview("6mm", "repeat", request_id=request_id)
        assert len(f.validated) == len(f.effects) == 1
        return
    f.preview("6mm", "repeat")
    assert len(f.validated) == len(f.effects) == 1


def test_semantic_raw_setting_projection_uses_the_same_validation_owner(
    admitted, tmp_path
):
    f = admitted
    operation = {"op": "set_style", **changes("100cm")[0]}
    with pytest.raises(ValueError, match="fit inside"):
        preview_native_edit(
            f.project,
            [],
            output_dir=tmp_path / "semantic-overflow",
            figure_id="first",
            expected_document_sha256=file_sha256(f.document),
            operations=[operation],
            expected_spec_sha256=None,
            candidate_builder=f.candidate,
            audit_document=lambda *_a: {},
            validate_settings=f.validate,
        )
    assert (
        f.validated == [changes("100cm")] and not f.effects and not f.store.commands()
    )


@pytest.mark.parametrize(
    "fault",
    [None, "kind", "version", "extra", "document", "spec", "batch", "transport"],
)
def test_host_validation_binds_exact_readonly_response_and_input_roles(
    project, tmp_path, monkeypatch, fault
):
    from sciplot_core.project_store.native_artifacts import resolve_native_artifact

    store = project_store(project)
    store.snapshot(import_legacy=True)
    document, spec = project / "studio/document.vsz", project / "studio/spec.json"
    before = {p: p.read_bytes() for p in (document, spec)}

    def worker(*argv):
        assert argv[0] == "validate-document-settings" and len(argv) == 5
        assert resolve_native_artifact(Path(argv[1]), role="document") == document
        change_path = resolve_native_artifact(Path(argv[4]), role="changes")
        assert json.loads(change_path.read_bytes()) == changes()
        if fault == "transport":
            raise RuntimeError("unknown readonly transport failure")
        result = {
            "kind": "sciplot_native_setting_validation",
            "version": 1,
            "status": "passed",
            "document": {"path": str(document), "sha256": file_sha256(document)},
            "spec": {"path": str(spec), "sha256": file_sha256(spec)},
            "changes_sha256": hashlib.sha256(change_path.read_bytes()).hexdigest(),
        }
        if fault == "kind":
            result["kind"] = "different"
        elif fault == "version":
            result["version"] = True
        elif fault == "extra":
            result["extra"] = "unbound"
        elif fault in {"document", "spec"}:
            result[fault]["sha256"] = "a" * 64
        elif fault == "batch":
            result["changes_sha256"] = "a" * 64
        return result

    monkeypatch.setattr(edits, "run_document_worker", worker)
    with project_runtime(store):
        if fault is None:
            edits._validate_settings(
                document,
                spec,
                changes(),
                expected_document_sha256=file_sha256(document),
                expected_spec_sha256=file_sha256(spec),
            )
        else:
            with pytest.raises((ValueError, RuntimeError)):
                edits._validate_settings(
                    document,
                    spec,
                    changes(),
                    expected_document_sha256=file_sha256(document),
                    expected_spec_sha256=file_sha256(spec),
                )
    assert {p: p.read_bytes() for p in before} == before and not store.commands()


@pytest.mark.parametrize("fault", ["extra", "missing", "abbreviation", "repeat"])
def test_readonly_command_rejects_extra_or_unknown_arguments(fault):
    argv = [
        "validate-document-settings",
        "/document.vsz",
        "/spec.json",
        "--changes",
        "/batch.json",
    ]
    if fault == "extra":
        argv += ["--out", "/must-not-write.png"]
    elif fault == "missing":
        argv.pop()
    elif fault == "abbreviation":
        argv[3] = "--change"
    else:
        argv += ["--changes", "/different.json"]
    with pytest.raises(ValueError):
        validate_request({"id": "one", "argv": argv})


@pytest.mark.parametrize(
    "value,expected", [("6mm", "0.40cm"), ("100cm", "0.40cm"), ("6mm", "stale")]
)
def test_readonly_native_validator_uses_actual_batch_and_bounds_without_save_or_preview(
    tmp_path, monkeypatch, value, expected
):
    from sciplot_core.veusz_worker import document_edit as native
    from sciplot_core.veusz_audit import pages

    document, spec, batch = (
        tmp_path / name for name in ("document.vsz", "spec.json", "changes.json")
    )
    document.write_bytes(b"saved native input")
    spec.write_bytes(b"{}")
    supplied = changes(value)
    supplied[0]["expected_value"] = expected
    batch.write_text(json.dumps(supplied))
    setting = SimpleNamespace(get=lambda: state["value"], normalize=lambda v: v)
    widget = SimpleNamespace(path="/page1/graph1/key1")
    state = {"value": "0.40cm", "disposed": False}
    loaded = SimpleNamespace(
        resolveWidgetPath=lambda *_a: widget, resolveSettingPath=lambda *_a: setting
    )
    loaded.applyOperation = lambda operations: state.update(value=operations[0][1])

    @contextmanager
    def fresh(_path):
        try:
            yield loaded
        finally:
            state["disposed"] = True

    class ControlKey:
        pass

    control = ControlKey()
    control.widget = widget
    control.posn = (1, 1)

    def geometry(_loaded, _helper):
        control.dims = (3000 if state["value"] == "100cm" else 10, 10)
        helper = SimpleNamespace(
            getControlGraph=lambda _widget: [control], states={}, rootstate=None
        )
        return {widget.path: {"page": 1, "helper": helper}}, [
            {"page": 1, "bounds_mm": [0, 0, 30, 30]}
        ]

    def imports(name):
        if name == "veusz.document.operations":
            return SimpleNamespace(
                OperationSettingSet=lambda path, v: (path, v),
                OperationMultiple=lambda ops, **_kw: ops,
            )
        if name == "veusz.document":
            return SimpleNamespace(
                PaintHelper=object,
                CommandInterface=lambda *_a: pytest.fail(
                    "Readonly validation cannot Save or Export."
                ),
            )
        return SimpleNamespace(ControlKey=ControlKey)

    monkeypatch.setattr(native, "loaded_native_document", fresh)
    monkeypatch.setattr(native, "import_module", imports)
    monkeypatch.setattr(
        native,
        "editable_fields",
        lambda *_a, **_kw: [
            {
                "setting_path": widget.path + "/keyLength",
                "current_value": "0.40cm",
                "editor": "distance",
                "choices": [],
            }
        ],
    )
    monkeypatch.setattr(
        native,
        "_preview",
        lambda *_a: pytest.fail("Readonly validator cannot write preview."),
    )
    monkeypatch.setattr(pages, "collect_page_geometry", geometry)
    before = {p: p.read_bytes() for p in (document, spec, batch)}
    if expected == "stale" or value == "100cm":
        with pytest.raises(
            ValueError, match="expected value" if expected == "stale" else "fit inside"
        ):
            native.validate_document_settings(document, spec, batch)
    else:
        result = native.validate_document_settings(document, spec, batch)
        assert result["status"] == "passed" and result["changes_sha256"] == file_sha256(
            batch
        )
    assert state["disposed"] and {p: p.read_bytes() for p in before} == before
    assert set(tmp_path.iterdir()) == set(before)


def test_closed_cli_validation_reads_only_exact_roles_and_exposes_no_output(
    tmp_path, monkeypatch
):
    from test_project_store import fixture_store
    from sciplot_core.project_store.native_artifacts import (
        NativeArtifactInput,
        native_artifact_runtime,
    )
    from sciplot_core.veusz_worker import cli, document_edit

    store, before = fixture_store(tmp_path)
    document, spec = store.root / "studio/document.vsz", store.root / "studio/spec.json"
    batch = tmp_path / "changes.json"
    batch.write_text(json.dumps(changes()))
    argv = [
        "validate-document-settings",
        str(document),
        str(spec),
        "--changes",
        str(batch),
    ]
    calls = []
    monkeypatch.setattr(
        document_edit,
        "validate_document_settings",
        lambda *args: calls.append(args) or {"readonly": True},
    )
    inputs = tuple(
        NativeArtifactInput(role, path, file_sha256(path), path.stat().st_mode & 0o777)
        for role, path in (("document", document), ("changes", batch))
    )
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs):
        assert cli._execute(argv) == 0
        with pytest.raises(ValueError):
            cli._execute([*argv, "--out", str(tmp_path / "forbidden.png")])
    assert calls == [(document, spec, batch)] and store.snapshot() == before
    assert not (tmp_path / "forbidden.png").exists()
