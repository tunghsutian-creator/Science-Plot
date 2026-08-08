from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.policy import CONTROL_FIRST_BRIGHT_COLORS, JAMA_EDITORIAL_COLORS
from sciplot_core.render import render_to_dir
from sciplot_core.request_contract import normalize_render_options
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.studio_core.series_encoding_contract import (
    SERIES_ENCODING_CONTRACT_KIND,
    SERIES_ENCODING_CONTRACT_VERSION,
    SERIES_ENCODING_KIND,
    SERIES_ENCODING_VERSION,
)
from sciplot_core.studio_render.metric_columns import _series_label_from_column
from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.series_options import resolve_series_encodings


def _ordinary_series() -> list[StudioSeries]:
    return [
        StudioSeries(
            label="sample_a",
            x_name="x",
            y_name="sample_a",
            x_values=(0.0, 1.0, 2.0),
            y_values=(1.0, 2.0, 3.0),
            color="#FFFFFF",
        ),
        StudioSeries(
            label="sample_b",
            x_name="x",
            y_name="sample_b",
            x_values=(0.0, 1.0, 2.0),
            y_values=(1.5, 2.5, 3.5),
            color="#FFFFFF",
        ),
    ]


def _explicit_options() -> dict[str, object]:
    return {
        "size": "60x55",
        "palette_preset": "jama_editorial",
        "line_style_sequence": ["solid", "dashed"],
        "marker_sequence": ["circle", "square"],
        "marker_fill_mode": "open",
    }


def test_plain_numeric_values_cannot_replace_series_identity() -> None:
    assert (
        _series_label_from_column(
            pd.Series([1.0, 2.0, 3.0]),
            fallback="sample_a",
        )
        == "sample_a"
    )
    assert (
        _series_label_from_column(
            pd.Series(["1", "MPa", 1.0, 2.0]),
            fallback="fallback",
        )
        == "1"
    )


def test_explicit_series_encoding_maps_by_final_series_order() -> None:
    options = _explicit_options()
    request = {
        "template": "point_line",
        "render_options": options,
        "explicit_render_option_keys": list(options),
    }

    assert normalize_render_options(options, template="point_line") == options
    styled = resolve_series_encodings(
        _ordinary_series(),
        render_options=options,
        request=request,
    )

    assert [item.color for item in styled] == list(JAMA_EDITORIAL_COLORS[:2])
    assert [item.line_style for item in styled] == ["solid", "dashed"]
    assert [item.marker for item in styled] == ["circle", "square"]
    assert [item.marker_fill_color for item in styled] == ["white", "white"]
    assert [item.marker_line_color for item in styled] == list(
        JAMA_EDITORIAL_COLORS[:2]
    )
    expected_request_bound = (
        "line.color",
        "line.style",
        "marker.shape",
        "marker.fill_color",
        "marker.line_color",
    )
    assert all(
        item.encoding_provenance.request_bound_fields == expected_request_bound
        for item in styled
    )


def test_series_encoding_has_no_second_palette_resolution_path() -> None:
    options = {
        "palette_preset": "jama_editorial",
        "marker_sequence": ["circle", "square"],
    }
    styled = resolve_series_encodings(
        _ordinary_series(),
        render_options=options,
        request={
            "template": "point_line",
            "render_options": options,
            "explicit_render_option_keys": [],
        },
    )

    assert [item.color for item in styled] == list(CONTROL_FIRST_BRIGHT_COLORS[:2])
    assert all(
        "line.color" not in item.encoding_provenance.request_bound_fields
        for item in styled
    )


@pytest.mark.comprehensive
def test_real_vsz_materializes_and_audits_explicit_series_encoding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_series.csv"
    pd.DataFrame(
        {
            "x": [0.0, 1.0, 2.0],
            "sample_a": [1.0, 2.0, 3.0],
            "sample_b": [1.5, 2.5, 3.5],
        }
    ).to_csv(source, index=False)
    options = _explicit_options()
    result = render_to_dir(
        source,
        template="point_line",
        output_dir=tmp_path / "rendered",
        options=options,
        request_context={"explicit_render_option_keys": list(options)},
        export_formats=("pdf",),
    )
    document_path = Path(result["veusz_documents"][0])
    spec_path = Path(result["veusz_specs"][0])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    document_text = document_path.read_text(encoding="utf-8")

    contract = spec["series_encoding_contract"]
    assert contract["kind"] == SERIES_ENCODING_CONTRACT_KIND
    assert contract["version"] == SERIES_ENCODING_CONTRACT_VERSION
    assert contract["series_count"] == 2
    assert contract["series_names"] == ["series_1", "series_2"]
    assert [item["label"] for item in spec["series"]] == ["sample_a", "sample_b"]
    encodings = [item["encoding"] for item in spec["series"]]
    assert all(item["kind"] == SERIES_ENCODING_KIND for item in encodings)
    assert all(item["version"] == SERIES_ENCODING_VERSION for item in encodings)
    assert [item["line"]["color"] for item in encodings] == list(
        JAMA_EDITORIAL_COLORS[:2]
    )
    assert [item["line"]["style"] for item in encodings] == ["solid", "dashed"]
    assert [item["marker"]["shape"] for item in encodings] == ["circle", "square"]
    assert [item["marker"]["fill_color"] for item in encodings] == [
        "white",
        "white",
    ]
    assert [item["marker"]["line_color"] for item in encodings] == list(
        JAMA_EDITORIAL_COLORS[:2]
    )
    assert "Set('PlotLine/style', 'solid')" in document_text
    assert "Set('PlotLine/style', 'dashed')" in document_text
    assert "Set('marker', 'circle')" in document_text
    assert "Set('marker', 'square')" in document_text
    assert document_text.count("Set('MarkerFill/color', 'white')") == 2

    audit, audited_spec = _audit_exact_document_data(
        document_path=document_path,
        spec_path=spec_path,
    )
    assert audit["status"] == "passed"
    assert audited_spec == spec
    assert audit["series_encoding_count"] == 2
    assert all(
        item["request_bound_fields"]
        == [
            "line.color",
            "line.style",
            "marker.shape",
            "marker.fill_color",
            "marker.line_color",
        ]
        for item in audit["series_encodings"]
    )

    tampered_values = (
        ("line", "color", "#000000", "line.color"),
        ("line", "style", "dotted", "line.style"),
        ("marker", "shape", "diamond", "marker.shape"),
        ("marker", "fill_color", "#000000", "marker.fill_color"),
        ("marker", "line_color", "#000000", "marker.line_color"),
    )
    for group, key, value, field_name in tampered_values:
        tampered = copy.deepcopy(spec)
        tampered["series"][1]["encoding"][group][key] = value
        tampered_path = tmp_path / f"tampered_{group}_{key}.json"
        tampered_path.write_text(
            json.dumps(tampered, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError,
            match=re.escape(f"request-bound encoding '{field_name}'"),
        ):
            _audit_exact_document_data(
                document_path=document_path,
                spec_path=tampered_path,
            )
