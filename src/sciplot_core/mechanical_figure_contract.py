"""Shared scientific and ordered-task contract for mechanical figures."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping


MECHANICAL_RULE_IDS: Final = frozenset(
    {"tensile_curve", "compression_curve", "flexural_curve"}
)
MECHANICAL_DEFAULT_REPLICATE_MODE: Final = "representative"
MECHANICAL_SELECTION_POLICY: Final = "mechanical_curve_then_all_descriptive_summaries"
MECHANICAL_STATISTICS_METHOD_ID: Final = "descriptive_median_iqr_raw_points"
MECHANICAL_QUARTILE_METHOD: Final = "linear_interpolation_at_(n_minus_1)_times_p"


def mechanical_statistics_method() -> dict[str, Any]:
    """Return the exact confirmed method used by every mechanical summary."""

    return {
        "kind": "sciplot_statistics_method_contract",
        "version": 1,
        "status": "confirmed",
        "auto_inference_allowed": False,
        "significance_required": False,
        "method_id": MECHANICAL_STATISTICS_METHOD_ID,
        "method_version": "1",
        "source": "mechanical_figure_contract",
        "n_definition": "one independently tested specimen",
        "center": "median",
        "spread_or_interval": "interquartile range",
        "test": "none",
        "multiple_comparisons": "none",
        "parameters": {
            "raw_points_visible": True,
            "quartile_method": MECHANICAL_QUARTILE_METHOD,
            "box_whisker_mode": "1.5IQR",
        },
    }


def mechanical_selection_policy(replicate_mode: str) -> str:
    """Return the closed selection identity for one supported curve mode."""

    if replicate_mode not in {"representative", "individual"}:
        raise ValueError(
            "Mechanical selection policy requires representative or individual."
        )
    return f"{MECHANICAL_SELECTION_POLICY}_{replicate_mode}_curve"


@dataclass(frozen=True, slots=True)
class MechanicalFigureTaskContract:
    """One route-independent mechanical FigureTask and display contract."""

    figure_id: str
    title: str
    x_metric: str
    y_metric: str
    template: str
    artifact_stem: str
    document_stem: str
    x_label: str
    y_label: str
    x_unit: str
    y_unit: str
    source_x_label: str
    source_y_label: str
    statistics_method_id: str | None = None

    @property
    def statistics_method(self) -> dict[str, Any] | None:
        """Return an independent JSON payload for summary tasks."""

        if self.statistics_method_id is None:
            return None
        if self.statistics_method_id != MECHANICAL_STATISTICS_METHOD_ID:
            raise ValueError("Unsupported mechanical statistics method identity.")
        return mechanical_statistics_method()

    @property
    def is_summary(self) -> bool:
        return self.statistics_method_id is not None

    def study_model_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.figure_id,
            "title": self.title,
            "metric": self.y_metric,
            "x_metric": self.x_metric,
            "y_metric": self.y_metric,
            "default_template": self.template,
        }
        statistics_method = self.statistics_method
        if statistics_method is not None:
            payload["statistics_method"] = statistics_method
        return payload


@dataclass(frozen=True, slots=True)
class MechanicalRuleFigureContract:
    """The complete ordered figure set for one mechanical rule."""

    rule_id: str
    tasks: tuple[MechanicalFigureTaskContract, ...]
    default_replicate_mode: str = MECHANICAL_DEFAULT_REPLICATE_MODE
    selection_policy: str = MECHANICAL_SELECTION_POLICY

    def __post_init__(self) -> None:
        if self.rule_id not in MECHANICAL_RULE_IDS:
            raise ValueError(f"Unsupported mechanical rule: {self.rule_id!r}.")
        if not self.tasks or self.tasks[0].is_summary:
            raise ValueError("A mechanical contract must start with its curve task.")
        task_ids = tuple(task.figure_id for task in self.tasks)
        artifact_stems = tuple(task.artifact_stem for task in self.tasks)
        document_stems = tuple(task.document_stem for task in self.tasks)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Mechanical FigureTask identities must be unique.")
        if len(artifact_stems) != len(set(artifact_stems)):
            raise ValueError("Mechanical artifact stems must be unique.")
        if len(document_stems) != len(set(document_stems)):
            raise ValueError("Mechanical document stems must be unique.")
        if any(task.template != "box_strip" for task in self.tasks[1:]):
            raise ValueError("Mechanical summaries must use box_strip.")

    @property
    def primary_task(self) -> MechanicalFigureTaskContract:
        return self.tasks[0]

    @property
    def summary_tasks(self) -> tuple[MechanicalFigureTaskContract, ...]:
        return self.tasks[1:]

    def task_by_id(self, figure_id: str) -> MechanicalFigureTaskContract:
        for task in self.tasks:
            if task.figure_id == figure_id:
                return task
        raise KeyError(figure_id)


def _curve_task(
    *,
    figure_id: str,
    title: str,
    y_metric: str,
    y_label: str,
    source_x_label: str,
) -> MechanicalFigureTaskContract:
    return MechanicalFigureTaskContract(
        figure_id=figure_id,
        title=title,
        x_metric="strain",
        y_metric=y_metric,
        template="curve",
        artifact_stem=figure_id,
        document_stem=figure_id,
        x_label="Strain (%)",
        y_label=y_label,
        x_unit="%",
        y_unit="MPa",
        source_x_label=source_x_label,
        source_y_label=y_label.removesuffix(" (MPa)"),
    )


def _summary_task(
    *,
    figure_id: str,
    title: str,
    y_metric: str,
    y_label: str,
    y_unit: str,
) -> MechanicalFigureTaskContract:
    return MechanicalFigureTaskContract(
        figure_id=figure_id,
        title=title,
        x_metric="sample",
        y_metric=y_metric,
        template="box_strip",
        artifact_stem=figure_id,
        document_stem=figure_id,
        x_label="Sample",
        y_label=y_label,
        x_unit="",
        y_unit=y_unit,
        source_x_label="Sample",
        source_y_label=y_label.removesuffix(f" ({y_unit})"),
        statistics_method_id=MECHANICAL_STATISTICS_METHOD_ID,
    )


_CONTRACTS = {
    "tensile_curve": MechanicalRuleFigureContract(
        rule_id="tensile_curve",
        tasks=(
            _curve_task(
                figure_id="stress_vs_strain",
                title="Tensile stress vs strain",
                y_metric="stress",
                y_label="Tensile stress (MPa)",
                source_x_label="Tensile strain",
            ),
            _summary_task(
                figure_id="tensile_strength_by_sample",
                title="Tensile strength by sample",
                y_metric="strength_MPa",
                y_label="Tensile strength (MPa)",
                y_unit="MPa",
            ),
            _summary_task(
                figure_id="elongation_at_break_by_sample",
                title="Elongation at break by sample",
                y_metric="elongation_at_break_percent",
                y_label="Elongation at break (%)",
                y_unit="%",
            ),
            _summary_task(
                figure_id="tensile_modulus_by_sample",
                title="Tensile modulus by sample",
                y_metric="modulus_MPa",
                y_label="Tensile modulus (MPa)",
                y_unit="MPa",
            ),
            _summary_task(
                figure_id="toughness_by_sample",
                title="Toughness by sample",
                y_metric="toughness_MJ_m3",
                y_label="Toughness (MJ m⁻³)",
                y_unit="MJ/m3",
            ),
        ),
    ),
    "compression_curve": MechanicalRuleFigureContract(
        rule_id="compression_curve",
        tasks=(
            _curve_task(
                figure_id="compressive_stress_vs_strain",
                title="Compressive stress vs strain",
                y_metric="compressive_stress",
                y_label="Compressive stress (MPa)",
                source_x_label="Strain",
            ),
            _summary_task(
                figure_id="compressive_strength_by_sample",
                title="Compressive strength by sample",
                y_metric="compressive_strength_MPa",
                y_label="Compressive strength (MPa)",
                y_unit="MPa",
            ),
        ),
    ),
    "flexural_curve": MechanicalRuleFigureContract(
        rule_id="flexural_curve",
        tasks=(
            _curve_task(
                figure_id="flexural_stress_vs_strain",
                title="Flexural stress vs strain",
                y_metric="flexural_stress",
                y_label="Flexural stress (MPa)",
                source_x_label="Strain",
            ),
            _summary_task(
                figure_id="flexural_strength_by_sample",
                title="Flexural strength by sample",
                y_metric="flexural_strength_MPa",
                y_label="Flexural strength (MPa)",
                y_unit="MPa",
            ),
        ),
    ),
}


MECHANICAL_FIGURE_CONTRACTS: Final[Mapping[str, MechanicalRuleFigureContract]] = (
    MappingProxyType(_CONTRACTS)
)


def mechanical_figure_contract(rule_id: str) -> MechanicalRuleFigureContract:
    """Return the exact mechanical contract or fail for an unsupported rule."""

    try:
        return MECHANICAL_FIGURE_CONTRACTS[rule_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported mechanical rule: {rule_id!r}.") from exc


def mechanical_experiment_plan(rule_id: str) -> dict[str, Any]:
    """Return a fresh Study Model recommendation from the shared contract."""

    contract = mechanical_figure_contract(rule_id)
    return {
        "default_replicate_mode": contract.default_replicate_mode,
        "figure_queue": tuple(task.study_model_payload() for task in contract.tasks),
    }


__all__ = [
    "MECHANICAL_DEFAULT_REPLICATE_MODE",
    "MECHANICAL_FIGURE_CONTRACTS",
    "MECHANICAL_QUARTILE_METHOD",
    "MECHANICAL_RULE_IDS",
    "MECHANICAL_SELECTION_POLICY",
    "MECHANICAL_STATISTICS_METHOD_ID",
    "MechanicalFigureTaskContract",
    "MechanicalRuleFigureContract",
    "mechanical_experiment_plan",
    "mechanical_figure_contract",
    "mechanical_selection_policy",
    "mechanical_statistics_method",
]
