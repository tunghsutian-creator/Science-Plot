"""Immutable per-figure execution outcome contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
    require_json_list,
    require_json_object,
)

from sciplot_core.figure_plan.constants import (
    FIGURE_OUTCOME_KIND,
    FIGURE_OUTCOME_VERSION,
)
from sciplot_core.figure_plan.payload_types import (
    FigureOutcomePayload,
    FigureOutcomeStatus,
)
from sciplot_core.figure_plan.values import (
    FIGURE_ID_PATTERN,
    optional_text,
    required_text,
    text_tuple,
)

_OUTCOME_STATUSES = {"pending", "editable", "ready", "unavailable", "failed"}


@dataclass(frozen=True, slots=True)
class FigureOutcome:
    """The execution result for exactly one selected FigureTask."""

    figure_id: str
    status: FigureOutcomeStatus
    artifacts: tuple[str, ...] = ()
    reason_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        figure_id = required_text(self.figure_id, label="outcome.figure_id")
        if FIGURE_ID_PATTERN.fullmatch(figure_id) is None:
            raise ValueError("Outcome figure_id is not a valid FigureTask ID.")
        status = required_text(self.status, label="outcome.status")
        if status not in _OUTCOME_STATUSES:
            raise ValueError(f"Unsupported FigureOutcome status: {status!r}")
        artifacts = text_tuple(self.artifacts, label="outcome.artifacts")
        if status == "pending" and artifacts:
            raise ValueError("A pending FigureOutcome cannot bind artifacts.")
        object.__setattr__(self, "figure_id", figure_id)
        object.__setattr__(
            self,
            "status",
            cast(FigureOutcomeStatus, status),
        )
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(
            self,
            "reason_code",
            optional_text(self.reason_code, label="outcome.reason_code"),
        )
        object.__setattr__(
            self,
            "message",
            optional_text(self.message, label="outcome.message"),
        )

    def to_payload(self) -> FigureOutcomePayload:
        return {
            "kind": FIGURE_OUTCOME_KIND,
            "version": FIGURE_OUTCOME_VERSION,
            "figure_id": self.figure_id,
            "status": self.status,
            "artifacts": list(self.artifacts),
            "reason_code": self.reason_code,
            "message": self.message,
        }

    @property
    def delivery_artifacts_complete(self) -> bool:
        """Require exactly one editable VSZ plus the standard PDF/TIFF pair."""

        vsz_paths = {
            path for path in self.artifacts if Path(path).suffix.casefold() == ".vsz"
        }
        pdf_paths = {
            path for path in self.artifacts if Path(path).suffix.casefold() == ".pdf"
        }
        tiff_paths = {
            path
            for path in self.artifacts
            if Path(path).name.casefold().endswith("_300dpi.tiff")
        }
        return len(vsz_paths) == 1 and len(pdf_paths) == 1 and len(tiff_paths) == 1

    @classmethod
    def from_payload(cls, value: object) -> FigureOutcome:
        payload = require_json_object(value, label="FigureOutcome")
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "figure_id",
                "status",
                "artifacts",
                "reason_code",
                "message",
            },
            label="FigureOutcome",
        )
        if payload.get("kind") != FIGURE_OUTCOME_KIND:
            raise ValueError("Not a SciPlot FigureOutcome payload.")
        if (
            require_json_int(payload.get("version"), label="FigureOutcome.version")
            != FIGURE_OUTCOME_VERSION
        ):
            raise ValueError("Unsupported FigureOutcome version.")
        return cls(
            figure_id=required_text(
                payload.get("figure_id"),
                label="FigureOutcome.figure_id",
            ),
            status=cast(
                FigureOutcomeStatus,
                required_text(
                    payload.get("status"),
                    label="FigureOutcome.status",
                ),
            ),
            artifacts=text_tuple(
                require_json_list(
                    payload.get("artifacts"),
                    label="FigureOutcome.artifacts",
                ),
                label="FigureOutcome.artifacts",
            ),
            reason_code=optional_text(
                payload.get("reason_code"),
                label="FigureOutcome.reason_code",
            ),
            message=optional_text(
                payload.get("message"),
                label="FigureOutcome.message",
            ),
        )


__all__ = ["FigureOutcome", "FigureOutcomeStatus"]
