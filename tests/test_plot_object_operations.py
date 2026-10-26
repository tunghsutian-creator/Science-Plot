"""Public operation continuity is projected from the current object authority."""

from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType

import pytest
from test_plot_engine import FakeBackend

from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.object_operations import attach_object_operations, plot_object_handle
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import commit


def test_existing_editable_object_declares_real_operations(tmp_path: Path) -> None:
    backend = FakeBackend(tmp_path / "backend")
    document, binding = backend.initial()
    plot = tmp_path / "plot"
    commit(plot, document, binding, "import")

    description = PlotService(backend).describe(plot)

    operations = description["object_operations"]
    assert operations["scope"] == "single_figure"
    assert operations["revision_semantics"] == "monotonic"
    assert operations["authority"] == description["authority"]
    assert operations["patch"] == {"supported": True, "available": True}
    assert operations["export"] == {"supported": True, "available": True}


@pytest.mark.parametrize("state,reason", [
    ({"status": "stale", "changed_inputs": ["source.csv"]}, "document_inputs_changed"),
    ({"pending": {"phase": "needs_review"}}, "document_transaction_pending"),
])
def test_support_does_not_bypass_currentness(state: dict, reason: str) -> None:
    current = {"status": "current", "authority": {"mode": "ManagedPlot"}, "plot_type": "ManagedPlot",
               "edit_targets": {"legend:A": {"properties": ["legend.location"]}}, **state}
    original = deepcopy(current)
    operations = attach_object_operations(current)["object_operations"]
    assert operations["patch"] == {"supported": True, "available": False, "reason_code": reason}
    assert operations["export"] == {"supported": True, "available": False, "reason_code": reason}
    assert current == original


def test_empty_coverage_never_advertises_patch_and_export_recovery_is_distinct() -> None:
    current = {"status": "current", "authority": {"mode": "LegacyPlot"}, "objects": {},
               "pending": {"phase": "export_pending"}}
    operations = attach_object_operations(current)["object_operations"]
    assert operations["patch"] == {"supported": False, "available": False,
                                    "reason_code": "object_no_editable_targets"}
    assert operations["export"] == {"supported": True, "available": True}
    assert operations["describe"]["scopes"] == ["summary"]
    assert operations["describe"]["description_optional"] is True


def test_creation_handle_projects_in_memory_coverage_without_file_access(tmp_path: Path, monkeypatch) -> None:
    backend = FakeBackend(tmp_path / "backend")
    document, _ = backend.initial()
    result = {"status": "complete", "plot": str(tmp_path / "plot"), "plot_id": document["plot_id"],
              "revision": document["revision"], "coordinates": [1, 2, 3], "diagnostic": "private detail"}
    authority = {"mode": "LegacyPlot", "source_of_truth": "saved_native_document"}
    with monkeypatch.context() as no_io:
        no_io.setattr(Path, "read_bytes", lambda _: pytest.fail("Creation handle must not inspect files"))
        handle = plot_object_handle(result, document=document, authority=authority)
    assert handle["plot_type"] == "LegacyPlot"
    assert handle["object_operations"]["patch"]["available"] is True
    assert "coordinates" not in handle and "diagnostic" not in handle
    assert handle["next_step"] == {"action": "plot.describe", "plot": result["plot"], "description": {"scope": "summary"}}
    assert "authority" not in result


def test_native_creation_handle_keeps_legacy_authority_with_explicit_scoped_coverage() -> None:
    result = {"status": "ready", "plot": "/bound/editable/main.vsz", "plot_id": "native:main",
              "revision": 412, "plot_type": "LegacyPlot",
              "authority": {"kind": "native_suite", "visual": "saved_vsz", "semantic_adoption": False},
              "edit_targets": {"legend:main": {"properties": ["legend.location"]}}}
    handle = plot_object_handle(result, revision_semantics="content_bound", edit_scope_supported=True)
    assert handle["plot_type"] == "LegacyPlot"
    assert handle["authority"]["semantic_adoption"] is False
    assert handle["object_operations"]["revision_semantics"] == "content_bound"
    assert handle["object_operations"]["describe"]["scopes"] == ["summary", "edit"]


@pytest.fixture
def native_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sciplot_core import workflow

    owner = ModuleType("sciplot_core.workflow.native_suite_operations")
    target = tmp_path / "suite" / "editable" / "Figure_main.vsz"
    calls: list[tuple] = []

    def resolve(path: Path, figure_id: str | None = None, *, repair: bool = True) -> dict:
        calls.append(("resolve", path, figure_id))
        return {"plot": str(target)}

    def describe(path: Path, *, description: dict | None = None) -> dict:
        calls.append(("describe", path, description))
        return {"kind": "sciplot_plot_description", "version": 1, "status": "current",
                "plot": str(path), "plot_id": "native:main", "revision": 412,
                "plot_type": "LegacyPlot", "authority": {"kind": "native_suite", "visual": "saved_vsz", "semantic_adoption": False},
                "edit_targets": {"legend:main": {"kind": "legend", "properties": ["legend.location"]}}}

    def operation(name: str):
        def invoke(path: Path, request: dict | None = None) -> dict:
            calls.append((name, path, request))
            return {"status": "complete", "plot": str(path), "operation": name}
        return invoke

    owner.resolve_native_object = resolve
    owner.describe_native_object = describe
    for name in ("patch", "decide", "resume", "export"):
        setattr(owner, name + "_native_object", operation(name))
    monkeypatch.setattr(workflow, "native_suite_operations", owner, raising=False)
    monkeypatch.setitem(sys.modules, owner.__name__, owner)
    return owner, target, calls


def test_native_object_uses_same_spine_without_semantic_import(native_owner, tmp_path: Path) -> None:
    _, target, calls = native_owner
    service = PlotService(backend=object())
    summary = service.open(tmp_path / "suite", "Figure_main", description={"scope": "summary"})
    assert summary["plot"] == str(target)
    assert summary["plot_type"] == "LegacyPlot"
    assert summary["object_operations"]["revision_semantics"] == "content_bound"
    assert summary["object_operations"]["patch"]["supported"] is True
    assert summary["object_operations"]["describe"]["scopes"] == ["summary", "edit"]
    assert calls[:2] == [("resolve", tmp_path / "suite", "Figure_main"),
                         ("describe", target, {"scope": "summary"})]
    edit = {"scope": "edit", "target": "legend:main", "property": "legend.location"}
    assert service.describe(target, description=edit)["plot"] == str(target)
    patch = {"plot_id": "native:main", "base_revision": 412, "idempotency_key": "legend-edit",
             "intent_class": "presentation", "changes": [
                 {"op": "set", "target": ["legend:main"], "property": "legend.location", "value": "bottom-left"}]}
    decision = {"decision_id": "native-decision", "base_revision": 412, "accept": True}
    resume = {"plot_id": "native:main", "base_revision": 412, "idempotency_key": "legend-edit"}
    for name, request in (("patch", patch), ("decide", decision), ("resume", resume)):
        result = getattr(service, name)(target, request)
        assert result["operation"] == name
        assert calls[-1] == (name, target, request)
    assert service.export(target)["operation"] == "export"
    assert calls[-1] == ("export", target, None)
    assert not target.parent.exists()


def test_recognized_invalid_native_object_never_falls_through(native_owner) -> None:
    owner, target, calls = native_owner

    def stale(*_, repair: bool = True):
        raise EngineError("native_source_changed", "The bound original source changed.")

    owner.resolve_native_object = stale
    with pytest.raises(EngineError) as error:
        PlotService(backend=object()).open(target)
    assert error.value.reason_code == "native_source_changed"
    assert calls == []


def test_existing_store_does_not_probe_native_owner(native_owner, tmp_path: Path) -> None:
    _, _, calls = native_owner
    backend = FakeBackend(tmp_path / "backend")
    document, binding = backend.initial()
    plot = tmp_path / "plot"
    commit(plot, document, binding, "import")
    result = PlotService(backend).describe(plot)
    assert result["plot_type"] == "LegacyPlot"
    assert calls == []
