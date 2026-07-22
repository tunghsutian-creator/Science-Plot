from __future__ import annotations

import shutil
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def _managed_names(values: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        name = str(raw_value).strip()
        path = Path(name)
        if not name or path.is_absolute() or path.name != name or name in {".", ".."}:
            raise ValueError(
                "Managed output entries must be unique top-level names: "
                f"{raw_value!r}."
            )
        if name in seen:
            raise ValueError(f"Duplicate managed output entry: {name}")
        seen.add(name)
        names.append(name)
    return tuple(names)


def _remove_artifact(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


@contextmanager
def managed_output_transaction(
    output_dir: Path,
    *,
    managed_names: Sequence[str],
) -> Iterator[None]:
    """Replace generator-owned top-level artifacts without losing the last run.

    For an existing output directory, named entries move to a sibling backup
    before generation.  A failed replacement removes only newly generated
    named entries and restores the prior bytes.  Unrelated user files remain
    in place.  New output directories intentionally retain partial diagnostics
    after failure.
    """

    names = _managed_names(managed_names)
    output_preexisted = output_dir.exists()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_preexisted:
        yield
        return

    existing = [
        output_dir / name
        for name in names
        if (output_dir / name).exists() or (output_dir / name).is_symlink()
    ]
    if not existing:
        yield
        return

    backup_dir = output_dir.parent / (
        f".{output_dir.name}.sciplot-managed-backup-{uuid4().hex}"
    )
    backup_dir.mkdir(parents=False, exist_ok=False)
    moved: list[str] = []
    try:
        for source in existing:
            source.replace(backup_dir / source.name)
            moved.append(source.name)
    except BaseException:
        for name in reversed(moved):
            (backup_dir / name).replace(output_dir / name)
        shutil.rmtree(backup_dir)
        raise

    try:
        yield
    except BaseException:
        for name in names:
            _remove_artifact(output_dir / name)
        for name in moved:
            (backup_dir / name).replace(output_dir / name)
        shutil.rmtree(backup_dir)
        raise
    else:
        shutil.rmtree(backup_dir)


__all__ = ["managed_output_transaction"]
