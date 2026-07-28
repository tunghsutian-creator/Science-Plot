from __future__ import annotations

import subprocess

from sciplot_core import one_step, render, source_coverage
from sciplot_gui import studio_assistant
from sciplot_gui.studio_assistant.context_history import ContextHistoryMixin
from sciplot_gui.studio_project.context import ContextMixin


def test_source_coverage_preserves_subprocess_patch_seam() -> None:
    assert source_coverage.subprocess is subprocess


def test_render_preserves_injectable_inspection_seams() -> None:
    assert callable(render.inspect_input_file)
    assert callable(render.classify_source)
    assert callable(render.inspect_payload)


def test_one_step_preserves_public_confidence_thresholds() -> None:
    assert one_step.HIGH_CONFIDENCE_THRESHOLD == 80.0
    assert one_step.MEDIUM_CONFIDENCE_THRESHOLD == 70.0


def test_studio_assistant_preserves_provider_resolution_seam() -> None:
    assert callable(studio_assistant.resolve_assistant_provider)


def test_gui_mixin_descriptors_survive_responsibility_split() -> None:
    assert isinstance(ContextMixin.__dict__["mode"], property)
    assert isinstance(ContextHistoryMixin.__dict__["selected_widget"], property)
    assert isinstance(ContextHistoryMixin.__dict__["pending_batch"], property)
    assert isinstance(
        ContextHistoryMixin.__dict__["_terminal_history_status"],
        staticmethod,
    )
