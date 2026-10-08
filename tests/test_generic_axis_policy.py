from __future__ import annotations

import pytest

from sciplot_core.policy import LINEAR_OUTER_PADDING_FRACTION
from sciplot_core.studio_render.axis_contract import _veusz_axis_contract
from sciplot_core.studio_render.axis_limits import compute_axis_limits
from sciplot_core.studio_render.models import StudioSeries


_OBSERVED_X = (3.5, 10.0, 41.0)


def test_category_wrapping_uses_native_width_preserving_names_and_frame(monkeypatch) -> None:
    import sciplot_core.studio_core.veusz_axis_apply as axis_apply

    long_labels = ["6-66 2 ADR", "E0 2MM", "E3 2MM", "E4 2MM"]
    widths = dict(zip(long_labels, [13.0, 9.0, 9.0, 9.0], strict=True))
    widths.update({label: 3.0 for label in ("E0", "E2", "E3", "E4")})
    widths.update({"6-66": 5.0, "2 ADR": 6.0, "6-66 2": 8.0, "ADR": 4.0})
    measured = []

    def measure(labels, *, family, size_pt):
        measured.append((family, size_pt))
        return [widths[label] for label in labels]

    monkeypatch.setattr(axis_apply, "_category_label_widths_mm", measure)
    axis = {"category_labels": long_labels, "category_positions": [1, 2, 3, 4],
            "min": 0.5, "max": 4.5, "tick_label_size_pt": 7.0}
    style = {"font_family": "Arial"}
    lines = axis_apply.category_label_lines(axis, style, 41.5)
    assert lines == [["6-66", "2 ADR"], ["E0 2MM"], ["E3 2MM"], ["E4 2MM"]]
    assert [" ".join(parts) for parts in lines] == long_labels
    assert axis_apply.category_label_lines(axis, style, 101.5) == [[name] for name in long_labels]
    assert axis_apply.category_label_lines(
        {**axis, "category_labels": ["E0", "E2", "E3", "E4"]}, style, 41.5
    ) == [[name] for name in ["E0", "E2", "E3", "E4"]]
    assert measured and set(measured) == {("Arial", 7.0)}
    assert axis["category_labels"] == long_labels


def test_existing_large_category_rotation_does_not_depend_on_new_measurement(monkeypatch) -> None:
    import sciplot_core.studio_core.veusz_axis_apply as axis_apply

    def unexpected(*args, **kwargs):
        raise AssertionError("The existing >4 category rotation policy must remain unchanged")

    monkeypatch.setattr(axis_apply, "_category_label_widths_mm", unexpected)
    assert axis_apply.category_label_lines({"category_labels": ["A", "B", "C", "D", "E"]}, {}, 41.5) == [[name] for name in "ABCDE"]
    assert axis_apply.category_label_lines({"category_labels": ["A"]}, {}, 41.5) == [["A"]]


def test_unbreakable_colliding_category_blocks_instead_of_dropping_text(monkeypatch) -> None:
    import sciplot_core.studio_core.veusz_axis_apply as axis_apply

    monkeypatch.setattr(axis_apply, "_category_label_widths_mm", lambda labels, **kwargs: [20.0] * len(labels))
    axis = {"category_labels": ["unbreakable", "E0"], "category_positions": [1, 2],
            "min": 0.5, "max": 2.5, "tick_label_size_pt": 7.0}
    with pytest.raises(ValueError, match="cannot fit the fixed frame in two lines"):
        axis_apply.category_label_lines(axis, {"font_family": "Arial"}, 20.0)


@pytest.mark.parametrize("display", [None, ["forged", "E0"]])
def test_category_audit_rejects_missing_or_forged_required_display(monkeypatch, display) -> None:
    from types import SimpleNamespace
    import sciplot_core.studio_core.veusz_data_import as data_import
    import sciplot_core.veusz_worker.spec_audit.categorical_axis as audit

    original = ["long label", "E0"]
    datasets = {"category_axis_labels": original}
    if display is not None:
        datasets["category_axis_display_labels"] = display
    monkeypatch.setattr(audit, "_text_dataset_values", lambda _document, *, dataset_name: datasets.get(dataset_name))
    monkeypatch.setattr(data_import, "category_display_labels", lambda *args: [r"long\\label", "E0"])
    inventory = SimpleNamespace(loaded_document=SimpleNamespace(data=datasets), categorical={"groups": []})
    spec = {"axes": {"x": {"category_labels": original, "category_positions": [1, 2]}},
            "style": {}, "size_mm": [60, 55]}
    with pytest.raises(ValueError, match="display labels differ"):
        audit.audit_categorical_axis(inventory, spec)


def test_generic_linear_axis_padding_uses_the_observed_span() -> None:
    limits = compute_axis_limits(
        [[1.0, 2.0, 3.0]],
        kind="line",
        x_values=[_OBSERVED_X],
    )

    assert limits.raw_xlim is not None
    observed_min, observed_max = limits.raw_xlim
    observed_span = observed_max - observed_min
    padding = observed_span * LINEAR_OUTER_PADDING_FRACTION
    assert limits.xlim == pytest.approx(
        (observed_min - padding, observed_max + padding)
    )
    assert limits.x_tick_policy is not None
    ticks = limits.x_tick_policy.major_ticks
    assert ticks
    assert limits.x_tick_policy.labeled_bounds == (ticks[0], ticks[-1])
    assert all(limits.xlim[0] < tick < limits.xlim[1] for tick in ticks)


def test_reverse_linear_axis_only_reverses_bounds_and_major_ticks() -> None:
    series = [
        StudioSeries(
            label="Observed series",
            x_name="x_observed",
            y_name="y_observed",
            x_values=_OBSERVED_X,
            y_values=(1.0, 2.0, 3.0),
            color="#374E55",
        )
    ]
    forward = _veusz_axis_contract(
        {},
        template_id="curve",
        series=series,
        explicit_render_options={},
    )
    reverse = _veusz_axis_contract(
        {"reverse_x": True},
        template_id="curve",
        series=series,
        explicit_render_options={},
    )

    assert reverse.x_min == pytest.approx(forward.x_max)
    assert reverse.x_max == pytest.approx(forward.x_min)
    assert reverse.x_ticks == tuple(reversed(forward.x_ticks))
    assert forward.x_min not in forward.x_ticks
    assert forward.x_max not in forward.x_ticks
    assert reverse.x_min not in reverse.x_ticks
    assert reverse.x_max not in reverse.x_ticks
