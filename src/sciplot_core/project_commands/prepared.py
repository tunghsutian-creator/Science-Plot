"""Detached byte-only publications; conversion never discovers or reads a file."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from .resources import InputRead, PreparedFile, PreparedSource, resource_key


class MutationDeclaration(Protocol):
    @property
    def writes(self) -> Mapping[str, bytes | Path | PreparedFile | None]: ...
    @property
    def result(self) -> dict[str, Any]: ...
    @property
    def sources(self) -> Sequence[dict[str, Any]] | None: ...
    @property
    def review(self) -> dict[str, Any] | None: ...
    @property
    def artifacts(self) -> Mapping[str, bytes | Path | PreparedFile]: ...
    @property
    def prepared_sources(self) -> tuple[PreparedSource, ...]: ...
    @property
    def input_reads(self) -> tuple[InputRead, ...]: ...


def _json(value: dict[str, Any] | None) -> str:
    if value is not None and not isinstance(value, dict):
        raise ValueError("Candidate result and review must be JSON objects.")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _files(values: Mapping[str, bytes | Path | PreparedFile | None], *, deletion: bool) -> tuple[tuple[str, bytes | PreparedFile | None], ...]:
    result = []
    for name, value in values.items():
        resource_key(name)
        if not (isinstance(value, (bytes, PreparedFile)) or deletion and value is None):
            raise ValueError("Prepared storage publication requires byte values and no deferred source capture.")
        if isinstance(value, PreparedFile):
            value.__post_init__()
        result.append((name, value))
    return tuple(sorted(result))


@dataclass(frozen=True)
class PreparedMutation:
    """Only immutable values are retained; all public JSON/mappings are copies."""
    _writes: tuple[tuple[str, bytes | PreparedFile | None], ...]
    _result_json: str
    _review_json: str
    _artifacts: tuple[tuple[str, bytes | PreparedFile | None], ...]
    prepared_sources: tuple[PreparedSource, ...] = ()
    input_reads: tuple[InputRead, ...] = ()

    def __post_init__(self) -> None:
        from .contracts import validate_input_reads
        if not isinstance(self._writes, tuple) or not isinstance(self._artifacts, tuple):
            raise ValueError("Prepared files must be immutable tuples.")
        if (len(dict(self._writes)) != len(self._writes) or len(dict(self._artifacts)) != len(self._artifacts)
                or _files(dict(self._writes), deletion=True) != self._writes
                or _files(dict(self._artifacts), deletion=False) != self._artifacts):
            raise ValueError("Prepared file members must be unique and canonical.")
        if not isinstance(self._result_json, str) or not isinstance(self._review_json, str):
            raise ValueError("Prepared JSON must be retained as immutable text.")
        result, review = json.loads(self._result_json), json.loads(self._review_json)
        if not isinstance(result, dict) or _json(result) != self._result_json or _json(review) != self._review_json:
            raise ValueError("Prepared JSON must use its exact canonical object representation.")
        if not isinstance(self.prepared_sources, tuple) or not isinstance(self.input_reads, tuple):
            raise ValueError("Prepared source and input declarations must be immutable tuples.")
        for source in self.prepared_sources:
            if not isinstance(source, PreparedSource):
                raise ValueError("Prepared sources must be explicit captured values.")
            source.__post_init__()
        if validate_input_reads(self.input_reads) != self.input_reads:
            raise ValueError("Prepared input declarations must be canonical.")

    @classmethod
    def from_values(cls, writes: Mapping[str, bytes | Path | PreparedFile | None], result: dict[str, Any], *,
                    review: dict[str, Any] | None = None,
                    artifacts: Mapping[str, bytes | Path | PreparedFile] | None = None,
                    prepared_sources: Sequence[PreparedSource] = (), input_reads: Sequence[InputRead] = ()) -> PreparedMutation:
        from .contracts import validate_input_reads
        captured = tuple(prepared_sources)
        for source in captured:
            if not isinstance(source, PreparedSource):
                raise ValueError("Prepared sources must be explicit captured values.")
            source.__post_init__()
        if not isinstance(result, dict):
            raise ValueError("Candidate result must be a JSON object.")
        return cls(_files(writes, deletion=True), _json(result), _json(review),
                   _files(artifacts or {}, deletion=False), captured, validate_input_reads(input_reads))

    @property
    def writes(self) -> dict[str, bytes | PreparedFile | None]:
        return dict(self._writes)

    @property
    def result(self) -> dict[str, Any]:
        return dict(json.loads(self._result_json))

    @property
    def review(self) -> dict[str, Any] | None:
        value = json.loads(self._review_json)
        return dict(value) if value is not None else None

    @property
    def sources(self) -> None:
        return None

    @property
    def artifacts(self) -> dict[str, bytes | PreparedFile]:
        return {name: value for name, value in self._artifacts if value is not None}

    @property
    def prepared_digest(self) -> str:
        def entries(values: tuple[tuple[str, bytes | PreparedFile | None], ...]) -> dict[str, Any]:
            return {name: (None if value is None else value.descriptor() if isinstance(value, PreparedFile) else
                          {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value), "mode": 0o600})
                    for name, value in values}
        value = {"writes": entries(self._writes), "artifacts": entries(self._artifacts),
                 "result": self.result, "review": self.review,
                 "sources": [source.descriptor() for source in self.prepared_sources]}
        if self.input_reads:
            value["input_reads"] = [item.to_payload() for item in self.input_reads]
        return canonical_json_sha256(value, allow_nan=False)

    def validate_for(self, command: Any) -> None:
        from .contracts import ProjectMutation
        ProjectMutation(self.writes, self.result, review=self.review, artifacts=self.artifacts,
                        prepared_sources=self.prepared_sources, input_reads=self.input_reads).validate_for(command)


def prepared_mutation(value: MutationDeclaration) -> PreparedMutation:
    """Read original declaration fields, including byte-frozen historical callers.

    Do not call a newly added helper on a retained old instance. There is one
    byte-only conversion/digest, and it cannot resolve deferred paths/sources.
    """
    if isinstance(value, PreparedMutation):
        return value
    if value.sources is not None:
        raise ValueError("Prepared storage publication requires byte values and no deferred source capture.")
    return PreparedMutation.from_values(value.writes, value.result, review=value.review, artifacts=value.artifacts,
                                        prepared_sources=value.prepared_sources, input_reads=value.input_reads)
