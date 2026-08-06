"""Stable fail-closed errors for figure-plan resolution."""

from __future__ import annotations


class FigurePlanResolutionError(ValueError):
    """Plan resolution failed with one stable machine-readable reason."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


__all__ = ["FigurePlanResolutionError"]
