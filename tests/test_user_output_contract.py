from pathlib import Path

import pytest

from sciplot_core.output_contract import (
    requested_delivery_root,
    resolve_user_output_layout,
)


def test_default_user_output_is_visible_beside_source_and_runtime_is_hidden(
    tmp_path: Path,
) -> None:
    source = tmp_path / "frequency sweep.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")

    layout = resolve_user_output_layout(source)

    assert layout.delivery_root == tmp_path / "frequency_sweep_SciPlot"
    assert layout.workspace_root == tmp_path / ".sciplot" / "frequency_sweep_sciplot"


def test_explicit_out_is_exact_visible_root(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    requested = tmp_path / "Paper Figure"

    layout = resolve_user_output_layout(
        source,
        requested_delivery_root=requested,
    )

    assert layout.delivery_root == requested
    assert layout.workspace_root == tmp_path / ".sciplot" / "paper_figure"


@pytest.mark.parametrize("requested", ["source", "."])
def test_output_must_be_a_dedicated_directory(
    tmp_path: Path,
    requested: str,
) -> None:
    source = tmp_path / "source"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    output = source if requested == "source" else tmp_path

    with pytest.raises(ValueError, match="dedicated directory"):
        resolve_user_output_layout(source, requested_delivery_root=output)


def test_manifest_request_controls_visible_delivery_root(tmp_path: Path) -> None:
    visible = tmp_path / "Visible"
    run_output = tmp_path / ".sciplot" / "project" / "run_001"

    resolved = requested_delivery_root(
        {"request": {"delivery_output": str(visible)}},
        run_output=run_output,
    )

    assert resolved == visible


def test_legacy_manifest_keeps_internal_delivery_fallback(tmp_path: Path) -> None:
    run_output = tmp_path / "run_001"

    assert requested_delivery_root({}, run_output=run_output) == run_output / "delivery"
