from __future__ import annotations

import pytest

from sciplot_core import render, studio
from sciplot_core.policy import canonical_figure_stem
from sciplot_core.request_contract import normalize_exports


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (["pdf", "tiff"], ["pdf", "tiff_300"]),
        (["png", "svg"], ["png_300", "svg"]),
        (["tif_300"], ["tiff_300"]),
    ],
)
def test_request_exports_use_canonical_shared_names(
    requested: list[str],
    expected: list[str],
) -> None:
    assert normalize_exports(requested) == expected
    assert list(render._normalize_export_formats(requested)) == expected


@pytest.mark.parametrize(
    "requested",
    [
        ["tiff", "tiff_300"],
        ["png", "png_300"],
        ["pdf", "pdf"],
    ],
)
def test_export_alias_collisions_fail_at_request_validation(
    requested: list[str],
) -> None:
    with pytest.raises(ValueError, match="same output artifact"):
        normalize_exports(requested)
    with pytest.raises(ValueError, match="same output artifact"):
        render._normalize_export_formats(requested)
    with pytest.raises(ValueError, match="same output artifact"):
        studio._split_formats(",".join(requested))


def test_pdf_tiff_pairing_uses_one_canonical_stem_contract() -> None:
    assert canonical_figure_stem("Figure_A.pdf") == "figure_a"
    assert canonical_figure_stem("Figure_A_300dpi.tiff") == "figure_a"
    assert canonical_figure_stem("Figure_A_600DPI.png") == "figure_a"
