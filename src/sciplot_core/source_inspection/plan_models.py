"""Define the internal recommendation plan selected from recognized evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecommendationPlan:
    template: str
    score: float
    reason: str
    overrides: dict[str, Any]
    signals: tuple[str, ...]
    alternatives: tuple[tuple[str, float, str], ...] = ()
    warnings: tuple[str, ...] = ()
    confidence: float | None = None


__all__ = ["RecommendationPlan"]
