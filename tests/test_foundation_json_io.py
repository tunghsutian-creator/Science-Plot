"""Shared serialization preserves persisted bytes and atomic failure behavior."""

import pytest

from sciplot_core.foundation import json_io


def test_stream_and_atomic_writes_keep_the_existing_json_bytes(tmp_path):
    payload = {"温度": "µ", "values": [1.2345678901234567, -0.0, True, None]}
    expected = (
        '{\n  "温度": "µ",\n  "values": [\n'
        '    1.2345678901234567,\n    -0.0,\n    true,\n    null\n  ]\n}\n'
    ).encode("utf-8")
    target, stream_target = tmp_path / "atomic.json", tmp_path / "stream.json"
    json_io.atomic_write_json(target, payload)
    with stream_target.open("w", encoding="utf-8") as handle:
        json_io.write_json_object(handle, payload)
    assert target.read_bytes() == stream_target.read_bytes() == expected


@pytest.mark.parametrize("failure", ["nonfinite", "fsync"])
def test_atomic_write_retains_original_bytes_and_cleans_stage_on_failure(tmp_path, monkeypatch, failure):
    target = tmp_path / "saved.json"
    original = b'{"previous": true}\n'
    target.write_bytes(original)
    payload = {"value": float("nan") if failure == "nonfinite" else 1}
    if failure == "fsync":
        def fail_sync(_descriptor):
            raise OSError("injected fsync failure")

        monkeypatch.setattr(json_io.os, "fsync", fail_sync)
    with pytest.raises(ValueError if failure == "nonfinite" else OSError):
        json_io.atomic_write_json(target, payload)
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]
