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


def test_header_text_reuses_cell_owner_without_broadening_missing_values() -> None:
    import pandas as pd

    from sciplot_core.source_inspection.header_matching import cell_text
    from sciplot_core.source_tables.parsing import normalize_cell

    assert cell_text is normalize_cell
    values = (None, float("nan"), pd.NA, 0, "  ζ (MPa)  ")
    assert [cell_text(value) for value in values] == ["", "", "<NA>", "0", "ζ (MPa)"]


def test_openai_free_text_reuses_typed_provider_contract_with_same_limits() -> None:
    import pytest

    from sciplot_core.assistant_provider.text_validation import _free_text as typed_free_text
    from sciplot_core.openai_provider.validation import _free_text as model_free_text

    assert model_free_text is typed_free_text
    assert model_free_text("  ", "rationale", maximum=0) == ""
    assert model_free_text("  done  ", "rationale", maximum=4) == "done"
    with pytest.raises(ValueError, match="^rationale must be a string.$"):
        model_free_text(None, "rationale", maximum=4)
    with pytest.raises(ValueError, match="^rationale must contain at most 4 characters.$"):
        model_free_text("longer", "rationale", maximum=4)


def test_public_provider_factory_keeps_one_owner_and_absent_provider_behavior() -> None:
    from sciplot_core.openai_provider import load_openai_provider_from_environment
    from sciplot_core.openai_provider.provider import (
        load_openai_provider_from_environment as owner,
    )

    assert load_openai_provider_from_environment is owner
    assert load_openai_provider_from_environment({}) is None


def test_public_template_validation_keeps_catalog_owner_and_original_error() -> None:
    import pytest

    from sciplot_core.style_contract import validate_veusz_template_id
    from sciplot_core.style_contract.template_contracts import (
        validate_veusz_template_id as owner,
    )

    assert validate_veusz_template_id is owner
    assert validate_veusz_template_id(" curve ") == "curve"
    with pytest.raises(
        ValueError,
        match="Template `missing` is not implemented by SciPlot's Veusz document builder",
    ):
        validate_veusz_template_id("missing")
