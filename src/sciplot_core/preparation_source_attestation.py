"""Attest the exact source snapshot consumed by semantic preparation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS


_HASH = re.compile(r"[0-9a-f]{64}")
_SOURCE_CHANGED = "semantic_preparation_source_changed"
_CONTRACT_MISMATCH = "semantic_preparation_attestation_mismatch"
SOURCE_ATTESTED_RULE_IDS = MECHANICAL_RULE_IDS | frozenset(
    {"dma_temperature_sweep", "rheology_temperature_sweep"}
)


def requires_preparation_source_attestation(rule_id: object) -> bool:
    """Return whether one canonical rule uses the preparation attestation seam."""

    return isinstance(rule_id, str) and rule_id in SOURCE_ATTESTED_RULE_IDS


class PreparationSourceAttestationError(ValueError):
    """Stable fail-closed error for a preparation source snapshot."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def _fail(reason_code: str, message: str) -> NoReturn:
    raise PreparationSourceAttestationError(reason_code, message)


@dataclass(frozen=True, slots=True)
class AttestedSourceFile:
    """One canonical file path and its preparation-time content hash."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        path = Path(self.path).expanduser()
        if (
            not self.path
            or not path.is_absolute()
            or str(path.resolve()) != self.path
            or _HASH.fullmatch(self.sha256) is None
        ):
            _fail(_CONTRACT_MISMATCH, "Attested source file identity is invalid.")

    @classmethod
    def capture(cls, path: Path) -> AttestedSourceFile:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            _fail(
                _CONTRACT_MISMATCH,
                f"Preparation-selected source is not a file: {resolved}",
            )
        return cls(path=str(resolved), sha256=file_sha256(resolved))

    def verify_current(self, *, label: str) -> None:
        path = Path(self.path)
        if not path.is_file() or file_sha256(path) != self.sha256:
            _fail(_SOURCE_CHANGED, f"{label} changed after semantic preparation.")

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class PreparationSourceAttestation:
    """Immutable bridge from one semantic preparation to terminal adapters."""

    rule_id: str
    source_root: str
    source_tree_sha256_before: str
    source_tree_sha256_after: str
    selected_sources: tuple[AttestedSourceFile, ...]
    prepared_source: AttestedSourceFile

    def __post_init__(self) -> None:
        root = Path(self.source_root).expanduser()
        if (
            not self.rule_id
            or self.rule_id.strip() != self.rule_id
            or not root.is_absolute()
            or str(root.resolve()) != self.source_root
            or _HASH.fullmatch(self.source_tree_sha256_before) is None
            or _HASH.fullmatch(self.source_tree_sha256_after) is None
            or self.source_tree_sha256_before != self.source_tree_sha256_after
            or not self.selected_sources
            or not all(
                isinstance(item, AttestedSourceFile) for item in self.selected_sources
            )
            or len({item.path for item in self.selected_sources})
            != len(self.selected_sources)
            or not isinstance(self.prepared_source, AttestedSourceFile)
        ):
            _fail(_CONTRACT_MISMATCH, "Preparation source attestation is invalid.")

    @classmethod
    def capture(
        cls,
        *,
        rule_id: str,
        source_root: Path,
        source_tree_sha256_before: str,
        selected_sources: tuple[Path, ...],
        prepared_source: Path,
    ) -> PreparationSourceAttestation:
        root = source_root.expanduser().resolve()
        tree_hash_after = source_tree_sha256(root)
        if (
            _HASH.fullmatch(source_tree_sha256_before) is None
            or tree_hash_after is None
            or source_tree_sha256_before != tree_hash_after
        ):
            _fail(
                _SOURCE_CHANGED,
                "Source tree changed while semantic preparation was running.",
            )
        unique_sources = tuple(
            dict.fromkeys(path.expanduser().resolve() for path in selected_sources)
        )
        if (
            root.is_file()
            and unique_sources != (root,)
            or root.is_dir()
            and any(not path.is_relative_to(root) for path in unique_sources)
        ):
            _fail(
                _CONTRACT_MISMATCH,
                "Preparation-selected sources escaped their attested source root.",
            )
        binding = cls(
            rule_id=rule_id,
            source_root=str(root),
            source_tree_sha256_before=source_tree_sha256_before,
            source_tree_sha256_after=tree_hash_after,
            selected_sources=tuple(
                AttestedSourceFile.capture(path) for path in unique_sources
            ),
            prepared_source=AttestedSourceFile.capture(prepared_source),
        )
        return binding

    def verify_current(
        self,
        *,
        source_root: Path | None = None,
        prepared_source: Path | None = None,
    ) -> None:
        root = Path(self.source_root)
        if source_root is not None and source_root.expanduser().resolve() != root:
            _fail(_CONTRACT_MISMATCH, "Preparation source root identity diverged.")
        prepared = Path(self.prepared_source.path)
        if (
            prepared_source is not None
            and prepared_source.expanduser().resolve() != prepared
        ):
            _fail(_CONTRACT_MISMATCH, "Prepared workbook identity diverged.")
        if source_tree_sha256(root) != self.source_tree_sha256_after:
            _fail(_SOURCE_CHANGED, "Source tree changed after semantic preparation.")
        for index, item in enumerate(self.selected_sources, start=1):
            item.verify_current(label=f"Preparation-selected source {index}")
        self.prepared_source.verify_current(label="Prepared workbook")

    def to_payload(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "source_root": self.source_root,
            "source_tree_sha256_before": self.source_tree_sha256_before,
            "source_tree_sha256_after": self.source_tree_sha256_after,
            "selected_sources": [item.to_payload() for item in self.selected_sources],
            "prepared_source": self.prepared_source.to_payload(),
        }


__all__ = [
    "AttestedSourceFile",
    "PreparationSourceAttestation",
    "PreparationSourceAttestationError",
    "SOURCE_ATTESTED_RULE_IDS",
    "requires_preparation_source_attestation",
]
