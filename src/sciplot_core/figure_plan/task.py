"""Immutable selected-figure task contract."""

from __future__ import annotations

from dataclasses import dataclass

from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_list,
    require_json_object,
)

from sciplot_core.figure_plan.constants import (
    FIGURE_TASK_KIND,
    FIGURE_TASK_V1_VERSION,
    FIGURE_TASK_V2_VERSION,
)
from sciplot_core.figure_plan.metric_binding import (
    CartesianMetricBinding,
    FigureMetricBinding,
    OrderedMetricsBinding,
    metric_binding_from_payload,
)
from sciplot_core.figure_plan.payload_types import (
    FigureTaskPayload,
    FigureTaskReplicateCountPayload,
    FigureTaskV1Payload,
    FigureTaskV2Payload,
)
from sciplot_core.figure_plan.values import (
    ARTIFACT_STEM_PATTERN,
    FIGURE_ID_PATTERN,
    required_text,
    text_tuple,
)


@dataclass(frozen=True, slots=True)
class FigureTask:
    """One selected logical figure, independent from its physical filenames."""

    figure_id: str
    order: int
    title: str
    x_metric: str | None
    y_metric: str | None
    template: str
    artifact_stem: str
    document_stem: str
    conditions: tuple[str, ...] = ()
    condition_labels: tuple[str, ...] = ()
    sample_order: tuple[str, ...] = ()
    replicate_counts: tuple[tuple[str, int], ...] = ()
    metric_binding: FigureMetricBinding | None = None

    def __post_init__(self) -> None:
        figure_id = required_text(self.figure_id, label="figure_id")
        if FIGURE_ID_PATTERN.fullmatch(figure_id) is None:
            raise ValueError(
                "figure_id must use lowercase ASCII letters, digits, and underscores."
            )
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise ValueError("FigureTask order must be an integer.")
        if self.order < 1:
            raise ValueError("FigureTask order must be 1 or greater.")
        artifact_stem = required_text(self.artifact_stem, label="artifact_stem")
        if ARTIFACT_STEM_PATTERN.fullmatch(artifact_stem) is None:
            raise ValueError("artifact_stem is not a portable filename stem.")
        document_stem = required_text(self.document_stem, label="document_stem")
        if ARTIFACT_STEM_PATTERN.fullmatch(document_stem) is None:
            raise ValueError("document_stem is not a portable filename stem.")
        conditions = text_tuple(self.conditions, label="conditions")
        condition_labels = text_tuple(
            self.condition_labels,
            label="condition_labels",
        )
        if condition_labels and len(condition_labels) != len(conditions):
            raise ValueError(
                "condition_labels must be empty or match the condition count."
            )
        sample_order = text_tuple(self.sample_order, label="sample_order")
        if len(sample_order) != len(set(sample_order)):
            raise ValueError("sample_order entries must be unique.")
        if not isinstance(self.replicate_counts, tuple | list):
            raise ValueError("replicate_counts must contain sample/count pairs.")
        counts: list[tuple[str, int]] = []
        for index, pair in enumerate(self.replicate_counts):
            if not isinstance(pair, tuple | list) or len(pair) != 2:
                raise ValueError(
                    f"replicate_counts[{index}] must be a sample/count pair."
                )
            sample = required_text(
                pair[0],
                label=f"replicate_counts[{index}].sample",
            )
            count = pair[1]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(
                    f"replicate_counts[{index}].count must be a non-negative integer."
                )
            counts.append((sample, count))
        if len({sample for sample, _count in counts}) != len(counts):
            raise ValueError("replicate_counts samples must be unique.")
        if counts and tuple(sample for sample, _count in counts) != sample_order:
            raise ValueError(
                "replicate_counts must follow the complete ordered sample_order."
            )
        object.__setattr__(self, "figure_id", figure_id)
        object.__setattr__(self, "title", required_text(self.title, label="title"))
        if self.metric_binding is None:
            object.__setattr__(
                self,
                "x_metric",
                required_text(self.x_metric, label="x_metric"),
            )
            object.__setattr__(
                self,
                "y_metric",
                required_text(self.y_metric, label="y_metric"),
            )
        else:
            if not isinstance(
                self.metric_binding,
                CartesianMetricBinding | OrderedMetricsBinding,
            ):
                raise ValueError("metric_binding must be a supported binding object.")
            if self.x_metric is not None or self.y_metric is not None:
                raise ValueError(
                    "FigureTask v2 cannot mix top-level x/y metrics with "
                    "metric_binding."
                )
        object.__setattr__(
            self,
            "template",
            required_text(self.template, label="template"),
        )
        object.__setattr__(self, "artifact_stem", artifact_stem)
        object.__setattr__(self, "document_stem", document_stem)
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "condition_labels", condition_labels)
        object.__setattr__(self, "sample_order", sample_order)
        object.__setattr__(self, "replicate_counts", tuple(counts))

    @classmethod
    def with_metric_binding(
        cls,
        *,
        figure_id: str,
        order: int,
        title: str,
        metric_binding: FigureMetricBinding,
        template: str,
        artifact_stem: str,
        document_stem: str,
        conditions: tuple[str, ...] = (),
        condition_labels: tuple[str, ...] = (),
        sample_order: tuple[str, ...] = (),
        replicate_counts: tuple[tuple[str, int], ...] = (),
    ) -> FigureTask:
        """Create an explicit v2 task without legacy top-level axes."""

        return cls(
            figure_id=figure_id,
            order=order,
            title=title,
            x_metric=None,
            y_metric=None,
            template=template,
            artifact_stem=artifact_stem,
            document_stem=document_stem,
            conditions=conditions,
            condition_labels=condition_labels,
            sample_order=sample_order,
            replicate_counts=replicate_counts,
            metric_binding=metric_binding,
        )

    def to_payload(self) -> FigureTaskPayload:
        replicate_counts: list[FigureTaskReplicateCountPayload] = [
            {"sample": sample, "count": count}
            for sample, count in self.replicate_counts
        ]
        if self.metric_binding is None:
            assert self.x_metric is not None
            assert self.y_metric is not None
            v1_payload: FigureTaskV1Payload = {
                "kind": FIGURE_TASK_KIND,
                "version": FIGURE_TASK_V1_VERSION,
                "figure_id": self.figure_id,
                "order": self.order,
                "selected": True,
                "title": self.title,
                "x_metric": self.x_metric,
                "y_metric": self.y_metric,
                "template": self.template,
                "artifact_stem": self.artifact_stem,
                "document_stem": self.document_stem,
                "conditions": list(self.conditions),
                "condition_labels": list(self.condition_labels),
                "sample_order": list(self.sample_order),
                "replicate_counts": replicate_counts,
            }
            return v1_payload
        v2_payload: FigureTaskV2Payload = {
            "kind": FIGURE_TASK_KIND,
            "version": FIGURE_TASK_V2_VERSION,
            "figure_id": self.figure_id,
            "order": self.order,
            "selected": True,
            "title": self.title,
            "metric_binding": self.metric_binding.to_payload(),
            "template": self.template,
            "artifact_stem": self.artifact_stem,
            "document_stem": self.document_stem,
            "conditions": list(self.conditions),
            "condition_labels": list(self.condition_labels),
            "sample_order": list(self.sample_order),
            "replicate_counts": replicate_counts,
        }
        return v2_payload

    @classmethod
    def from_payload(cls, value: object) -> FigureTask:
        payload = require_json_object(value, label="FigureTask")
        version = require_json_int(
            payload.get("version"),
            label="FigureTask.version",
        )
        common_keys = {
            "kind",
            "version",
            "figure_id",
            "order",
            "selected",
            "title",
            "template",
            "artifact_stem",
            "document_stem",
            "conditions",
            "condition_labels",
            "sample_order",
            "replicate_counts",
        }
        if version == FIGURE_TASK_V1_VERSION:
            allowed_keys = common_keys | {"x_metric", "y_metric"}
        elif version == FIGURE_TASK_V2_VERSION:
            allowed_keys = common_keys | {"metric_binding"}
        else:
            raise ValueError("Unsupported FigureTask version.")
        reject_unknown_keys(
            payload,
            allowed_keys,
            label="FigureTask",
        )
        if payload.get("kind") != FIGURE_TASK_KIND:
            raise ValueError("Not a SciPlot FigureTask payload.")
        if (
            require_json_bool(
                payload.get("selected"),
                label="FigureTask.selected",
            )
            is not True
        ):
            raise ValueError("ResolvedFigurePlan v1 contains selected tasks only.")
        raw_counts = require_json_list(
            payload.get("replicate_counts"),
            label="FigureTask.replicate_counts",
        )
        counts: list[tuple[str, int]] = []
        for index, value in enumerate(raw_counts):
            record = require_json_object(
                value,
                label=f"FigureTask.replicate_counts[{index}]",
            )
            reject_unknown_keys(
                record,
                {"sample", "count"},
                label=f"FigureTask.replicate_counts[{index}]",
            )
            counts.append(
                (
                    required_text(
                        record.get("sample"),
                        label=f"FigureTask.replicate_counts[{index}].sample",
                    ),
                    require_json_int(
                        record.get("count"),
                        label=f"FigureTask.replicate_counts[{index}].count",
                    ),
                )
            )
        if version == FIGURE_TASK_V1_VERSION:
            x_metric = required_text(
                payload.get("x_metric"),
                label="FigureTask.x_metric",
            )
            y_metric = required_text(
                payload.get("y_metric"),
                label="FigureTask.y_metric",
            )
            metric_binding = None
        else:
            x_metric = None
            y_metric = None
            metric_binding = metric_binding_from_payload(payload.get("metric_binding"))
        return cls(
            figure_id=required_text(
                payload.get("figure_id"),
                label="FigureTask.figure_id",
            ),
            order=require_json_int(
                payload.get("order"),
                label="FigureTask.order",
            ),
            title=required_text(payload.get("title"), label="FigureTask.title"),
            x_metric=x_metric,
            y_metric=y_metric,
            template=required_text(
                payload.get("template"),
                label="FigureTask.template",
            ),
            artifact_stem=required_text(
                payload.get("artifact_stem"),
                label="FigureTask.artifact_stem",
            ),
            document_stem=required_text(
                payload.get("document_stem"),
                label="FigureTask.document_stem",
            ),
            conditions=text_tuple(
                require_json_list(
                    payload.get("conditions"),
                    label="FigureTask.conditions",
                ),
                label="FigureTask.conditions",
            ),
            condition_labels=text_tuple(
                require_json_list(
                    payload.get("condition_labels"),
                    label="FigureTask.condition_labels",
                ),
                label="FigureTask.condition_labels",
            ),
            sample_order=text_tuple(
                require_json_list(
                    payload.get("sample_order"),
                    label="FigureTask.sample_order",
                ),
                label="FigureTask.sample_order",
            ),
            replicate_counts=tuple(counts),
            metric_binding=metric_binding,
        )


__all__ = ["FigureTask"]
