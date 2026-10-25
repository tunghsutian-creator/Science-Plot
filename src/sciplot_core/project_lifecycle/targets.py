"""Closed target variants supplied by the composition adapter, never path guesses."""
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True)
class StoredTarget:
    root: Path


@dataclass(frozen=True)
class ImportTarget:
    root: Path
    project: Path
    figure_id: str
    plot_id: str | None = None


@dataclass(frozen=True)
class ManagedDeliveryTarget:
    root: Path
    item_id: str
    native_snapshot: str


OpenTarget = StoredTarget | ImportTarget | ManagedDeliveryTarget


class DecisionKind(StrEnum):
    SEMANTIC = "semantic"
    CREATION = "creation"


@dataclass(frozen=True)
class DecisionTarget:
    root: Path
    kind: DecisionKind


@dataclass(frozen=True)
class ManagedCreationLocation:
    root: Path
    output: Path
    plot_id: str
