"""Negative controls for the finite frozen implementation exception."""

from pathlib import Path
import shutil

import pytest

from immutable_operator_architecture import PREFIX, permitted_pairs, pinned_duplicate_locations


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_copy_rule_allows_only_the_seventeen_exact_pairs():
    permitted = pinned_duplicate_locations(ROOT)
    assert len(permitted) == len(permitted_pairs()) == 17
    pair = next(iter(permitted))
    assert frozenset((*pair, "src/sciplot_core/another.py:1")) not in permitted
    assert frozenset({"src/sciplot_core/new.py:1", "src/sciplot_core/new_copy.py:1"}) not in permitted


def test_even_format_only_retained_file_drift_cannot_inherit_copy_exception(tmp_path):
    for pair in permitted_pairs():
        for item in pair:
            relative = item.rsplit(":", 1)[0]
            target = tmp_path / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
    frozen = tmp_path / PREFIX / "hashing.py"
    frozen.write_bytes(frozen.read_bytes() + b"\n")
    with pytest.raises(AssertionError, match="Retained scientific version bytes changed"):
        pinned_duplicate_locations(tmp_path)
