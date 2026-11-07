"""Generated public torque sources and exact numerical CSV observations."""

import pandas as pd

from sciplot_core.foundation.file_hashing import file_sha256
from test_torque_source_contract import _write_torque_source


def _points(path):
    table = pd.read_csv(path, header=None)
    return [
        tuple(
            (float(x), float(y))
            for x, y in table.iloc[3:, index : index + 2]
            .dropna()
            .itertuples(index=False, name=None)
        )
        for index in range(0, table.shape[1], 2)
    ]


def _generated_torque_sources(source):
    source.mkdir()
    responses = [1] * 10 + [50] + [10 + i % 7 for i in range(2600)] + [1] * 20
    original = {}
    for label, unit, offset in (("Cedar", "s", 0), ("Birch", "min", 3)):
        path = source / (label + "_torque.csv")
        points = tuple(
            (index * (60 if unit == "s" else 1), value + offset)
            for index, value in enumerate(responses)
        )
        _write_torque_source(path, points, x_unit=unit)
        original[file_sha256(path)] = (
            path,
            path.read_bytes(),
            tuple(
                (index * 60.0, value + offset) for index, value in enumerate(responses)
            ),
        )
    return original
