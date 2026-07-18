from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from sciplot_core.canvas._validation import (
    reject_unknown_keys,
    require_json_int,
    require_json_list,
    require_json_number,
    require_json_object,
)
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch

COMPOSITE_LAYOUT_KIND = "sciplot_composite_layout"
COMPOSITE_LAYOUT_VERSION = 1
COMPOSITION_PROJECT_KIND = "sciplot_composition_project"
COMPOSITION_PROJECT_VERSION = 1
COMPOSITE_CANVAS_WIDTH_MM = 183.0
COMPOSITE_NOMINAL_CONTENT_WIDTH_MM = 180.0
DEFAULT_COMPOSITION_HEIGHT_MM = 55.0
MIN_COMPOSITION_HEIGHT_MM = 20.0
MAX_COMPOSITION_HEIGHT_MM = 170.0

COMPOSITION_VARIANT_STATES = {
    "draft",
    "compiled",
    "edited",
    "ready",
    "conflict",
    "needs_human_confirmation",
    "needs_rule_repair",
}
COMPOSITION_LEGEND_POLICIES = {
    "auto",
    "shared_when_equivalent",
    "per_panel",
}

_SAFE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LAYOUTS: dict[str, dict[str, Any]] = {
    "single_180": {
        "label": "Single 180 mm panel",
        "panel_widths_mm": (180.0,),
        "gaps_mm": (),
        "outer_left_mm": 1.5,
        "outer_right_mm": 1.5,
    },
    "double_equal_90": {
        "label": "Two equal 90 mm panels",
        "panel_widths_mm": (90.0, 90.0),
        "gaps_mm": (3.0,),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
    "double_120_60": {
        "label": "120 mm primary plus 60 mm supporting panel",
        "panel_widths_mm": (120.0, 60.0),
        "gaps_mm": (3.0,),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
    "double_60_120": {
        "label": "60 mm supporting plus 120 mm primary panel",
        "panel_widths_mm": (60.0, 120.0),
        "gaps_mm": (3.0,),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
    "triple_equal_60": {
        "label": "Three equal 60 mm panels",
        "panel_widths_mm": (60.0, 60.0, 60.0),
        "gaps_mm": (1.5, 1.5),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
}

_AUTHORITY_POLICY = {
    "source_vsz_snapshots_are_immutable": True,
    "composition_variants_are_independent": True,
    "compiled_vsz_is_visual_authority_after_manual_save": True,
    "regeneration_must_archive_current_compiled_vsz": True,
    "arbitrary_vsz_text_rewriting_allowed": False,
}
_RENDERER_CONTRACT = {
    "engine": "veusz",
    "document_shape": "one_page_grid_native_graphs",
    "raster_panel_composition_allowed": False,
    "preview_rasters_are_non_authoritative": True,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _required_text(value: object, label: str, *, maximum: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters.")
    return text


def _safe_id(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64)
    if _SAFE_ID.fullmatch(text) is None:
        raise ValueError(
            f"{label} must start with a letter and contain only letters, "
            "numbers, underscores, or hyphens."
        )
    return text


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def _relative_ref(value: object, label: str, *, suffix: str | None = None) -> str:
    text = _required_text(value, label, maximum=512).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a safe project-relative path.")
    if suffix is not None and path.suffix.casefold() != suffix.casefold():
        raise ValueError(f"{label} must end with {suffix}.")
    return path.as_posix()


def _optional_ref(
    value: object,
    label: str,
    *,
    suffix: str | None = None,
) -> str | None:
    if value is None:
        return None
    return _relative_ref(value, label, suffix=suffix)


def _layout_total(spec: dict[str, Any]) -> float:
    return (
        float(spec["outer_left_mm"])
        + sum(float(value) for value in spec["panel_widths_mm"])
        + sum(float(value) for value in spec["gaps_mm"])
        + float(spec["outer_right_mm"])
    )


@dataclass(frozen=True)
class CompositionSlot:
    slot_id: str
    order: int
    panel_label: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        _safe_id(self.slot_id, "slot_id")
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise ValueError("Composition slot order must be an integer.")
        if self.order < 1:
            raise ValueError("Composition slot order must be positive.")
        label = _required_text(self.panel_label, "panel_label", maximum=8)
        if label != label.casefold() or not label.isalpha():
            raise ValueError("Panel labels must be lowercase alphabetic text.")
        for name, value in (
            ("x_mm", self.x_mm),
            ("y_mm", self.y_mm),
            ("width_mm", self.width_mm),
            ("height_mm", self.height_mm),
        ):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"Composition slot {name} must be numeric.")
            if not math.isfinite(float(value)):
                raise ValueError(f"Composition slot {name} must be finite.")
        if self.x_mm < 0 or self.y_mm < 0:
            raise ValueError("Composition slot coordinates must be non-negative.")
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("Composition slot dimensions must be positive.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.slot_id,
            "order": self.order,
            "panel_label": self.panel_label,
            "x_mm": _rounded(self.x_mm),
            "y_mm": _rounded(self.y_mm),
            "width_mm": _rounded(self.width_mm),
            "height_mm": _rounded(self.height_mm),
            "x_fraction": _rounded(self.x_mm / COMPOSITE_CANVAS_WIDTH_MM),
            "width_fraction": _rounded(self.width_mm / COMPOSITE_CANVAS_WIDTH_MM),
        }


@dataclass(frozen=True)
class CompositionLayout:
    layout_id: str
    label: str
    canvas_height_mm: float
    panel_widths_mm: tuple[float, ...]
    gaps_mm: tuple[float, ...]
    outer_left_mm: float
    outer_right_mm: float
    slots: tuple[CompositionSlot, ...]

    def __post_init__(self) -> None:
        if self.layout_id not in _LAYOUTS:
            raise ValueError(f"Unknown composition layout: {self.layout_id!r}")
        _required_text(self.label, "composition layout label", maximum=160)
        height = float(self.canvas_height_mm)
        if not math.isfinite(height) or not (
            MIN_COMPOSITION_HEIGHT_MM <= height <= MAX_COMPOSITION_HEIGHT_MM
        ):
            raise ValueError(
                "Composition height must be between "
                f"{MIN_COMPOSITION_HEIGHT_MM:g} and {MAX_COMPOSITION_HEIGHT_MM:g} mm."
            )
        if not self.slots:
            raise ValueError("Composition layouts require at least one slot.")
        if len(self.gaps_mm) != len(self.slots) - 1:
            raise ValueError("Composition gaps must separate every adjacent slot.")
        if len(self.panel_widths_mm) != len(self.slots):
            raise ValueError("Composition panel widths must match the slots.")
        if [slot.order for slot in self.slots] != list(range(1, len(self.slots) + 1)):
            raise ValueError("Composition slot order must be contiguous.")
        if len({slot.slot_id for slot in self.slots}) != len(self.slots):
            raise ValueError("Composition slot ids must be unique.")
        if len({slot.panel_label for slot in self.slots}) != len(self.slots):
            raise ValueError("Composition panel labels must be unique.")
        cursor = float(self.outer_left_mm)
        for index, slot in enumerate(self.slots):
            if not math.isclose(slot.x_mm, cursor, abs_tol=1e-6):
                raise ValueError("Composition slots must close without hidden offsets.")
            if not math.isclose(
                slot.width_mm,
                self.panel_widths_mm[index],
                abs_tol=1e-6,
            ):
                raise ValueError("Composition slot width disagrees with its layout.")
            if not math.isclose(slot.height_mm, height, abs_tol=1e-6):
                raise ValueError("Composition slot height disagrees with the canvas.")
            cursor += float(slot.width_mm)
            if index < len(self.gaps_mm):
                cursor += float(self.gaps_mm[index])
        cursor += float(self.outer_right_mm)
        if not math.isclose(cursor, COMPOSITE_CANVAS_WIDTH_MM, abs_tol=1e-6):
            raise ValueError(
                f"Composition geometry closes to {cursor:g} mm, not 183 mm."
            )

    @property
    def slot_ids(self) -> tuple[str, ...]:
        return tuple(slot.slot_id for slot in self.slots)

    def slot(self, slot_id: str) -> CompositionSlot:
        match = next((slot for slot in self.slots if slot.slot_id == slot_id), None)
        if match is None:
            raise ValueError(f"Unknown composition slot: {slot_id!r}")
        return match

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": COMPOSITE_LAYOUT_KIND,
            "version": COMPOSITE_LAYOUT_VERSION,
            "id": self.layout_id,
            "label": self.label,
            "authority": "sciplot_composite_layout_definition",
            "canvas_width_mm": COMPOSITE_CANVAS_WIDTH_MM,
            "canvas_height_mm": _rounded(self.canvas_height_mm),
            "nominal_content_width_mm": COMPOSITE_NOMINAL_CONTENT_WIDTH_MM,
            "spare_width_mm": _rounded(
                COMPOSITE_CANVAS_WIDTH_MM - COMPOSITE_NOMINAL_CONTENT_WIDTH_MM
            ),
            "panel_widths_mm": [float(value) for value in self.panel_widths_mm],
            "gaps_mm": [float(value) for value in self.gaps_mm],
            "outer_left_mm": float(self.outer_left_mm),
            "outer_right_mm": float(self.outer_right_mm),
            "geometry_total_mm": COMPOSITE_CANVAS_WIDTH_MM,
            "slots": [slot.to_dict() for slot in self.slots],
            "renderer_contract": {
                "engine": "veusz",
                "future_widget_tree": "page/grid/native_graphs",
                "raster_panel_composition_allowed": False,
                "grid_outer_margins_must_be_explicit": True,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompositionLayout:
        value = require_json_object(payload, label="CompositionLayout")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "id",
                "label",
                "authority",
                "canvas_width_mm",
                "canvas_height_mm",
                "nominal_content_width_mm",
                "spare_width_mm",
                "panel_widths_mm",
                "gaps_mm",
                "outer_left_mm",
                "outer_right_mm",
                "geometry_total_mm",
                "slots",
                "renderer_contract",
            },
            label="CompositionLayout",
        )
        if value.get("kind") != COMPOSITE_LAYOUT_KIND:
            raise ValueError("Not a SciPlot composition layout.")
        version = require_json_int(value.get("version", 0), label="layout version")
        if version != COMPOSITE_LAYOUT_VERSION:
            raise ValueError(f"Unsupported composition layout version: {version}")
        layout_id = _required_text(value.get("id"), "layout id", maximum=64)
        height = require_json_number(
            value.get("canvas_height_mm"),
            label="canvas_height_mm",
        )
        canonical = composition_layout(layout_id, canvas_height_mm=height)
        if value != canonical.to_dict():
            raise ValueError(
                "Persisted composition layout does not match the exact SciPlot contract."
            )
        return canonical


def composition_layout(
    layout_id: str,
    *,
    canvas_height_mm: float = DEFAULT_COMPOSITION_HEIGHT_MM,
) -> CompositionLayout:
    if layout_id not in _LAYOUTS:
        known = ", ".join(sorted(_LAYOUTS))
        raise ValueError(f"Unknown composite layout `{layout_id}`. Available: {known}.")
    height = float(canvas_height_mm)
    if not math.isfinite(height) or not (
        MIN_COMPOSITION_HEIGHT_MM <= height <= MAX_COMPOSITION_HEIGHT_MM
    ):
        raise ValueError(
            "Composite canvas height must be a finite value between "
            f"{MIN_COMPOSITION_HEIGHT_MM:g} and {MAX_COMPOSITION_HEIGHT_MM:g} mm."
        )
    spec = _LAYOUTS[layout_id]
    total = _layout_total(spec)
    if not math.isclose(total, COMPOSITE_CANVAS_WIDTH_MM, abs_tol=1e-9):
        raise RuntimeError(
            f"Composite layout `{layout_id}` closes to {total} mm, not 183 mm."
        )
    cursor = float(spec["outer_left_mm"])
    slots: list[CompositionSlot] = []
    for index, width in enumerate(spec["panel_widths_mm"]):
        slots.append(
            CompositionSlot(
                slot_id=f"panel_{chr(ord('a') + index)}",
                order=index + 1,
                panel_label=chr(ord("a") + index),
                x_mm=_rounded(cursor),
                y_mm=0.0,
                width_mm=float(width),
                height_mm=height,
            )
        )
        cursor += float(width)
        if index < len(spec["gaps_mm"]):
            cursor += float(spec["gaps_mm"][index])
    return CompositionLayout(
        layout_id=layout_id,
        label=str(spec["label"]),
        canvas_height_mm=height,
        panel_widths_mm=tuple(float(value) for value in spec["panel_widths_mm"]),
        gaps_mm=tuple(float(value) for value in spec["gaps_mm"]),
        outer_left_mm=float(spec["outer_left_mm"]),
        outer_right_mm=float(spec["outer_right_mm"]),
        slots=tuple(slots),
    )


def build_composite_layout(
    layout_id: str,
    *,
    canvas_height_mm: float = DEFAULT_COMPOSITION_HEIGHT_MM,
) -> dict[str, Any]:
    return composition_layout(
        layout_id,
        canvas_height_mm=canvas_height_mm,
    ).to_dict()


def list_composite_layouts() -> list[dict[str, Any]]:
    return [build_composite_layout(layout_id) for layout_id in _LAYOUTS]


def composite_layout_ids() -> tuple[str, ...]:
    return tuple(_LAYOUTS)


def default_layout_for_module_count(module_count: int) -> str:
    defaults = {
        1: "single_180",
        2: "double_equal_90",
        3: "triple_equal_60",
    }
    try:
        return defaults[module_count]
    except KeyError as exc:
        raise ValueError(
            "M4 composition currently supports one to three modules."
        ) from exc


@dataclass(frozen=True)
class CompositionSourceModule:
    module_id: str
    title: str
    source_ref: str
    source_sha256: str
    source_graph_path: str | None = None
    source_page_index: int | None = None

    def __post_init__(self) -> None:
        _safe_id(self.module_id, "module_id")
        _required_text(self.title, "module title", maximum=160)
        _relative_ref(self.source_ref, "source_ref", suffix=".vsz")
        _sha256(self.source_sha256, "source_sha256")
        if self.source_graph_path is not None:
            graph_path = _required_text(
                self.source_graph_path,
                "source_graph_path",
                maximum=512,
            )
            if (
                not graph_path.startswith("/")
                or ".." in PurePosixPath(graph_path).parts
            ):
                raise ValueError("source_graph_path must be an absolute Veusz path.")
        if self.source_page_index is not None:
            if isinstance(self.source_page_index, bool) or not isinstance(
                self.source_page_index,
                int,
            ):
                raise ValueError("source_page_index must be an integer.")
            if self.source_page_index < 0:
                raise ValueError("source_page_index must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "title": self.title,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "source_graph_path": self.source_graph_path,
            "source_page_index": self.source_page_index,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompositionSourceModule:
        value = require_json_object(payload, label="CompositionSourceModule")
        reject_unknown_keys(
            value,
            {
                "module_id",
                "title",
                "source_ref",
                "source_sha256",
                "source_graph_path",
                "source_page_index",
            },
            label="CompositionSourceModule",
        )
        page_index = value.get("source_page_index")
        if page_index is not None:
            page_index = require_json_int(page_index, label="source_page_index")
        return cls(
            module_id=_safe_id(value.get("module_id"), "module_id"),
            title=_required_text(value.get("title"), "module title", maximum=160),
            source_ref=_relative_ref(
                value.get("source_ref"),
                "source_ref",
                suffix=".vsz",
            ),
            source_sha256=_sha256(value.get("source_sha256"), "source_sha256"),
            source_graph_path=(
                _required_text(
                    value.get("source_graph_path"),
                    "source_graph_path",
                    maximum=512,
                )
                if value.get("source_graph_path") is not None
                else None
            ),
            source_page_index=page_index,
        )


@dataclass(frozen=True)
class CompositionPlacement:
    module_id: str
    slot_ref: str | None

    def __post_init__(self) -> None:
        _safe_id(self.module_id, "placement module_id")
        if self.slot_ref is not None:
            _safe_id(self.slot_ref, "placement slot_ref")

    def to_dict(self) -> dict[str, Any]:
        return {"module_id": self.module_id, "slot_ref": self.slot_ref}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompositionPlacement:
        value = require_json_object(payload, label="CompositionPlacement")
        reject_unknown_keys(
            value,
            {"module_id", "slot_ref"},
            label="CompositionPlacement",
        )
        return cls(
            module_id=_safe_id(value.get("module_id"), "placement module_id"),
            slot_ref=(
                _safe_id(value.get("slot_ref"), "placement slot_ref")
                if value.get("slot_ref") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class CompositionVariant:
    variant_id: str
    name: str
    layout: CompositionLayout
    placements: tuple[CompositionPlacement, ...]
    revision: int = 0
    state: str = "draft"
    legend_policy: str = "auto"
    selected_module_id: str | None = None
    compiled_document_ref: str | None = None
    compiled_document_sha256: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _safe_id(self.variant_id, "variant_id")
        _required_text(self.name, "variant name", maximum=160)
        if not isinstance(self.layout, CompositionLayout):
            raise ValueError("CompositionVariant layout must be a CompositionLayout.")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise ValueError("Composition variant revision must be an integer.")
        if self.revision < 0:
            raise ValueError("Composition variant revision must be non-negative.")
        if self.state not in COMPOSITION_VARIANT_STATES:
            raise ValueError(f"Unsupported composition variant state: {self.state!r}")
        if self.legend_policy not in COMPOSITION_LEGEND_POLICIES:
            raise ValueError(f"Unsupported legend policy: {self.legend_policy!r}")
        if not self.placements:
            raise ValueError("Composition variants require source-module placements.")
        module_ids = [placement.module_id for placement in self.placements]
        if len(set(module_ids)) != len(module_ids):
            raise ValueError("Composition placement module ids must be unique.")
        assigned_slots = [
            placement.slot_ref
            for placement in self.placements
            if placement.slot_ref is not None
        ]
        if len(set(assigned_slots)) != len(assigned_slots):
            raise ValueError("A composition slot cannot contain multiple modules.")
        unknown_slots = set(assigned_slots) - set(self.layout.slot_ids)
        if unknown_slots:
            raise ValueError(
                f"Composition placements reference unknown slots: {sorted(unknown_slots)!r}"
            )
        if self.selected_module_id is not None:
            _safe_id(self.selected_module_id, "selected_module_id")
            if self.selected_module_id not in module_ids:
                raise ValueError("Selected composition module is not in the variant.")
        document_ref = _optional_ref(
            self.compiled_document_ref,
            "compiled_document_ref",
            suffix=".vsz",
        )
        document_hash = (
            _sha256(self.compiled_document_sha256, "compiled_document_sha256")
            if self.compiled_document_sha256 is not None
            else None
        )
        if (document_ref is None) != (document_hash is None):
            raise ValueError(
                "Compiled document reference and SHA-256 must appear together."
            )
        if self.state in {"compiled", "edited", "ready"}:
            if document_ref is None or not self.ready_to_compile:
                raise ValueError(
                    "Compiled composition states require a complete layout and document authority."
                )
        elif document_ref is not None:
            raise ValueError(
                "Only compiled, edited, or ready variants may carry a compiled document."
            )
        _required_text(self.created_at, "variant created_at", maximum=80)
        _required_text(self.updated_at, "variant updated_at", maximum=80)

    @property
    def ready_to_compile(self) -> bool:
        assigned = {
            placement.slot_ref
            for placement in self.placements
            if placement.slot_ref is not None
        }
        return assigned == set(self.layout.slot_ids)

    def placement(self, module_id: str) -> CompositionPlacement:
        match = next(
            (
                placement
                for placement in self.placements
                if placement.module_id == module_id
            ),
            None,
        )
        if match is None:
            raise ValueError(f"Unknown composition module: {module_id!r}")
        return match

    def module_for_slot(self, slot_ref: str) -> str | None:
        match = next(
            (
                placement.module_id
                for placement in self.placements
                if placement.slot_ref == slot_ref
            ),
            None,
        )
        return match

    def ordered_module_ids(self) -> tuple[str, ...]:
        slot_order = {
            slot_id: index for index, slot_id in enumerate(self.layout.slot_ids)
        }
        original_order = {
            placement.module_id: index
            for index, placement in enumerate(self.placements)
        }
        return tuple(
            placement.module_id
            for placement in sorted(
                self.placements,
                key=lambda item: (
                    slot_order.get(item.slot_ref, len(slot_order)),
                    original_order[item.module_id],
                ),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "name": self.name,
            "layout": self.layout.to_dict(),
            "placements": [placement.to_dict() for placement in self.placements],
            "revision": self.revision,
            "state": self.state,
            "legend_policy": self.legend_policy,
            "selected_module_id": self.selected_module_id,
            "compiled_document_ref": self.compiled_document_ref,
            "compiled_document_sha256": self.compiled_document_sha256,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompositionVariant:
        value = require_json_object(payload, label="CompositionVariant")
        reject_unknown_keys(
            value,
            {
                "variant_id",
                "name",
                "layout",
                "placements",
                "revision",
                "state",
                "legend_policy",
                "selected_module_id",
                "compiled_document_ref",
                "compiled_document_sha256",
                "created_at",
                "updated_at",
            },
            label="CompositionVariant",
        )
        raw_placements = require_json_list(
            value.get("placements"),
            label="composition placements",
        )
        if not all(isinstance(item, dict) for item in raw_placements):
            raise ValueError("Every composition placement must be an object.")
        return cls(
            variant_id=_safe_id(value.get("variant_id"), "variant_id"),
            name=_required_text(value.get("name"), "variant name", maximum=160),
            layout=CompositionLayout.from_dict(
                require_json_object(value.get("layout"), label="variant layout")
            ),
            placements=tuple(
                CompositionPlacement.from_dict(item) for item in raw_placements
            ),
            revision=require_json_int(value.get("revision", 0), label="revision"),
            state=_required_text(value.get("state"), "variant state", maximum=64),
            legend_policy=_required_text(
                value.get("legend_policy"),
                "legend_policy",
                maximum=64,
            ),
            selected_module_id=(
                _safe_id(value.get("selected_module_id"), "selected_module_id")
                if value.get("selected_module_id") is not None
                else None
            ),
            compiled_document_ref=_optional_ref(
                value.get("compiled_document_ref"),
                "compiled_document_ref",
                suffix=".vsz",
            ),
            compiled_document_sha256=(
                _sha256(
                    value.get("compiled_document_sha256"),
                    "compiled_document_sha256",
                )
                if value.get("compiled_document_sha256") is not None
                else None
            ),
            created_at=_required_text(
                value.get("created_at"),
                "variant created_at",
                maximum=80,
            ),
            updated_at=_required_text(
                value.get("updated_at"),
                "variant updated_at",
                maximum=80,
            ),
        )


@dataclass(frozen=True)
class CompositionProject:
    composition_id: str
    name: str
    source_modules: tuple[CompositionSourceModule, ...]
    variants: tuple[CompositionVariant, ...]
    active_variant_id: str
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _safe_id(self.composition_id, "composition_id")
        _required_text(self.name, "composition name", maximum=160)
        if not 1 <= len(self.source_modules) <= 12:
            raise ValueError(
                "Composition projects require one to twelve source modules."
            )
        module_ids = [module.module_id for module in self.source_modules]
        if len(set(module_ids)) != len(module_ids):
            raise ValueError("Composition source module ids must be unique.")
        source_refs = [module.source_ref for module in self.source_modules]
        if len(set(source_refs)) != len(source_refs):
            raise ValueError("Composition source refs must be unique.")
        if not self.variants:
            raise ValueError("Composition projects require at least one variant.")
        variant_ids = [variant.variant_id for variant in self.variants]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("Composition variant ids must be unique.")
        if self.active_variant_id not in variant_ids:
            raise ValueError("active_variant_id does not identify a project variant.")
        source_id_set = set(module_ids)
        for variant in self.variants:
            placement_ids = {placement.module_id for placement in variant.placements}
            if placement_ids != source_id_set:
                raise ValueError(
                    "Every composition variant must contain each source module exactly once."
                )
        _required_text(self.created_at, "composition created_at", maximum=80)
        _required_text(self.updated_at, "composition updated_at", maximum=80)

    @property
    def active_variant(self) -> CompositionVariant:
        return self.variant(self.active_variant_id)

    def variant(self, variant_id: str) -> CompositionVariant:
        match = next(
            (variant for variant in self.variants if variant.variant_id == variant_id),
            None,
        )
        if match is None:
            raise ValueError(f"Unknown composition variant: {variant_id!r}")
        return match

    def source_module(self, module_id: str) -> CompositionSourceModule:
        match = next(
            (module for module in self.source_modules if module.module_id == module_id),
            None,
        )
        if match is None:
            raise ValueError(f"Unknown composition source module: {module_id!r}")
        return match

    def with_variant(self, updated: CompositionVariant) -> CompositionProject:
        if updated.variant_id not in {variant.variant_id for variant in self.variants}:
            raise ValueError("Cannot replace an unknown composition variant.")
        return replace(
            self,
            variants=tuple(
                updated if variant.variant_id == updated.variant_id else variant
                for variant in self.variants
            ),
            updated_at=_now(),
        )

    def with_source_modules(
        self,
        modules: tuple[CompositionSourceModule, ...],
    ) -> CompositionProject:
        return replace(self, source_modules=modules, updated_at=_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": COMPOSITION_PROJECT_KIND,
            "version": COMPOSITION_PROJECT_VERSION,
            "composition_id": self.composition_id,
            "name": self.name,
            "active_variant_id": self.active_variant_id,
            "source_modules": [module.to_dict() for module in self.source_modules],
            "variants": [variant.to_dict() for variant in self.variants],
            "authority_policy": dict(_AUTHORITY_POLICY),
            "renderer_contract": dict(_RENDERER_CONTRACT),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompositionProject:
        value = require_json_object(payload, label="CompositionProject")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "composition_id",
                "name",
                "active_variant_id",
                "source_modules",
                "variants",
                "authority_policy",
                "renderer_contract",
                "created_at",
                "updated_at",
            },
            label="CompositionProject",
        )
        if value.get("kind") != COMPOSITION_PROJECT_KIND:
            raise ValueError("Not a SciPlot composition project.")
        version = require_json_int(
            value.get("version", 0),
            label="composition project version",
        )
        if version != COMPOSITION_PROJECT_VERSION:
            raise ValueError(f"Unsupported composition project version: {version}")
        if value.get("authority_policy") != _AUTHORITY_POLICY:
            raise ValueError("Composition authority policy is missing or was altered.")
        if value.get("renderer_contract") != _RENDERER_CONTRACT:
            raise ValueError("Composition renderer contract is missing or was altered.")
        raw_modules = require_json_list(
            value.get("source_modules"),
            label="composition source modules",
        )
        raw_variants = require_json_list(
            value.get("variants"),
            label="composition variants",
        )
        if not all(isinstance(item, dict) for item in raw_modules):
            raise ValueError("Every composition source module must be an object.")
        if not all(isinstance(item, dict) for item in raw_variants):
            raise ValueError("Every composition variant must be an object.")
        return cls(
            composition_id=_safe_id(
                value.get("composition_id"),
                "composition_id",
            ),
            name=_required_text(value.get("name"), "composition name", maximum=160),
            active_variant_id=_safe_id(
                value.get("active_variant_id"),
                "active_variant_id",
            ),
            source_modules=tuple(
                CompositionSourceModule.from_dict(item) for item in raw_modules
            ),
            variants=tuple(CompositionVariant.from_dict(item) for item in raw_variants),
            created_at=_required_text(
                value.get("created_at"),
                "composition created_at",
                maximum=80,
            ),
            updated_at=_required_text(
                value.get("updated_at"),
                "composition updated_at",
                maximum=80,
            ),
        )


def new_composition_project(
    *,
    name: str,
    source_modules: tuple[CompositionSourceModule, ...],
    layout_id: str | None = None,
    canvas_height_mm: float = DEFAULT_COMPOSITION_HEIGHT_MM,
    composition_id: str | None = None,
    variant_id: str = "default",
) -> CompositionProject:
    if not source_modules:
        raise ValueError("A composition project requires at least one source module.")
    selected_layout = layout_id or default_layout_for_module_count(len(source_modules))
    layout = composition_layout(
        selected_layout,
        canvas_height_mm=canvas_height_mm,
    )
    placements = tuple(
        CompositionPlacement(
            module_id=module.module_id,
            slot_ref=(layout.slot_ids[index] if index < len(layout.slot_ids) else None),
        )
        for index, module in enumerate(source_modules)
    )
    variant = CompositionVariant(
        variant_id=variant_id,
        name="Default",
        layout=layout,
        placements=placements,
        selected_module_id=source_modules[0].module_id,
    )
    identifier = composition_id or f"composition_{uuid4().hex[:12]}"
    return CompositionProject(
        composition_id=identifier,
        name=name,
        source_modules=source_modules,
        variants=(variant,),
        active_variant_id=variant.variant_id,
    )


def clone_composition_variant(
    project: CompositionProject,
    *,
    source_variant_id: str,
    variant_id: str,
    name: str,
) -> CompositionProject:
    _safe_id(variant_id, "variant_id")
    if variant_id in {variant.variant_id for variant in project.variants}:
        raise ValueError(f"Composition variant already exists: {variant_id!r}")
    source = project.variant(source_variant_id)
    now = _now()
    cloned = replace(
        source,
        variant_id=variant_id,
        name=_required_text(name, "variant name", maximum=160),
        revision=0,
        state="draft",
        compiled_document_ref=None,
        compiled_document_sha256=None,
        created_at=now,
        updated_at=now,
    )
    return replace(
        project,
        variants=(*project.variants, cloned),
        active_variant_id=variant_id,
        updated_at=now,
    )


def _placement_map(
    variant: CompositionVariant,
) -> dict[str, str | None]:
    return {placement.module_id: placement.slot_ref for placement in variant.placements}


def _variant_with_placements(
    variant: CompositionVariant,
    placements: dict[str, str | None],
) -> CompositionVariant:
    return replace(
        variant,
        placements=tuple(
            CompositionPlacement(
                module_id=placement.module_id,
                slot_ref=placements[placement.module_id],
            )
            for placement in variant.placements
        ),
    )


def _as_draft(variant: CompositionVariant) -> CompositionVariant:
    return replace(
        variant,
        state="draft",
        compiled_document_ref=None,
        compiled_document_sha256=None,
    )


def _operation_change(
    project: CompositionProject,
    variant: CompositionVariant,
    operation: CanvasOperation,
) -> tuple[CompositionVariant, dict[str, Any]]:
    if operation.target_id != variant.variant_id:
        raise ValueError(
            "Composition operations must target exactly one known variant."
        )
    arguments = operation.arguments
    if operation.operation_type == "composition_place_module":
        module_id = str(arguments["module_id"])
        if module_id not in {module.module_id for module in project.source_modules}:
            raise ValueError(f"Unknown composition module: {module_id!r}")
        target_slot = arguments["slot_ref"]
        expected_slot = arguments["expected_slot_ref"]
        if target_slot is not None and target_slot not in variant.layout.slot_ids:
            raise ValueError(f"Unknown composition slot: {target_slot!r}")
        placements = _placement_map(variant)
        current_slot = placements[module_id]
        if current_slot != expected_slot:
            raise ValueError(
                f"Composition slot conflict for {module_id!r}: "
                f"expected {expected_slot!r}, current {current_slot!r}."
            )
        if current_slot == target_slot:
            return variant, {
                "operation_type": operation.operation_type,
                "operation_id": operation.operation_id,
                "module_id": module_id,
                "old_slot_ref": current_slot,
                "new_slot_ref": target_slot,
                "effectful": False,
            }
        occupant = next(
            (
                candidate
                for candidate, slot_ref in placements.items()
                if slot_ref == target_slot and candidate != module_id
            ),
            None,
        )
        placements[module_id] = target_slot
        if occupant is not None:
            placements[occupant] = current_slot
        updated = _variant_with_placements(variant, placements)
        return updated, {
            "operation_type": operation.operation_type,
            "operation_id": operation.operation_id,
            "module_id": module_id,
            "old_slot_ref": current_slot,
            "new_slot_ref": target_slot,
            "swapped_module_id": occupant,
            "effectful": True,
        }

    if operation.operation_type == "composition_reorder_modules":
        ordered = tuple(str(value) for value in arguments["ordered_module_ids"])
        expected = tuple(
            str(value) for value in arguments["expected_ordered_module_ids"]
        )
        current = variant.ordered_module_ids()
        source_ids = {module.module_id for module in project.source_modules}
        if set(ordered) != source_ids or len(ordered) != len(source_ids):
            raise ValueError(
                "Composition reorder must contain every source module exactly once."
            )
        if expected != current:
            raise ValueError(
                "Composition module-order conflict: the variant changed after preview."
            )
        if ordered == current:
            return variant, {
                "operation_type": operation.operation_type,
                "operation_id": operation.operation_id,
                "old_order": list(current),
                "new_order": list(ordered),
                "effectful": False,
            }
        placements = {
            module_id: (
                variant.layout.slot_ids[index]
                if index < len(variant.layout.slot_ids)
                else None
            )
            for index, module_id in enumerate(ordered)
        }
        updated = _variant_with_placements(variant, placements)
        return updated, {
            "operation_type": operation.operation_type,
            "operation_id": operation.operation_id,
            "old_order": list(current),
            "new_order": list(ordered),
            "effectful": True,
        }

    if operation.operation_type == "composition_set_layout":
        expected = str(arguments["expected_layout_id"])
        layout_id = str(arguments["layout_id"])
        if expected != variant.layout.layout_id:
            raise ValueError(
                "Composition layout conflict: the variant changed after preview."
            )
        if layout_id == variant.layout.layout_id:
            return variant, {
                "operation_type": operation.operation_type,
                "operation_id": operation.operation_id,
                "old_layout_id": expected,
                "new_layout_id": layout_id,
                "effectful": False,
            }
        layout = composition_layout(
            layout_id,
            canvas_height_mm=variant.layout.canvas_height_mm,
        )
        ordered = variant.ordered_module_ids()
        placements = {
            module_id: (
                layout.slot_ids[index] if index < len(layout.slot_ids) else None
            )
            for index, module_id in enumerate(ordered)
        }
        updated = replace(
            variant,
            layout=layout,
            placements=tuple(
                CompositionPlacement(
                    module_id=placement.module_id,
                    slot_ref=placements[placement.module_id],
                )
                for placement in variant.placements
            ),
        )
        return updated, {
            "operation_type": operation.operation_type,
            "operation_id": operation.operation_id,
            "old_layout_id": expected,
            "new_layout_id": layout_id,
            "effectful": True,
        }

    if operation.operation_type == "composition_set_canvas_height":
        expected = float(arguments["expected_height_mm"])
        height = float(arguments["height_mm"])
        if not math.isclose(
            expected,
            variant.layout.canvas_height_mm,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "Composition height conflict: the variant changed after preview."
            )
        if math.isclose(height, expected, abs_tol=1e-6):
            return variant, {
                "operation_type": operation.operation_type,
                "operation_id": operation.operation_id,
                "old_height_mm": expected,
                "new_height_mm": height,
                "effectful": False,
            }
        updated = replace(
            variant,
            layout=composition_layout(
                variant.layout.layout_id,
                canvas_height_mm=height,
            ),
        )
        return updated, {
            "operation_type": operation.operation_type,
            "operation_id": operation.operation_id,
            "old_height_mm": expected,
            "new_height_mm": height,
            "effectful": True,
        }

    if operation.operation_type == "composition_set_legend_policy":
        expected = str(arguments["expected_legend_policy"])
        policy = str(arguments["legend_policy"])
        if expected != variant.legend_policy:
            raise ValueError(
                "Composition legend-policy conflict: the variant changed after preview."
            )
        if policy == expected:
            return variant, {
                "operation_type": operation.operation_type,
                "operation_id": operation.operation_id,
                "old_legend_policy": expected,
                "new_legend_policy": policy,
                "effectful": False,
            }
        return replace(variant, legend_policy=policy), {
            "operation_type": operation.operation_type,
            "operation_id": operation.operation_id,
            "old_legend_policy": expected,
            "new_legend_policy": policy,
            "effectful": True,
        }

    raise ValueError(f"Unsupported composition operation: {operation.operation_type!r}")


def _evaluate_composition_batch(
    project: CompositionProject,
    batch: CanvasOperationBatch,
) -> tuple[CompositionProject, list[dict[str, Any]], CompositionVariant]:
    validated = CanvasOperationBatch.from_dict(batch.to_dict())
    target_ids = {operation.target_id for operation in validated.operations}
    if len(target_ids) != 1:
        raise ValueError("Composition batches must target exactly one variant.")
    variant_id = next(iter(target_ids))
    variant = project.variant(variant_id)
    if validated.base_revision != variant.revision:
        raise ValueError(
            f"Stale composition batch: base_revision={validated.base_revision}, "
            f"current_revision={variant.revision}."
        )
    structural = {
        operation.operation_type
        for operation in validated.operations
        if operation.operation_type
        in {
            "composition_reorder_modules",
            "composition_set_layout",
            "composition_set_canvas_height",
            "composition_set_legend_policy",
        }
    }
    if structural and len(validated.operations) != 1:
        raise ValueError(
            "Structural composition operations require their own atomic batch."
        )
    place_modules: set[str] = set()
    place_slots: set[str] = set()
    current = variant
    changes: list[dict[str, Any]] = []
    for operation in validated.operations:
        if operation.operation_type == "composition_place_module":
            module_id = str(operation.arguments["module_id"])
            slot_ref = operation.arguments["slot_ref"]
            if module_id in place_modules:
                raise ValueError(
                    "Composition batch repeats a module placement operation."
                )
            if slot_ref is not None and str(slot_ref) in place_slots:
                raise ValueError("Composition batch repeats a target slot.")
            place_modules.add(module_id)
            if slot_ref is not None:
                place_slots.add(str(slot_ref))
        current, change = _operation_change(project, current, operation)
        changes.append(change)
    if not any(change["effectful"] for change in changes):
        raise ValueError("Composition batch does not change the active variant.")
    now = _now()
    current = replace(
        _as_draft(current),
        revision=variant.revision + 1,
        updated_at=now,
    )
    updated_project = replace(
        project.with_variant(current),
        active_variant_id=current.variant_id,
        updated_at=now,
    )
    return updated_project, changes, current


def preview_composition_batch(
    project: CompositionProject,
    batch: CanvasOperationBatch,
) -> dict[str, Any]:
    updated, changes, variant = _evaluate_composition_batch(project, batch)
    return {
        "kind": "sciplot_composition_operation_preview",
        "version": 1,
        "batch_id": batch.batch_id,
        "base_revision": batch.base_revision,
        "provider": batch.provider,
        "rationale": batch.rationale,
        "variant_id": variant.variant_id,
        "next_revision": variant.revision,
        "operation_count": len(batch.operations),
        "changes": changes,
        "ready_to_compile": variant.ready_to_compile,
        "publication_document_changed": False,
        "resulting_project": updated.to_dict(),
    }


def apply_composition_batch(
    project: CompositionProject,
    batch: CanvasOperationBatch,
) -> tuple[CompositionProject, dict[str, Any]]:
    updated, changes, variant = _evaluate_composition_batch(project, batch)
    return updated, {
        "kind": "sciplot_composition_operation_receipt",
        "version": 1,
        "batch_id": batch.batch_id,
        "base_revision": batch.base_revision,
        "revision": variant.revision,
        "provider": batch.provider,
        "rationale": batch.rationale,
        "variant_id": variant.variant_id,
        "operation_count": len(batch.operations),
        "changes": changes,
        "ready_to_compile": variant.ready_to_compile,
        "publication_document_changed": False,
        "accepted_at": _now(),
    }


__all__ = [
    "COMPOSITE_CANVAS_WIDTH_MM",
    "COMPOSITE_LAYOUT_KIND",
    "COMPOSITE_LAYOUT_VERSION",
    "COMPOSITE_NOMINAL_CONTENT_WIDTH_MM",
    "COMPOSITION_LEGEND_POLICIES",
    "COMPOSITION_PROJECT_KIND",
    "COMPOSITION_PROJECT_VERSION",
    "COMPOSITION_VARIANT_STATES",
    "CompositionLayout",
    "CompositionPlacement",
    "CompositionProject",
    "CompositionSlot",
    "CompositionSourceModule",
    "CompositionVariant",
    "apply_composition_batch",
    "build_composite_layout",
    "clone_composition_variant",
    "composite_layout_ids",
    "composition_layout",
    "default_layout_for_module_count",
    "list_composite_layouts",
    "new_composition_project",
    "preview_composition_batch",
]
