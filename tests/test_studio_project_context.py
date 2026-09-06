from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_project_probe import _copy_project_fixture
from sciplot_gui.studio_project import context as context_module
from sciplot_gui.studio_project.context import ContextMixin


class _StatusView:
    def setPlainText(self, _text: str) -> None:
        pass


class _Context(ContextMixin):
    def __init__(self, document_path: Path) -> None:
        self.document_path = document_path
        self.project_dir = document_path.parent
        self.window = object()
        self.status_view = _StatusView()
        self.status_snapshot: dict[str, Any] = {
            "scientific_transform_review": {
                "status": "available",
                "semantic_family": "rheology_stress_relaxation",
            }
        }
        self.published_status: dict[str, Any] | None = None

    def _publish_status(self, status: dict[str, Any]) -> None:
        self.published_status = status


def test_document_context_change_clears_scientific_transform_review(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    bound_document = tmp_path / "bound.vsz"
    changed_document = tmp_path / "changed.vsz"
    context = _Context(bound_document)
    monkeypatch.setattr(
        context_module,
        "resolved_window_document_path",
        lambda _window: changed_document,
    )
    monkeypatch.setattr(context_module, "_status_text", lambda _status: "blocked")

    status = context.handle_document_context_changed()

    assert status is not None
    assert status["state"] == "document_context_changed"
    assert status["scientific_transform_review"] is None
    assert context.published_status is status


def _copyable_project(tmp_path: Path) -> Path:
    project = tmp_path / "original"
    (project / "raw").mkdir(parents=True)
    (project / "source").mkdir()
    (project / "studio").mkdir()
    (project / "raw" / "input.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    source = project / "source" / "prepared.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    document = project / "studio" / "document.vsz"
    document.write_text("# exact-current native document\n", encoding="utf-8")
    spec = project / "studio" / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "kind": "sciplot_veusz_plot_spec",
                "series": [
                    {
                        "source_artifacts": [
                            {
                                "path": str(source),
                                "sha256": file_sha256(source),
                            }
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project / "studio" / "figure_set.json").write_text(
        json.dumps(
            {
                "primary_document": str(document),
                "figures": [{"document": str(document), "spec": str(spec)}],
                "resolved_figure_plan": {
                    "outcomes": [{"artifacts": [str(document), str(spec)]}]
                },
            }
        ),
        encoding="utf-8",
    )
    (project / "plot_request.json").write_text(
        json.dumps(
            {
                "source": str(source),
            }
        ),
        encoding="utf-8",
    )
    return project


@pytest.mark.parametrize("preserve_registry", [False, True])
def test_probe_fixture_copy_rebinds_only_proven_sources(
    tmp_path: Path,
    preserve_registry: bool,
) -> None:
    original = _copyable_project(tmp_path)
    original_files = {
        p.relative_to(original): p.read_bytes()
        for p in original.rglob("*")
        if p.is_file()
    }

    copied = _copy_project_fixture(
        original,
        tmp_path / "probe",
        preserve_stale_registry_paths=preserve_registry,
    )

    for path in ("raw/input.csv", "source/prepared.csv", "studio/document.vsz"):
        assert (copied / path).read_bytes() == original_files[Path(path)]
    spec = json.loads((copied / "studio/spec.json").read_text())
    assert spec["series"][0]["source_artifacts"] == [
        {
            "path": str(copied / "source/prepared.csv"),
            "sha256": file_sha256(copied / "source/prepared.csv"),
        }
    ]
    registry = json.loads((copied / "studio/figure_set.json").read_text())
    expected_root = original if preserve_registry else copied
    assert registry["primary_document"] == str(expected_root / "studio/document.vsz")
    assert registry["figures"][0]["spec"] == str(expected_root / "studio/spec.json")
    assert registry["resolved_figure_plan"]["outcomes"][0]["artifacts"] == [
        str(expected_root / "studio/document.vsz"),
        str(expected_root / "studio/spec.json"),
    ]
    assert original_files == {
        p.relative_to(original): p.read_bytes()
        for p in original.rglob("*")
        if p.is_file()
    }


def test_probe_fixture_copy_rejects_unproven_prepared_source(tmp_path: Path) -> None:
    original = _copyable_project(tmp_path)
    (original / "source/prepared.csv").write_text("x,y\n1,999\n", encoding="utf-8")

    with pytest.raises(ValueError, match="specification hash"):
        _copy_project_fixture(original, tmp_path / "probe")
