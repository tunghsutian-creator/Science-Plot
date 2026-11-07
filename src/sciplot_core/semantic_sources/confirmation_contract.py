"""Scientific confirmation values and their exact recorded source binding."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sciplot_core.materials_rules.models import SemanticRule

COLUMN_ROLES = frozenset({"auto", "x", "y", "series", "sample", "unit", "metadata", "ignore"})
COLUMN_TYPES = frozenset({"auto", "numeric", "text", "categorical", "datetime", "unit", "metadata", "ignore"})


def normalize_column_confirmations(value: object) -> list[dict[str, Any]]:
    """Preserve version facts; legacy preview fields do not become instructions."""
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        raise ValueError("Column confirmations must be a list.")
    result = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("columns", []), list | tuple):
            raise ValueError("Each column confirmation requires an object and column list.")
        columns = []
        seen = set()
        for column in item.get("columns", []):
            if (not isinstance(column, dict) or isinstance(column.get("index"), bool)
                    or not isinstance(column.get("index"), int | str)):
                raise ValueError("Each confirmed column requires an integer index.")
            try:
                index = int(column["index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Each confirmed column requires an integer index.") from exc
            if index < 0 or index in seen or index != column["index"] and str(index) != column["index"]:
                raise ValueError("Confirmed column indices must be non-negative and unique.")
            seen.add(index)
            kind = str(column.get("confirmed_type") or column.get("type") or "auto").strip()
            role = str(column.get("role") or "auto").strip()
            inferred = str(column.get("inferred_type") or "auto").strip()
            if kind not in COLUMN_TYPES or inferred not in COLUMN_TYPES or role not in COLUMN_ROLES:
                raise ValueError("Unknown confirmed column type or role; inspect and confirm the original table again.")
            columns.append({"index": index, "name": str(column.get("name") or f"Column {index + 1}"),
                            "inferred_type": inferred, "confirmed_type": kind, "role": role})
        selected = item.get("sheet_selected") is True
        if not columns and not selected:
            continue
        output: dict[str, Any] = {"sample": str(item.get("sample") or "").strip(),
                  "file_name": str(item.get("file_name") or item.get("name") or ""),
                  "source_path": str(item.get("source_path") or ""),
                  "sheet": str(item.get("sheet") or "") or None, "columns": columns}
        if "source_sha256" in item:
            digest = str(item["source_sha256"]).casefold()
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Column confirmation requires an exact source SHA-256.")
            output["source_sha256"] = digest
        if selected:
            if not output["sheet"] or not output.get("source_sha256"):
                raise ValueError("Explicit worksheet selection requires its name and exact source SHA-256.")
            output["sheet_selected"] = True
        result.append(output)
    return result


def has_column_intent(confirmation: dict[str, Any]) -> bool:
    return any(column["role"] != "auto" or column["confirmed_type"] != "auto"
               for column in confirmation["columns"])


def confirmation_capabilities(rule: SemanticRule) -> dict[str, Any]:
    sweep = rule.scientific_source_adapter in {"rheology_frequency", "rheology_temperature"}
    return {"worksheet": rule.scientific_source_adapter == "registered_paired_curve",
            "column_roles": ["auto", "ignore", "x", "y"] if sweep else ["auto"],
            "column_types": ["auto", "ignore", "numeric"] if sweep else ["auto"],
            "column_scope": "one contiguous plain source table; instrument Test/Result/Interval scopes use task mapping" if sweep else "observations only",
            "unsupported_choices": "Use the source-bound task/table-mapping route for other scientific selections."}


def require_supported_confirmations(rule: SemanticRule, value: object) -> list[dict[str, Any]]:
    confirmations = normalize_column_confirmations(value)
    capabilities = confirmation_capabilities(rule)
    for item in confirmations:
        if item.get("sheet_selected") is True and not capabilities["worksheet"]:
            raise ValueError(f"Explicit worksheet selection is not supported for {rule.rule_id}; use source-bound task mapping.")
        for column in item["columns"]:
            if column["role"] not in capabilities["column_roles"] or column["confirmed_type"] not in capabilities["column_types"]:
                raise ValueError(f"Explicit column type/role is not supported for {rule.rule_id}; use source-bound task mapping.")
        if has_column_intent(item):
            active = [column for column in item["columns"] if column["confirmed_type"] != "ignore"]
            if sum(column["role"] == "x" for column in active) != 1 or not any(column["role"] == "y" for column in active):
                raise ValueError("An explicit rheology column selection requires one X and at least one Y column.")
    return confirmations


def bind_materialized_confirmations(value: object, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind through recorded group/file facts, never by parsing a generated name."""
    sources = [(group["sample"], item) for group in groups for item in group["files"]]
    result = []
    used = set()
    for item in normalize_column_confirmations(value):
        matches = []
        for sample, source in sources:
            if item["sample"] and item["sample"] != sample:
                continue
            if item["file_name"] and item["file_name"] != source["original_name"]:
                continue
            if item.get("source_sha256") and item["source_sha256"] != source["sha256"]:
                continue
            if item["source_path"]:
                path = Path(item["source_path"]).expanduser().resolve()
                locators = [source["source_path"]]
                if source.get("original_source_path"):
                    locators.append(source["original_source_path"])
                exact = any(path == Path(locator).expanduser().resolve() for locator in locators)
                if not exact:
                    continue
            if not any((item["sample"], item["file_name"], item.get("source_sha256"), item["source_path"])):
                continue
            matches.append((sample, source))
        if len(matches) != 1:
            raise ValueError("A column confirmation must identify one exact recorded sample/file/version; reconfirm ambiguous history.")
        sample, source = matches[0]
        if source["source_path"] in used:
            raise ValueError("Duplicate or conflicting confirmations for one recorded source.")
        used.add(source["source_path"])
        result.append({**item, "sample": sample, "file_name": source["original_name"],
                       "source_path": source["source_path"], "source_sha256": source["sha256"]})
    return result


def request_column_confirmations(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Interpret old confirmed choices using their already recorded source map."""
    model = request.get("study_model")
    groups = [{"sample": sample["name"], "files": [replicate["source_file"] for replicate in sample["replicates"]]}
              for sample in model.get("samples", [])] if isinstance(model, dict) else []
    value = request.get("column_confirmations")
    return bind_materialized_confirmations(value, groups) if groups else normalize_column_confirmations(value)
