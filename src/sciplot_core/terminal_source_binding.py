"""Bind one adapter-materialized table to an internal terminal render."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe


TERMINAL_SOURCE_BINDING_KIND = "sciplot_internal_terminal_source_binding"
TERMINAL_SOURCE_BINDING_VERSION = 1
_CONTRACT_MISMATCH = "terminal_source_binding_contract_mismatch"
_REQUEST_MISMATCH = "terminal_source_binding_request_mismatch"
_SOURCE_CHANGED = "terminal_source_binding_source_changed"
_SERIES_MISMATCH = "terminal_source_binding_series_mismatch"
_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


class TerminalSourceBindingError(ValueError):
    """Stable failure raised by the internal materialized-source seam."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def _fail(reason_code: str, message: str) -> NoReturn:
    raise TerminalSourceBindingError(reason_code, message)


def _require(condition: bool, message: str, *, reason_code: str) -> None:
    if not condition:
        _fail(reason_code, message)


def _identifier(value: object, *, label: str) -> str:
    _require(
        isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None,
        f"{label} must be one canonical lowercase identifier.",
        reason_code=_CONTRACT_MISMATCH,
    )
    return value


@dataclass(frozen=True, slots=True)
class SourceArtifactBinding:
    path: str
    sha256: str

    @classmethod
    def create(cls, path: Path) -> SourceArtifactBinding:
        resolved = path.expanduser().resolve()
        _require(
            resolved.is_file(),
            f"Bound terminal source is not a file: {resolved}",
            reason_code=_CONTRACT_MISMATCH,
        )
        return cls(path=str(resolved), sha256=file_sha256(resolved))

    @classmethod
    def from_payload(cls, value: object, *, label: str) -> SourceArtifactBinding:
        if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
            _fail(_CONTRACT_MISMATCH, f"{label} must contain only path and sha256.")
        path = value.get("path")
        digest = value.get("sha256")
        _require(
            isinstance(path, str) and bool(path) and Path(path).is_absolute(),
            f"{label} path must be absolute text.",
            reason_code=_CONTRACT_MISMATCH,
        )
        _require(
            str(Path(path).expanduser().resolve()) == path,
            f"{label} path is not canonical.",
            reason_code=_CONTRACT_MISMATCH,
        )
        _require(
            isinstance(digest, str) and _HASH.fullmatch(digest) is not None,
            f"{label} sha256 is invalid.",
            reason_code=_CONTRACT_MISMATCH,
        )
        return cls(path=path, sha256=digest)

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}

    def verify_current(self, *, label: str) -> None:
        path = Path(self.path)
        _require(
            path.is_file() and file_sha256(path) == self.sha256,
            f"{label} changed after the terminal source was bound: {path}",
            reason_code=_SOURCE_CHANGED,
        )


@dataclass(frozen=True, slots=True)
class MaterializedTerminalSourceBinding:
    task_key: str
    rule_id: str
    template: str
    x_metric: str
    y_metric: str
    raw_sources: tuple[SourceArtifactBinding, ...]
    prepared_source: SourceArtifactBinding
    terminal_source: SourceArtifactBinding
    sample_order: tuple[str, ...]
    point_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("task_key", self.task_key),
            ("rule_id", self.rule_id),
            ("template", self.template),
            ("x_metric", self.x_metric),
            ("y_metric", self.y_metric),
        ):
            _identifier(value, label=label)
        _require(
            self.x_metric != self.y_metric,
            "Terminal x_metric and y_metric must differ.",
            reason_code=_CONTRACT_MISMATCH,
        )
        artifacts_valid = all(
            isinstance(item, SourceArtifactBinding) for item in self.raw_sources
        ) and isinstance(self.prepared_source, SourceArtifactBinding)
        artifacts_valid = artifacts_valid and isinstance(
            self.terminal_source, SourceArtifactBinding
        )
        _require(
            artifacts_valid and bool(self.raw_sources),
            "Terminal source inventory is invalid or empty.",
            reason_code=_CONTRACT_MISMATCH,
        )
        _require(
            len({item.path for item in self.raw_sources}) == len(self.raw_sources),
            "Terminal raw-source inventory must be unique.",
            reason_code=_CONTRACT_MISMATCH,
        )
        labels_valid = all(
            isinstance(sample, str) and bool(sample) and sample.strip() == sample
            for sample in self.sample_order
        )
        _require(
            labels_valid
            and bool(self.sample_order)
            and len(set(self.sample_order)) == len(self.sample_order),
            "Terminal sample_order must contain unique canonical labels.",
            reason_code=_CONTRACT_MISMATCH,
        )
        count_records_valid = all(
            isinstance(item, tuple) and len(item) == 2 for item in self.point_counts
        )
        _require(
            count_records_valid
            and tuple(sample for sample, _count in self.point_counts)
            == self.sample_order,
            "Terminal point_counts must follow the complete sample_order.",
            reason_code=_CONTRACT_MISMATCH,
        )
        _require(
            all(
                isinstance(count, int) and not isinstance(count, bool) and count > 0
                for _sample, count in self.point_counts
            ),
            "Terminal point counts must be positive integers.",
            reason_code=_CONTRACT_MISMATCH,
        )

    @classmethod
    def create(
        cls,
        *,
        task_key: str,
        rule_id: str,
        template: str,
        x_metric: str,
        y_metric: str,
        raw_sources: Iterable[Path],
        prepared_source: Path,
        terminal_source: Path,
        sample_order: Iterable[str],
        point_counts: Mapping[str, int],
    ) -> MaterializedTerminalSourceBinding:
        samples = tuple(sample_order)
        binding = cls(
            task_key=task_key,
            rule_id=rule_id,
            template=template,
            x_metric=x_metric,
            y_metric=y_metric,
            raw_sources=tuple(
                SourceArtifactBinding.create(path) for path in raw_sources
            ),
            prepared_source=SourceArtifactBinding.create(prepared_source),
            terminal_source=SourceArtifactBinding.create(terminal_source),
            sample_order=samples,
            point_counts=tuple(
                (sample, point_counts.get(sample)) for sample in samples
            ),
        )
        _require(
            set(point_counts) == set(samples),
            "Terminal point_counts must exactly cover sample_order.",
            reason_code=_CONTRACT_MISMATCH,
        )
        binding.verify_sources()
        return binding

    def verify_sources(self) -> None:
        for index, artifact in enumerate(self.raw_sources, start=1):
            artifact.verify_current(label=f"Raw source {index}")
        self.prepared_source.verify_current(label="Prepared source")
        self.terminal_source.verify_current(label="Terminal source")

    def validate_request(self, request_path: Path, request: Mapping[str, Any]) -> None:
        self.verify_sources()
        reserved = ("_terminal_source_binding", "_terminal_source_prepared")
        _require(
            not any(field in request for field in reserved),
            "A public request cannot carry internal terminal-source authority.",
            reason_code=_REQUEST_MISMATCH,
        )
        identity = (
            request.get("rule_id"),
            request.get("template"),
            request.get("x_metric"),
            request.get("y_metric"),
        )
        _require(
            identity == (self.rule_id, self.template, self.x_metric, self.y_metric),
            "Terminal request rule, template, or metric identity diverged.",
            reason_code=_REQUEST_MISMATCH,
        )
        input_value = request.get("input")
        _require(
            isinstance(input_value, str) and bool(input_value.strip()),
            "Terminal request has no bound input path.",
            reason_code=_REQUEST_MISMATCH,
        )
        input_path = Path(input_value).expanduser()
        if not input_path.is_absolute():
            input_path = request_path.parent / input_path
        _require(
            str(input_path.resolve()) == self.terminal_source.path,
            "Terminal request input does not match its materialized source.",
            reason_code=_REQUEST_MISMATCH,
        )
        _require(
            request.get("series_order") == list(self.sample_order),
            "Terminal request series_order does not match source authority.",
            reason_code=_REQUEST_MISMATCH,
        )
        options = request.get("render_options")
        metrics_match = isinstance(options, dict) and (
            options.get("x_metric"),
            options.get("y_metric"),
        ) == (self.x_metric, self.y_metric)
        _require(
            metrics_match,
            "Terminal render options do not match the bound metrics.",
            reason_code=_REQUEST_MISMATCH,
        )

    def seal(
        self, request_path: Path, request: Mapping[str, Any]
    ) -> SealedTerminalSourceBinding:
        resolved = request_path.expanduser().resolve()
        self.validate_request(resolved, request)
        return SealedTerminalSourceBinding(
            materialized=self,
            request=SourceArtifactBinding.create(resolved),
        )

    def validate_series(self, series: Sequence[Any]) -> None:
        self.verify_sources()
        try:
            records = tuple(
                (
                    item.label,
                    len(item.x_values),
                    len(item.y_values),
                    tuple(item.source_artifacts),
                )
                for item in series
            )
        except (AttributeError, TypeError) as exc:
            raise TerminalSourceBindingError(
                _SERIES_MISMATCH, "Rendered series records are invalid."
            ) from exc
        _require(
            tuple(item[0] for item in records) == self.sample_order,
            "Rendered series order does not match the bound source order.",
            reason_code=_SERIES_MISMATCH,
        )
        expected_counts = dict(self.point_counts)
        expected_artifacts = ((self.terminal_source.path, self.terminal_source.sha256),)
        for label, x_count, y_count, artifacts in records:
            _require(
                x_count == expected_counts[label] and y_count == expected_counts[label],
                f"Rendered point count diverged for sample {label!r}.",
                reason_code=_SERIES_MISMATCH,
            )
            _require(
                artifacts == expected_artifacts,
                f"Rendered source artifact diverged for sample {label!r}.",
                reason_code=_SERIES_MISMATCH,
            )


@dataclass(frozen=True, slots=True)
class SealedTerminalSourceBinding:
    materialized: MaterializedTerminalSourceBinding
    request: SourceArtifactBinding

    def to_payload(self) -> dict[str, Any]:
        source = self.materialized
        return {
            "kind": TERMINAL_SOURCE_BINDING_KIND,
            "version": TERMINAL_SOURCE_BINDING_VERSION,
            "task_key": source.task_key,
            "rule_id": source.rule_id,
            "template": source.template,
            "x_metric": source.x_metric,
            "y_metric": source.y_metric,
            "raw_sources": [item.to_payload() for item in source.raw_sources],
            "prepared_source": source.prepared_source.to_payload(),
            "terminal_source": source.terminal_source.to_payload(),
            "sample_order": list(source.sample_order),
            "point_counts": [
                {"sample": sample, "count": count}
                for sample, count in source.point_counts
            ],
            "request": self.request.to_payload(),
        }

    def to_environment_value(self) -> str:
        return json.dumps(
            json_safe(self.to_payload()),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def validate_request(self, request_path: Path, request: Mapping[str, Any]) -> None:
        resolved = request_path.expanduser().resolve()
        _require(
            str(resolved) == self.request.path,
            "Terminal worker request path does not match its sealed binding.",
            reason_code=_REQUEST_MISMATCH,
        )
        self.request.verify_current(label="Terminal worker request")
        self.materialized.validate_request(resolved, request)


__all__ = [
    "MaterializedTerminalSourceBinding",
    "SealedTerminalSourceBinding",
    "SourceArtifactBinding",
    "TERMINAL_SOURCE_BINDING_KIND",
    "TERMINAL_SOURCE_BINDING_VERSION",
    "TerminalSourceBindingError",
]
