"""Bound file snapshots and reversible publication for rheology presentation edits."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.source_update_commit import reject_symlink_path


def snapshot(paths: list[Path]) -> dict[str, str]:
    result = {}
    for path in paths:
        reject_symlink_path(path)
        result[str(path.resolve())] = file_sha256(path)
    return result


def check_snapshot(files: dict[str, str], *, label: str) -> None:
    for name, digest in files.items():
        path = Path(name)
        reject_symlink_path(path)
        if not path.is_file() or file_sha256(path) != digest:
            raise ValueError(f"Stale {label}: {path}; inspect a new style preview.")


def publish_files(updates: list[tuple[Path, Path]], backup: Path, *,
                  expected: dict[str, str], candidates: dict[str, str],
                  allowed_roots: tuple[Path, ...]) -> dict[str, str]:
    """Prepare all replacements, retain backups, and roll back interrupted writes."""
    targets = [target.resolve() for _, target in updates]
    if len(set(targets)) != len(targets):
        raise ValueError("Duplicate presentation publication target.")
    if any(not any(target.is_relative_to(root.resolve()) for root in allowed_roots) for target in targets):
        raise ValueError("Presentation publication target lies outside its bound suite.")
    check_snapshot(expected, label="presentation baseline")
    check_snapshot(candidates, label="presentation candidate")
    backup.mkdir(parents=True, exist_ok=False)
    prepared = []
    for index, (source, target) in enumerate(updates):
        reject_symlink_path(source)
        reject_symlink_path(target)
        staged = backup / f"new_{index}"
        previous = backup / f"old_{index}"
        digest = candidates.get(str(source.resolve()))
        if digest is None:
            raise ValueError(f"Unbound presentation candidate: {source}")
        shutil.copy2(source, staged)
        if file_sha256(source) != digest or file_sha256(staged) != digest:
            raise ValueError(f"Presentation candidate changed during staging: {source}")
        existed = target.exists()
        if existed:
            if str(target.resolve()) not in expected:
                raise ValueError(f"Unbound existing publication target: {target}")
            shutil.copy2(target, previous)
        prepared.append((staged, target, previous, existed, digest))
    check_snapshot(expected, label="presentation baseline")
    check_snapshot(candidates, label="presentation candidate")
    journal = [{"target": str(target), "backup": str(previous) if existed else None}
               for _, target, previous, existed, _ in prepared]
    (backup / "journal.json").write_text(json.dumps(journal, indent=2), encoding="utf-8")
    applied = []
    try:
        for staged, target, previous, existed, digest in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            applied.append((target, previous, existed))
            if file_sha256(target) != digest:
                raise ValueError(f"Published presentation bytes differ from reviewed candidate: {target}")
        check_snapshot(candidates, label="presentation candidate")
        check_snapshot({p: h for p, h in expected.items() if Path(p).resolve() not in targets},
                       label="unchanged presentation dependency")
    except BaseException:
        for target, previous, existed in reversed(applied):
            if existed:
                shutil.copy2(previous, target)
            else:
                target.unlink(missing_ok=True)
        raise
    return snapshot(targets)
