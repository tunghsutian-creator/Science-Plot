"""Data model for source-controlled changed-owner mappings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChangedOwner:
    """Map one production owner to its focused and deferred gates."""

    owner_id: str
    pytest_targets: tuple[str, ...]
    exact_paths: frozenset[str] = frozenset()
    path_prefixes: tuple[str, ...] = ()
    owned_test_paths: frozenset[str] = frozenset()
    mypy_required: bool = False
    handoff_gates: tuple[str, ...] = ()
    final_milestone_gates: tuple[str, ...] = ()
    release_gates: tuple[str, ...] = ()

    def matches(self, path: str) -> bool:
        return (
            path in self.exact_paths
            or path in self.owned_test_paths
            or path.startswith(self.path_prefixes)
        )
