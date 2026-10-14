from __future__ import annotations

import pytest

from sciplot_core.delivery.install import install_new_delivery


@pytest.mark.parametrize("existing", ["empty", "nonempty", "symlink"])
def test_exclusive_install_never_replaces_existing_destination(tmp_path, existing):
    candidate, delivery = tmp_path / "candidate", tmp_path / "delivery"
    candidate.mkdir()
    (candidate / "new").write_text("new")
    if existing == "symlink":
        real = tmp_path / "real"
        real.mkdir()
        delivery.symlink_to(real)
    else:
        delivery.mkdir()
        if existing == "nonempty":
            (delivery / "old").write_text("old")
    with pytest.raises((OSError, ValueError)):
        install_new_delivery(candidate, delivery)
    assert (candidate / "new").read_text() == "new"
    assert delivery.exists()
    if existing == "nonempty":
        assert (delivery / "old").read_text() == "old"


def test_exclusive_install_moves_one_complete_directory(tmp_path):
    candidate, delivery = tmp_path / "candidate", tmp_path / "delivery"
    candidate.mkdir()
    (candidate / "artifact").write_text("sealed")
    install_new_delivery(candidate, delivery)
    assert not candidate.exists()
    assert (delivery / "artifact").read_text() == "sealed"
