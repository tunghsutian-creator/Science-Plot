"""Immutable input models accepted by intake project creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IncomingFile:
    name: str
    content: bytes
    source_path: str | None = None


@dataclass(frozen=True)
class IntakeGroupInput:
    sample: str
    files: tuple[IncomingFile, ...]
