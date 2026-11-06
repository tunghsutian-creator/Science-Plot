"""Detached provider observations, separate from proposal/edit authority."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from sciplot_core.json_contract import reject_unknown_keys, require_json_object

_USAGE_STATUSES = {"reported", "not_reported", "not_observed", "invalid"}
_FACT_TEXT = re.compile(r"[A-Za-z0-9_.:/-]{1,256}\Z")
_USAGE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,95}\Z")


def _fact_text(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not _FACT_TEXT.fullmatch(value)):
        raise ValueError("Provider fact identifier must be bounded metadata text.")
    return value


def _usage_object(value: object, *, depth: int = 0) -> dict[str, Any]:
    obj = require_json_object(value, label="Provider usage")
    if len(obj) > 32 or depth > 2:
        raise ValueError("Provider usage exceeds its metadata bound.")
    result: dict[str, Any] = {}
    for key, item in obj.items():
        if not isinstance(key, str) or not _USAGE_KEY.fullmatch(key):
            raise ValueError("Provider usage has an invalid counter name.")
        if isinstance(item, dict):
            result[key] = _usage_object(item, depth=depth + 1)
        elif item is None or (type(item) is int and 0 <= item <= 2**63 - 1):
            result[key] = item
        else:
            raise ValueError("Provider usage must contain only actual non-negative counters.")
    return result


@dataclass(frozen=True)
class ProviderFacts:
    response_id: str | None = None
    model: str | None = None
    usage_json: str | None = None
    usage_status: str = "not_observed"
    terminal_status: str | None = None

    def __post_init__(self) -> None:
        _fact_text(self.response_id)
        _fact_text(self.model)
        _fact_text(self.terminal_status)
        if not isinstance(self.usage_status, str) or self.usage_status not in _USAGE_STATUSES:
            raise ValueError("Unknown provider usage observation status.")
        if (self.usage_json is not None) != (self.usage_status == "reported"):
            raise ValueError("Only reported provider usage can carry counters.")
        if self.usage_json is not None:
            if len(self.usage_json.encode("utf-8")) > 16384:
                raise ValueError("Provider usage exceeds its metadata byte bound.")
            canonical = json.dumps(_usage_object(json.loads(self.usage_json)),
                                   sort_keys=True, separators=(",", ":"), allow_nan=False)
            if canonical != self.usage_json:
                raise ValueError("Provider usage must use canonical metadata JSON.")

    @classmethod
    def from_values(cls, *, response_id: str | None = None, model: str | None = None,
                    usage: dict[str, Any] | None = None, usage_status: str = "not_observed",
                    terminal_status: str | None = None) -> ProviderFacts:
        encoded = None if usage is None else json.dumps(
            usage, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return cls(response_id, model, encoded, usage_status, terminal_status)

    @property
    def usage(self) -> dict[str, Any] | None:
        return json.loads(self.usage_json) if self.usage_json is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {"response_id": self.response_id, "model": self.model,
                "usage": self.usage, "usage_status": self.usage_status,
                "terminal_status": self.terminal_status}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProviderFacts:
        obj = require_json_object(value, label="Provider facts")
        reject_unknown_keys(obj, {"response_id", "model", "usage", "usage_status", "terminal_status"},
                            label="Provider facts")
        return cls.from_values(response_id=obj.get("response_id"), model=obj.get("model"),
                               usage=obj.get("usage"), usage_status=obj.get("usage_status", "not_observed"),
                               terminal_status=obj.get("terminal_status"))
