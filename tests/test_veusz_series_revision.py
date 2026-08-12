from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.studio import preview_veusz_series_revision
from sciplot_core.studio_core.axis_data_visibility import (
    axis_data_visibility_payload,
)
from sciplot_core.studio_core.figure_set_storage import (
    _commit_studio_figure_set_transaction,
)
from sciplot_core.studio_core.persistence import (
    atomic_save_veusz_document,
    stage_veusz_document,
)
from sciplot_core.studio_core.series_encoding_contract import (
    series_encoding_contract_payload,
)
from sciplot_core.studio_core.series_presentation import (
    effective_series_presentation,
    persist_series_selection,
)


class _Setting:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value


class _Settings:
    def __init__(self, **values: object) -> None:
        self.values = {name: _Setting(value) for name, value in values.items()}

    def get(self, name: str) -> _Setting:
        return self.values[name]


class _Widget:
    def __init__(self, name: str, *, hide: bool = False) -> None:
        self.name = name
        self.parent: _Widget | None = None
        self.children: list[_Widget] = []
        self.settings = _Settings(hide=hide)

    def add(self, *children: _Widget) -> _Widget:
        for child in children:
            child.parent = self
            self.children.append(child)
        return self


class _Document:
    def __init__(self, basewidget: _Widget) -> None:
        self.basewidget = basewidget
        self.historyundo: list[object] = []


class _SavableDocument:
    def __init__(self) -> None:
        self.filename = "live.vsz"
        self.modified = True
        self.changeset = 7
        self._signals_blocked = False

    def isModified(self) -> bool:
        return self.modified

    def signalsBlocked(self) -> bool:
        return self._signals_blocked

    def blockSignals(self, value: bool) -> None:
        self._signals_blocked = value

    def save(self, path: str, _mode: str) -> None:
        Path(path).write_text("new document", encoding="utf-8")
        self.filename = path
        self.modified = False
        self.changeset += 1

    def setModified(self, value: bool) -> None:
        self.modified = value


def test_curve_revision_preview_reports_membership_order_and_preserved_layout(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "studio" / "document.vsz"
    document_path.parent.mkdir()
    document_path.touch()
    (document_path.parent / "spec.json").write_text(
        json.dumps(
            {
                "template": "curve",
                "size_mm": [60, 55],
                "series": [
                    {"name": "series_1", "label": "rPA"},
                    {"name": "series_2", "label": "m-rPA"},
                ],
            }
        ),
        encoding="utf-8",
    )
    graph = _Widget("graph1").add(
        _Widget("x"),
        _Widget("y"),
        _Widget("series_1"),
        _Widget("series_2"),
    )
    document = _Document(_Widget("root").add(_Widget("page1").add(graph)))

    preview = preview_veusz_series_revision(
        document,
        document_path,
        ["m-rPA"],
    )

    assert preview["current_order"] == ["rPA", "m-rPA"]
    assert preview["target_order"] == ["m-rPA"]
    assert preview["removed"] == ["rPA"]
    assert preview["moved"] == []
    assert preview["preserved"] == {
        "page_size_mm": [60.0, 55.0],
        "page_and_graph": True,
        "physical_margins": True,
        "y_axis": True,
        "series_style": True,
        "source_values": True,
    }


def test_box_selection_keeps_source_inventory_and_projects_visible_geometry() -> None:
    series = [
        {
            "name": f"series_{index}",
            "label": label,
            "x_name": f"category_x_{index}",
            "y_name": f"category_y_{index}",
            "x_values": [float(index) - 0.1, float(index) + 0.1],
            "y_values": [float(index), float(index + 1)],
            "category_position": float(index),
            "color": color,
        }
        for index, (label, color) in enumerate(
            (("A", "#111111"), ("B", "#222222"), ("C", "#333333")),
            start=1,
        )
    ]
    axes = {
        "x": {
            "min": 0.5,
            "max": 3.5,
            "ticks": [1.0, 2.0, 3.0],
            "category_labels": ["A", "B", "C"],
            "category_positions": [1.0, 2.0, 3.0],
        },
        "y": {"min": 0.0, "max": 5.0},
    }
    spec = {
        "template": "box_strip",
        "series": series,
        "axes": axes,
        "render_options": {},
        "categorical": {
            "groups": [
                {
                    "label": label,
                    "position": float(index),
                    "replicate_count": 2,
                    "boxplot_eligible": True,
                    "descriptive_statistics": {"median": index + 0.5},
                }
                for index, label in enumerate(("A", "B", "C"), start=1)
            ],
            "raw_replicate_count": 6,
        },
        "series_encoding_contract": series_encoding_contract_payload(series),
        "axis_data_visibility": axis_data_visibility_payload(
            series_specs=series,
            axes=axes,
            render_options={},
        ),
    }

    persisted = persist_series_selection(
        spec,
        source_order=["A", "B", "C"],
        active_order=["C", "A"],
    )
    visible = effective_series_presentation(persisted)

    assert [item["label"] for item in persisted["series"]] == ["A", "B", "C"]
    assert persisted["presentation_series_selection"] == {
        "kind": "sciplot_presentation_series_selection",
        "version": 1,
        "active_order": ["C", "A"],
    }
    assert [item["label"] for item in visible["series"]] == ["C", "A"]
    assert visible["series"][0]["x_values"] == pytest.approx([0.9, 1.1])
    assert visible["series"][1]["x_values"] == pytest.approx([1.9, 2.1])
    assert [item["color"] for item in visible["series"]] == [
        "#333333",
        "#111111",
    ]
    assert visible["axes"]["x"] == {
        "min": 0.5,
        "max": 2.5,
        "ticks": [1.0, 2.0],
        "category_labels": ["C", "A"],
        "category_positions": [1.0, 2.0],
    }
    assert [
        (group["label"], group["position"], group["boxplot_name"], group["median_name"])
        for group in visible["categorical"]["groups"]
    ] == [
        ("C", 1.0, "categorical_boxplot_3", "categorical_box_median_3"),
        ("A", 2.0, "categorical_boxplot_1", "categorical_box_median_1"),
    ]
    assert visible["series_encoding_contract"] == series_encoding_contract_payload(
        visible["series"]
    )
    assert visible["axis_data_visibility"] == axis_data_visibility_payload(
        series_specs=visible["series"],
        axes=visible["axes"],
        render_options={},
    )


def test_staged_save_reuses_atomic_serialization_without_replacing_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "document.vsz"
    target.write_text("old document", encoding="utf-8")
    document = _SavableDocument()

    staged = stage_veusz_document(
        document,
        target,
        staged_validator=lambda *_args, **_kwargs: True,
    )

    staged_path = Path(staged["staged"])
    assert target.read_text(encoding="utf-8") == "old document"
    assert staged_path.read_text(encoding="utf-8") == "new document"
    assert (document.filename, document.modified, document.changeset) == (
        "live.vsz",
        True,
        7,
    )
    staged_path.unlink()

    receipt = atomic_save_veusz_document(
        document,
        target,
        staged_validator=lambda *_args, **_kwargs: True,
    )
    assert receipt["status"] == "passed"
    assert target.read_text(encoding="utf-8") == "new document"
    assert document.filename == str(target)
    assert document.isModified() is False


def test_series_revision_transaction_uses_current_hash_not_generated_hash(
    tmp_path: Path,
) -> None:
    studio_dir = tmp_path / "project" / "studio"
    studio_dir.mkdir(parents=True)
    document = studio_dir / "document.vsz"
    spec = studio_dir / "spec.json"
    registry_path = studio_dir / "figure_set.json"
    document.write_bytes(b"generated document")
    spec.write_text(json.dumps({"template": "curve"}), encoding="utf-8")
    registry_path.write_text(
        json.dumps(
            {"kind": "sciplot_studio_figure_set", "version": 1, "figures": []}
        ),
        encoding="utf-8",
    )
    generated_hash = existing_file_sha256(document)

    staged_document = studio_dir / ".revision.vsz"
    staged_spec = studio_dir / ".revision.spec.json"
    staged_document.write_bytes(b"accepted native series revision")
    staged_spec.write_text(json.dumps({"template": "curve"}), encoding="utf-8")
    current_hash = existing_file_sha256(staged_document)
    assert generated_hash and current_hash and generated_hash != current_hash
    registry = {
        "kind": "sciplot_studio_figure_set",
        "version": 1,
        "status": "ready",
        "figures": [
            {
                "figure_id": "curve",
                "status": "ready",
                "document": str(document),
                "spec": str(spec),
                "generated_hash": generated_hash,
                "document_state": {"current_hash": current_hash},
            }
        ],
    }

    _commit_studio_figure_set_transaction(
        project_dir=tmp_path / "project",
        replacements=[
            {
                "staged": staged_document,
                "target": document,
                "expected_hash": current_hash,
                "kind": "document",
            },
            {
                "staged": staged_spec,
                "target": spec,
                "expected_hash": existing_file_sha256(staged_spec),
                "kind": "spec",
            },
        ],
        manual_archive_requests=[],
        registry=registry,
    )

    installed = json.loads(registry_path.read_text(encoding="utf-8"))["figures"][0]
    assert installed["generated_hash"] == generated_hash
    assert installed["document_state"]["current_hash"] == existing_file_sha256(
        document
    )


def test_failed_series_commit_reverts_only_its_automatic_live_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.studio_core.series_revision_persistence as persistence

    project = tmp_path / "project"
    primary_path = project / "studio" / "document.vsz"
    peer_path = project / "studio" / "figures" / "peer.vsz"
    primary_path.parent.mkdir(parents=True)
    peer_path.parent.mkdir(parents=True)
    primary_path.touch()
    peer_path.touch()
    series = [{"label": "rPA"}, {"label": "m-rPA"}]
    (primary_path.parent / "spec.json").write_text(
        json.dumps({"template": "curve", "series": series}), encoding="utf-8"
    )
    peer_path.with_suffix(".spec.json").write_text(
        json.dumps({"template": "curve", "series": series}), encoding="utf-8"
    )
    (project / "plot_request.json").write_text("{}", encoding="utf-8")
    registry = {
        "kind": "sciplot_studio_figure_set",
        "version": 2,
        "status": "ready",
        "figures": [
            {"figure_id": "primary", "status": "ready", "document": str(primary_path)},
            {"figure_id": "peer", "status": "ready", "document": str(peer_path)},
        ],
    }

    class LiveDocument:
        def __init__(self, name: str, order: list[str], modified: bool) -> None:
            self.name = name
            self.order = order
            self.modified = modified

        def isModified(self) -> bool:
            return self.modified

        def setModified(self, value: bool) -> None:
            self.modified = value

    primary = LiveDocument("primary", ["rPA"], True)
    peer = LiveDocument("peer", ["rPA", "m-rPA"], False)
    applied: list[str] = []
    reverted: list[str] = []

    def apply(document: LiveDocument, _path: Path, target: list[str]) -> None:
        applied.append(document.name)
        document.order = list(target)
        document.modified = True

    def revert(document: LiveDocument, _path: Path) -> None:
        reverted.append(document.name)
        document.order = ["rPA", "m-rPA"]
        document.modified = True

    def stage(document: LiveDocument, target: Path) -> dict[str, object]:
        staged = target.with_name(f".{target.stem}.revision.vsz")
        staged.write_text(document.name, encoding="utf-8")
        return {
            "status": "passed",
            "staged": str(staged),
            "sha256": existing_file_sha256(staged),
        }

    def fail_transaction(**_kwargs: object) -> None:
        raise OSError("injected transaction failure")

    monkeypatch.setattr(persistence, "_read_studio_figure_set", lambda _path: registry)
    monkeypatch.setattr(
        persistence,
        "inspect_veusz_series_revision",
        lambda document, _path: {
            "source_order": ["rPA", "m-rPA"],
            "current_order": list(document.order),
        },
    )
    monkeypatch.setattr(persistence, "apply_veusz_series_revision", apply)
    monkeypatch.setattr(persistence, "revert_veusz_series_revision", revert)
    monkeypatch.setattr(persistence, "stage_veusz_document", stage)
    monkeypatch.setattr(persistence, "audit_spec_data", lambda *_args: None)
    monkeypatch.setattr(
        persistence, "_commit_studio_figure_set_transaction", fail_transaction
    )

    with pytest.raises(OSError, match="injected transaction failure"):
        persistence.commit_project_series_revision(
            project_dir=project,
            active_order=["rPA"],
            live_documents={primary_path: primary, peer_path: peer},
        )

    assert (primary.order, primary.modified) == (["rPA"], True)
    assert (peer.order, peer.modified) == (["rPA", "m-rPA"], False)
    assert applied == ["peer"]
    assert reverted == ["peer"]


@pytest.mark.parametrize("revision_available", [False, True])
def test_project_save_without_applicable_pending_revision_uses_atomic_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revision_available: bool,
) -> None:
    import sciplot_gui.studio_project.series_revision as revision_gui

    document = object()
    target = (tmp_path / "document.vsz").resolve()
    calls: list[tuple[object, Path]] = []
    receipt = {"status": "passed", "target": str(target)}

    class Bridge:
        document_path = target
        _series_revision_available = revision_available
        _atomic_save_document = staticmethod(
            lambda saved_document, saved_target: (
                calls.append((saved_document, saved_target)) or receipt
            )
        )

    bridge = Bridge()
    bridge.document = document
    monkeypatch.setattr(
        revision_gui,
        "has_pending_veusz_series_revision",
        lambda *_args: (
            False
            if revision_available
            else pytest.fail("an unavailable revision feature must not inspect state")
        ),
    )
    monkeypatch.setattr(
        revision_gui,
        "commit_project_series_revision",
        lambda **_kwargs: pytest.fail("ordinary save must not commit a figure set"),
    )

    result = revision_gui.SeriesRevisionMixin.save_or_commit_current_document(
        bridge,
        target,
    )

    assert result is receipt
    assert calls == [(document, target)]
    assert (
        revision_gui.SeriesRevisionMixin._series_revision_export_blocker(bridge)
        is None
    )
