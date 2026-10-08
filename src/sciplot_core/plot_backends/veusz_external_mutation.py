"""Read-only full-transcript comparison for a narrow literal Veusz save format.

This does not execute or rewrite VSZ. All saved statements must remain identical
except unique, explicitly bound Set values. Unknown commands and expressions fail
closed instead of being treated as harmless native content.
"""

import ast
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import posixpath
from typing import Any

_LIMIT = 16 * 1024 * 1024
_COMMANDS = {"SetCompatLevel", "AddImportPath", "ImportString", "Add", "To", "Set"}


def _literal(node: ast.expr) -> Any:
    value = ast.literal_eval(node)
    def require_finite(item: Any) -> None:
        if item is None or type(item) in {str, int, bool}:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                require_finite(child)
            return
        raise ValueError("Only finite, literal saved command values are supported")
    require_finite(value)
    return value


def _parse(raw: bytes) -> tuple[ast.Module, dict[str, ast.Call]]:
    if len(raw) > _LIMIT:
        raise ValueError("Native transcript exceeds bounded comparison size")
    tree = ast.parse(raw.decode("utf-8"))
    current = "/"
    settings: dict[str, ast.Call] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise ValueError("Only saved command expressions are supported")
        call = statement.value
        if not isinstance(call.func, ast.Name) or call.func.id not in _COMMANDS:
            raise ValueError("Native command lacks a comparison contract")
        values = [_literal(arg) for arg in call.args]
        if any(keyword.arg is None for keyword in call.keywords):
            raise ValueError("Dynamic keyword expansion is not a saved command")
        keywords = {keyword.arg: _literal(keyword.value) for keyword in call.keywords}
        name = call.func.id
        if name == "To":
            if len(values) != 1 or keywords or not isinstance(values[0], str):
                raise ValueError("Native navigation is not explicit")
            value = values[0]
            if not value or (value != ".." and ("/" in value or value == ".")) or (value == ".." and current == "/"):
                raise ValueError("Native navigation exceeds the saved-tree grammar")
            current = posixpath.normpath(posixpath.join(current, value))
        elif name == "Set":
            if len(values) != 2 or keywords or not isinstance(values[0], str):
                raise ValueError("Native setting is not explicit")
            value = values[0]
            if not value or any(part in {"", ".", ".."} for part in value.split("/")):
                raise ValueError("Native setting path exceeds the saved-tree grammar")
            path = posixpath.join(current, value)
            if path in settings:
                raise ValueError("Repeated setting writes are not an exact semantic delta")
            settings[path] = call
        elif name == "Add":
            if (len(values) != 1 or not isinstance(values[0], str)
                    or set(keywords) != {"name", "autoadd"}
                    or not isinstance(keywords["name"], str) or keywords["autoadd"] is not False):
                raise ValueError("Native object creation exceeds the saved-tree grammar")
            if not keywords["name"] or "/" in keywords["name"] or keywords["name"] in {".", ".."}:
                raise ValueError("Native object name exceeds the saved-tree grammar")
        elif name == "SetCompatLevel":
            if len(values) != 1 or type(values[0]) is not int or keywords:
                raise ValueError("Unsupported compatibility declaration")
        elif name == "AddImportPath":
            if len(values) != 1 or not isinstance(values[0], str) or keywords:
                raise ValueError("Unsupported import path declaration")
        elif name == "ImportString":
            if len(values) != 2 or not all(isinstance(value, str) for value in values) or keywords:
                raise ValueError("Unsupported embedded data declaration")
    return tree, settings


def compare_setting_transcript(baseline: bytes, observed: bytes,
                               changes: list[dict[str, Any]]) -> dict[str, str] | None:
    """Return complete state seals, or None when the narrow proof is unavailable."""
    try:
        expected_tree, settings = _parse(baseline)
        observed_tree, _ = _parse(observed)
        seen: set[str] = set()
        for change in changes:
            path = change["setting_path"]
            if path in seen or path not in settings:
                return None
            seen.add(path)
            node = settings[path]
            previous = _literal(node.args[1])
            if type(previous) is not type(change["before"]) or previous != change["before"]:
                return None
            replacement = ast.parse(repr(change["after"]), mode="eval").body
            _literal(replacement)
            node.args[1] = deepcopy(replacement)
        expected = ast.dump(expected_tree, include_attributes=False).encode()
        actual = ast.dump(observed_tree, include_attributes=False).encode()
        return {"method": "closed_saved_transcript", "coverage": "complete_native_state",
                "backend_identity": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "expected_native_sha256": hashlib.sha256(ast.unparse(expected_tree).encode()).hexdigest(),
                "expected_state_sha256": hashlib.sha256(expected).hexdigest(),
                "observed_state_sha256": hashlib.sha256(actual).hexdigest()}
    except (ValueError, SyntaxError, UnicodeError, TypeError, KeyError, RecursionError, MemoryError):
        return None
