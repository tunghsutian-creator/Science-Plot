"""FigureSpec v2 extensions require explicit opt-in without changing defaults."""

import pytest

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_grammar import merge_figure_spec, split_figure_spec, validate_figure_spec

from test_figure_grammar import example, resolve


def composition(spec, *, rows=2, columns=2):
    spec["composition"].update(kind="grid", rows=rows, columns=columns,
                               row_weights=[1] * rows, column_weights=[1] * columns)


def test_spans_require_explicit_opt_in_and_preserve_projection_and_compile():
    spec, datasets = example()
    composition(spec)
    spec["composition"]["cells"][0].update(row_span=2, column_span=2)
    with pytest.raises(DocumentError) as captured:
        resolve(spec, datasets)
    assert captured.value.reason_code == "figure_layout_span_unsupported"
    spec["composition"]["capabilities"] = ["spans"]
    assert validate_figure_spec(spec) == spec
    assert merge_figure_spec(*split_figure_spec(spec)) == spec
    resolved = resolve(spec, datasets)
    assert len(resolved["layout"]["panels"]) == 1
    assert resolved["layout"]["panels"][0]["cell_mm"][2] == 86


def test_sparse_cells_require_explicit_opt_in_and_retain_declared_tracks():
    spec, datasets = example()
    composition(spec)
    spec["layout"]["width_mm"] = 180
    spec["composition"]["cells"][0].update(row=1, column=1)
    with pytest.raises(DocumentError) as captured:
        resolve(spec, datasets)
    assert captured.value.reason_code == "figure_layout_empty_cell"
    spec["composition"]["capabilities"] = ["sparse"]
    resolved = resolve(spec, datasets)
    assert len(resolved["layout"]["panels"]) == 1
    assert resolved["layout"]["panels"][0]["row"] == resolved["layout"]["panels"][0]["column"] == 1


@pytest.mark.parametrize("mutation", ["bounds", "unknown_capability", "unopted_span"])
def test_invalid_additive_grammar_state_is_rejected_before_rendering(mutation):
    spec, _ = example()
    composition(spec)
    spec["composition"]["capabilities"] = ["sparse", "spans"]
    if mutation == "bounds":
        spec["composition"]["cells"][0].update(row=1, row_span=2)
    elif mutation == "unknown_capability":
        spec["composition"]["capabilities"].append("arbitrary_layout")
    else:
        spec["composition"]["capabilities"] = ["sparse"]
        spec["composition"]["cells"][0]["column_span"] = 2
    with pytest.raises(DocumentError):
        validate_figure_spec(spec)
