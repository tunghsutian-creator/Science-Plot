import os

import pandas as pd
import pytest

from sciplot_core.source_tables.read_session import read_table_once, table_read_session


def test_parse_reuse_checks_actual_bytes_and_returns_independent_frames(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("1")
    original_stat = path.stat()
    calls = []

    def read():
        calls.append(path.read_text())
        return pd.DataFrame({"value": [int(path.read_text())]})

    with table_read_session():
        first = read_table_once(path, ("test",), read)
        first.iat[0, 0] = 999
        with table_read_session():
            assert read_table_once(path, ("test",), read).iat[0, 0] == 1
        path.write_text("2")
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        assert read_table_once(path, ("test",), read).iat[0, 0] == 2
    with table_read_session():
        assert read_table_once(path, ("test",), read).iat[0, 0] == 2
    assert calls == ["1", "2", "2"]


def test_mutation_during_parse_is_not_cached(tmp_path):
    path = tmp_path / "data"
    path.write_text("a")

    def changing():
        path.write_text("b")
        return pd.DataFrame({"value": [1]})

    with table_read_session(), pytest.raises(ValueError, match="changed while reading"):
        read_table_once(path, ("test",), changing)


def test_mapping_reuses_excel_parses_without_skipping_cell_evidence(tmp_path, monkeypatch):
    from sciplot_core.data_mapping.raw_tables import _read_raw_table
    from sciplot_core.mapping_contract import DataSourceReference
    from sciplot_core.foundation.file_hashing import file_sha256

    source = tmp_path / "data.xlsx"
    pd.DataFrame([["Sample", "A"], [1, 2]]).to_excel(source, header=False, index=False)
    original = pd.read_excel
    calls = []

    def read(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "read_excel", read)
    with table_read_session():
        for _ in range(3):
            ref = DataSourceReference("a", source.name, file_sha256(source), header_row=None)
            assert len(_read_raw_table(ref, source).frame) == 2
        bad = DataSourceReference("a", source.name, file_sha256(source), header_row=None,
                                  cell_evidence={"0,1": "B"})
        with pytest.raises(ValueError, match="Metadata cell"):
            _read_raw_table(bad, source)
    assert calls == [1]


def test_selected_frame_reuse_keeps_missing_tokens_and_evidence_modes_separate(tmp_path, monkeypatch):
    from sciplot_core.data_mapping import raw_tables
    from sciplot_core.mapping_contract import DataSourceReference
    from sciplot_core.foundation.file_hashing import file_sha256

    source = tmp_path / "data.csv"
    source.write_text('Wavelength,Signal\nnm,a.u.\n400, NA \n450,2\n500,3\n')
    ref = DataSourceReference("a", source.name, file_sha256(source), header_row=0,
                              data_start_row=2, data_end_row=4, cell_evidence={"2,1": " NA "})
    calls = []
    original = raw_tables._normalize_missing

    def normalize(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(raw_tables, "_normalize_missing", normalize)
    with table_read_session():
        first = raw_tables._read_raw_table(ref, source)
        assert pd.isna(first.frame.iat[0, 1])
        first.frame.iat[1, 1] = "changed"
        second = raw_tables._read_raw_table(ref, source)
        assert second.frame.iat[1, 1] == "2" and len(calls) == 4
        raw = raw_tables._read_raw_table(ref, source, preserve_cells=True)
        assert raw.frame.iat[0, 1] == " NA " and len(calls) == 4
        from dataclasses import replace
        with pytest.raises(ValueError, match="Metadata cell"):
            raw_tables._read_raw_table(replace(ref, cell_evidence={"2,1": "NA"}), source)
        assert len(raw_tables._read_raw_table(replace(ref, data_end_row=5), source).frame) == 3


def test_normalization_cannot_cache_old_cells_under_new_file_bytes(tmp_path, monkeypatch):
    from sciplot_core.data_mapping import raw_tables
    from sciplot_core.mapping_contract import DataSourceReference
    from sciplot_core.foundation.file_hashing import file_sha256

    source = tmp_path / "data.csv"
    source.write_text("X,Y\n1,2\n")
    ref = DataSourceReference("a", source.name, file_sha256(source), header_row=0)
    original = raw_tables._cell_text

    def changed(value):
        source.write_text("X,Y\n1,3\n")
        return original(value)

    monkeypatch.setattr(raw_tables, "_cell_text", changed)
    with table_read_session(), pytest.raises(ValueError, match="changed while reading"):
        raw_tables._read_raw_table(ref, source)


def test_workbook_sheet_name_reuse_is_invalidated_by_new_bytes(tmp_path, monkeypatch):
    from sciplot_core.source_tables.raw_readers import read_sheet_names

    source = tmp_path / "data.xlsx"
    pd.DataFrame([[1]]).to_excel(source, sheet_name="First", index=False)
    calls = []
    original = pd.ExcelFile

    def read(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "ExcelFile", read)
    with table_read_session():
        names = read_sheet_names(source)
        names.append("not original")
        assert read_sheet_names(source) == ["First"]
        assert len(calls) == 1
        pd.DataFrame([[1]]).to_excel(source, sheet_name="Changed", index=False)
        assert read_sheet_names(source) == ["Changed"]
    assert len(calls) == 2
