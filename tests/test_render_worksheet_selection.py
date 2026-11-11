"""A worksheet selector owns both rendered values and their source replay."""
from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.render import render_to_dir
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_render.table_io import _read_source_frame_records
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.terminal_request import authoritative_terminal_render_request, normalize_terminal_render_request


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path.resolve() / "sheets.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]}).to_excel(writer, sheet_name="first", index=False)
        pd.DataFrame({"x": [1, 2, 3], "y": [100, 200, 300]}).to_excel(writer, sheet_name="wanted", index=False)
    return path


@pytest.mark.parametrize("sheet", ["wanted", 1])
def test_source_reader_uses_requested_worksheet_for_current_and_legacy(workbook, sheet):
    for legacy in (False, True):
        frames = _read_source_frame_records(workbook, request={"sheet": sheet}, legacy_numeric_parser=legacy)
        assert frames[0].frame["y"].tolist() == [100, 200, 300]
    with pytest.raises(StudioPreparationBlocked, match="could not be parsed"):
        _read_source_frame_records(workbook, request={"sheet": "absent"})


def test_direct_render_worksheet_survives_worker_and_exact_source_audit(workbook):
    result = render_to_dir(workbook, template="curve", sheet="wanted",
                           output_dir=workbook.parent / "render", export_formats=["pdf"])
    spec = json.loads(Path(result["veusz_specs"][0]).read_text())
    assert spec["source_request"]["sheet"] == "wanted"
    assert spec["series"][0]["y_values"] == [100., 200., 300.]
    terminal = result["terminal_render_requests"][0]
    assert normalize_terminal_render_request(terminal, label="worksheet") == terminal
    assert authoritative_terminal_render_request(terminal) == terminal
    snapshots = [{"path": str(workbook), "sha256": file_sha256(workbook), "bytes": workbook.read_bytes()}]
    assert _verify_prepared_data(spec, snapshots)["status"] == "passed"
    wrong = deepcopy(spec)
    wrong["source_request"]["sheet"] = "first"
    with pytest.raises(ValueError, match="do not reproduce"):
        _verify_prepared_data(wrong, snapshots)
