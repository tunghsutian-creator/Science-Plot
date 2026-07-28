"""Define validated native inspector field specifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INSPECTOR_EDITORS = {
    "boolean",
    "choice",
    "color",
    "dataset",
    "distance",
    "float_list",
    "integer",
    "number",
    "number_or_auto",
    "read_only",
    "scalar_list",
    "text",
}


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class InspectorFieldSpec:
    field_id: str
    section: str
    label: str
    suffix: str
    editor: str
    immediate: bool = False
    read_only: bool = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    decimals: int = 4
    help_text: str = ""

    def __post_init__(self) -> None:
        _required_text(self.field_id, "field_id")
        _required_text(self.section, "section")
        _required_text(self.label, "label")
        _required_text(self.suffix, "suffix")
        if self.editor not in INSPECTOR_EDITORS:
            raise ValueError(f"Unsupported inspector editor: {self.editor!r}")
        if self.editor in {"dataset", "read_only"} and not self.read_only:
            raise ValueError(f"{self.editor} fields must be read-only.")
        if self.read_only and self.immediate:
            raise ValueError("Read-only inspector fields cannot be immediate.")
        if self.minimum is not None and self.maximum is not None:
            if float(self.minimum) > float(self.maximum):
                raise ValueError("Inspector field minimum cannot exceed maximum.")
        if not 0 <= self.decimals <= 12:
            raise ValueError("Inspector field decimals must be between 0 and 12.")


def _field(
    field_id: str,
    section: str,
    label: str,
    suffix: str,
    editor: str,
    *,
    immediate: bool = False,
    read_only: bool = False,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
    step: float | int | None = None,
    decimals: int = 4,
    help_text: str = "",
) -> InspectorFieldSpec:
    return InspectorFieldSpec(
        field_id=field_id,
        section=section,
        label=label,
        suffix=suffix,
        editor=editor,
        immediate=immediate,
        read_only=read_only,
        minimum=minimum,
        maximum=maximum,
        step=step,
        decimals=decimals,
        help_text=help_text,
    )


COMMON_VISIBILITY = _field(
    "hidden",
    "Object",
    "Hidden",
    "hide",
    "boolean",
    immediate=True,
    help_text="Hide this object without deleting it.",
)
