from __future__ import annotations

from pathlib import Path

from sciplot_core import ingest
from sciplot_core.foundation.text_decoding import (
    decode_text_file,
    is_clean_utf8,
    smart_decode,
)


def test_ingest_preserves_the_public_decoder_api() -> None:
    assert ingest.smart_decode is smart_decode
    assert ingest.decode_text_file is decode_text_file


def test_smart_decode_preserves_scientific_symbols_in_sparse_cp1252() -> None:
    text, encoding = smart_decode("Temperature,25 °C ± 1\n".encode("cp1252"))

    assert text == "Temperature,25 °C ± 1\n"
    assert encoding == "cp1252"


def test_smart_decode_recognizes_bomless_utf16() -> None:
    text, encoding = smart_decode("温度\t25 °C\n".encode("utf-16-le"))

    assert text == "温度\t25 °C\n"
    assert encoding == "utf-16-le"


def test_decode_text_file_and_utf8_probe_share_the_foundation_contract(
    tmp_path: Path,
) -> None:
    source = tmp_path / "instrument.csv"
    source.write_bytes("Length,10 µm\n".encode("utf-8"))

    assert is_clean_utf8(source.read_bytes()) is True
    assert decode_text_file(source) == "Length,10 µm\n"
    assert is_clean_utf8(b"\xef\xbb\xbfvalue\n") is False
