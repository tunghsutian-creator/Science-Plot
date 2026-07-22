from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("SCIPLOT_REPO") or PACKAGE_ROOT.parents[1]).expanduser().resolve()
VENDORED_CORE_ROOT = PACKAGE_ROOT / "_vendor"
RUNTIME_REPO_ROOT = Path(
    os.environ.get("SCIPLOT_RUNTIME_REPO") or REPO_ROOT
).expanduser().resolve()
VEUSZ_ROOT = Path(
    os.environ.get("SCIPLOT_VEUSZ_ROOT") or RUNTIME_REPO_ROOT / "third_party" / "veusz"
).expanduser().resolve()
VEUSZ_UPSTREAM_COMMIT = "264084b06eb306d860c7757c637f37b78bb2333f"


def local_reference_root(*, repo_root: Path = REPO_ROOT) -> Path:
    configured = os.environ.get("SCIPLOT_REFERENCE_DATA")
    return Path(configured).expanduser().resolve() if configured else repo_root / ".local" / "reference_data"


def real_world_fixture_root(*, repo_root: Path = REPO_ROOT) -> Path:
    tracked = repo_root / "tests" / "fixtures" / "real_world"
    if tracked.exists():
        return tracked
    return local_reference_root(repo_root=repo_root) / "real_world"


def resolve_fixture_path(value: str | Path, *, repo_root: Path = REPO_ROOT) -> Path:
    """Resolve a rule fixture from a full development tree or local-only data store."""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()

    tracked = (repo_root / path).resolve()
    if tracked.exists():
        return tracked

    aliases = {
        Path("tests/fixtures/real_world"): Path("real_world"),
        Path("tests/fixtures/polymer_corpus"): Path("polymer_corpus"),
        Path("tests/fixtures/archived_output_raw_data"): Path("archived_sources"),
    }
    for source_prefix, local_prefix in aliases.items():
        try:
            relative = path.relative_to(source_prefix)
        except ValueError:
            continue
        local = (local_reference_root(repo_root=repo_root) / local_prefix / relative).resolve()
        if local.exists():
            return local
    return tracked


def resolved_path_is_within(path: Path, root: Path) -> bool:
    """Return whether the fully resolved path stays inside the resolved root."""

    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


__all__ = [
    "PACKAGE_ROOT",
    "REPO_ROOT",
    "RUNTIME_REPO_ROOT",
    "VENDORED_CORE_ROOT",
    "VEUSZ_ROOT",
    "VEUSZ_UPSTREAM_COMMIT",
    "local_reference_root",
    "real_world_fixture_root",
    "resolved_path_is_within",
    "resolve_fixture_path",
]
