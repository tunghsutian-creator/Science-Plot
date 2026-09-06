from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from sciplot_gui.studio_project.change_dialogs import project_change_preview_text
from sciplot_gui.studio_project.project_changes import ProjectChangesMixin
from sciplot_gui.studio_project import services
from sciplot_gui.studio_project_services import StudioProjectServices
from sciplot_gui.studio_project_status.workflow_status import _result_targets

pytestmark = pytest.mark.focused


def test_old_service_injections_disable_only_new_project_operations(monkeypatch):
    old = StudioProjectServices(
        atomic_save_document=lambda *_a: {"saved": True},
        export_document=lambda *_a: {},
        publish_standalone_export=lambda **_k: {},
        publish_project_export=lambda **_k: {},
        build_figure_set_scope=lambda **_k: None,
        is_complete_figure_set_scope=lambda _v: False,
    )
    monkeypatch.setattr(services, "_project_services", old)
    assert services.project_change_service("delivery_recovery") is None
    assert services.project_change_service("source_update", apply=True) is None
    assert services.atomic_save_veusz_document(None, Path("saved.vsz")) == {
        "saved": True
    }


def _guard_context(tmp_path):
    project = tmp_path / "project"
    return SimpleNamespace(
        project_dir=project,
        document_path=project / "studio/document.vsz",
        window=SimpleNamespace(),
        document=SimpleNamespace(isModified=lambda: False),
        _exporting=False,
        _document_context_blocker=lambda: None,
        _assistant_export_blocker=lambda: None,
        _series_revision_export_blocker=lambda: None,
    )


@pytest.mark.parametrize(
    "case, expected",
    [
        ("unsaved", "Save or undo"),
        ("export", "current export"),
        ("ai", "pending AI"),
        ("revision", "sample revision"),
        ("busy", "in progress"),
        ("secondary", "primary managed"),
    ],
)
def test_project_changes_refuse_unsafe_live_states(tmp_path, case, expected):
    context = _guard_context(tmp_path)
    if case == "unsaved":
        context.document.isModified = lambda: True
    elif case == "export":
        context._exporting = True
    elif case == "ai":
        context._assistant_export_blocker = lambda: "pending proposal"
    elif case == "revision":
        context._series_revision_export_blocker = lambda: "pending sample selection"
    elif case == "busy":
        context._project_change_busy = True
    else:
        context.document_path = context.project_dir / "studio/secondary.vsz"
    assert expected in ProjectChangesMixin._project_change_blocker(context)


def test_source_review_names_value_changes_even_when_range_is_unchanged():
    def series(digest):
        return {
            "sample": "A",
            **{
                axis: {
                    "count": 3,
                    "minimum": 0,
                    "maximum": 2,
                    "sha256": digest if axis == "y" else "same",
                }
                for axis in ("x", "y", "error")
            },
        }

    preview = {
        "project": "/project",
        "source": "/input/new.csv",
        "worksheet": "Sheet 2",
        "status": "ready",
        "changes": {
            "figures": [
                {
                    "figure_id": "primary",
                    "change": "updated",
                    "samples_added": ["B"],
                    "samples_removed": [],
                    "sample_order_changed": True,
                    "axes_changed": False,
                    "before": {"series": [series("old")]},
                    "after": {"series": [series("new")]},
                    "numerical_differences": [
                        {
                            "sample": "A",
                            "values": "y_values",
                            "changed_value_count": 9,
                            "examples": [
                                {"point_index": 2, "before": 1.0, "after": 1.5}
                            ],
                            "omitted_example_count": 8,
                        }
                    ],
                }
            ]
        },
        "styles": [
            {
                "figure_id": "primary",
                "status": "passed",
                "applied": [
                    {
                        "current_widget": "/page1/graph1/line",
                        "setting": "PlotLine/color",
                        "before": "black",
                        "after": "red",
                    }
                ],
                "skipped": [{"reason": "sample_removed"}],
            }
        ],
    }
    text = project_change_preview_text("source_update", preview)
    for expected in (
        "/input/new.csv",
        "Sheet 2",
        "Added samples: B",
        "A value changes: y",
        "Removed sample; previous sample styles skipped",
        "Preserved 1 compatible style changes: curve color (1)",
        "A y_values: 9 changed values",
        "Point 2: 1.0 → 1.5",
        "8 further changed values",
    ):
        assert expected in text
    assert "PlotLine/color" not in text
    assert "/page1/graph1/line" not in text
    assert "sample_removed" not in text


def test_source_preview_explains_retained_layout_and_omits_empty_errors():
    numbers = {"count": 2, "minimum": 1, "maximum": 2, "sha256": "source"}
    empty = {"count": 0, "minimum": None, "maximum": None, "sha256": "empty"}
    summary = {"series": [{"sample": "A", "x": numbers, "y": numbers, "error": empty}]}
    preview = {
        "status": "ready",
        "changes": {
            "figures": [
                {
                    "figure_id": "dsc_curve",
                    "change": "unchanged",
                    "samples_added": [],
                    "samples_removed": [],
                    "sample_order_changed": False,
                    "axes_changed": False,
                    "before": summary,
                    "after": summary,
                }
            ]
        },
        "styles": [
            {
                "figure_id": "dsc_curve",
                "status": "passed",
                "applied": [],
                "skipped": [
                    {
                        "current_widget": "/page1/graph1/key1",
                        "reason": "new_source_legend_layout_kept",
                    },
                    {
                        "reason": "scientific_geometry_style_kept_from_new_source",
                        "widget_types": ["rect"],
                    },
                ],
            }
        ],
    }
    text = project_change_preview_text("source_update", preview)
    for expected in (
        "No compatible custom style changes",
        "Skipped style transfers: 2",
        "New source legend layout retained",
        "New-source geometry styles retained: rectangle",
    ):
        assert expected in text
    for internal in (
        "/page1/graph1/key1",
        "new_source_legend_layout_kept",
        "scientific_geometry_style_kept_from_new_source",
        "0 points",
        "None … None",
        '"reason"',
    ):
        assert internal not in text


def test_project_change_requires_other_project_windows_to_close(tmp_path):
    context = _guard_context(tmp_path)

    class Window:
        windows: ClassVar[list[object]] = []

    context.window = Window()
    other = Window()
    other._sciplot_project_bridge = SimpleNamespace(project_dir=context.project_dir)
    Window.windows = [context.window, other]
    assert "other windows" in ProjectChangesMixin._project_change_blocker(context)
    Window.windows = [context.window]
    assert ProjectChangesMixin._project_change_blocker(context) is None


def test_blocked_recovery_does_not_claim_source_or_value_preservation():
    text = project_change_preview_text(
        "delivery_recovery", {"status": "blocked", "message": "Source values differ"}
    )
    assert "Source values differ" in text
    assert "source audit passed" not in text


@pytest.mark.parametrize("case", ["current", "failed", "foreign", "unverified"])
def test_delivery_result_uses_only_the_verified_external_root(tmp_path, case):
    visible = tmp_path / "visible"
    visible.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    evidence = tmp_path / "hidden/runs/studio_001/manifest.json"
    verification = {"passed": case != "failed", "expected_root": str(visible)}
    targets = _result_targets(
        live_document={},
        qa={"artifact_qa_current": True},
        evidence_path=evidence,
        delivery={"path": str(foreign if case == "foreign" else visible)},
        delivery_current=True,
        delivery_verification=None if case == "unverified" else verification,
    )
    if case == "current":
        assert targets["delivery"]["path"] == str(visible)
        assert targets["delivery"]["evidence_root"] == str(visible)
        assert targets["delivery"]["current"] is True
    else:
        assert targets["delivery"]["path"] is None
        assert targets["delivery"]["current"] is False
