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
                f"Managed output entries must be unique top-level names: {raw_value!r}."
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


def _existing_entries(output_dir: Path, names: Sequence[str]) -> list[Path]:
    return [path for name in names if (path := output_dir / name).exists() or path.is_symlink()]


def require_clear_managed_output(output_dir: Path, managed_names: Sequence[str]) -> None:
    """Names identify what the runner will write, not who owns existing bytes."""
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError(f"Choose a real output directory: {output_dir}.")
    conflicts = _existing_entries(output_dir, managed_names)
    if conflicts:
        raise ValueError(
            "Output already contains unverified files; nothing was replaced: "
            + ", ".join(str(path) for path in conflicts)
            + ". Choose a new output directory."
        )


@contextmanager
def managed_output_transaction(
    output_dir: Path,
    *,
    managed_names: Sequence[str],
    private: bool = False,
) -> Iterator[None]:
    """Preserve unowned outputs; private images can regenerate owned entries."""

    names = _managed_names(managed_names)
    if not private:
        require_clear_managed_output(output_dir, names)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = _existing_entries(output_dir, names) if private else []
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
