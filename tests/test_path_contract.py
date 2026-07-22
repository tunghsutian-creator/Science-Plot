from __future__ import annotations

from pathlib import Path

from sciplot_core._paths import resolved_path_is_within


def test_resolved_path_containment_rejects_prefix_and_parent_escapes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    child = root / "nested" / "artifact.json"
    sibling = tmp_path / "project-copy" / "artifact.json"
    child.parent.mkdir(parents=True)
    sibling.parent.mkdir(parents=True)
    child.write_text("{}", encoding="utf-8")
    sibling.write_text("{}", encoding="utf-8")

    assert resolved_path_is_within(child, root)
    assert not resolved_path_is_within(sibling, root)
    assert not resolved_path_is_within(root / ".." / sibling.parent.name, root)


def test_resolved_path_containment_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "artifact.json"
    target.write_text("{}", encoding="utf-8")
    link = root / "external"
    link.symlink_to(outside, target_is_directory=True)

    assert not resolved_path_is_within(link / target.name, root)
