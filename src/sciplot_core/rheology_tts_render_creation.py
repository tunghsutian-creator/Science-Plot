"""Resume source-bound native creation without regenerating a saved document."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.rheology_tts_spec import _identifier
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.runtime import _export_suffix
from sciplot_core.studio_core.source_update_commit import reject_symlink_path

_KIND = "sciplot_rheology_tts_creation_checkpoint"
_FORMATS = ("pdf", "tiff_300", "png_300")


def _ordinary(path: Path, *, directory: bool = False) -> None:
    reject_symlink_path(path)
    if path.exists():
        valid = path.is_dir() if directory else path.is_file() and path.stat().st_nlink == 1
        if not valid:
            raise ValueError(f"Native creation requires an ordinary {'directory' if directory else 'unaliased file'}: {path}")


def _names(identifier: str) -> dict[str, str]:
    return {fmt: identifier + _export_suffix(fmt)[0] for fmt in _FORMATS} | {
        "audit": f"{identifier}.native-audit.json"}


def _new_json(path: Path, value: dict[str, Any]) -> None:
    """Publish initial evidence exclusively, without replacing a concurrent file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent, prefix=".creation-") as directory:
        temporary = atomic_write_json(Path(directory) / path.name, value)
        os.link(temporary, path)


def _inventory(out: Path, identifiers: list[str]) -> None:
    _ordinary(out, directory=True)
    checkpoint_dir = out / ".creation"
    _ordinary(checkpoint_dir, directory=True)
    allowed = {name for identifier in identifiers for name in (
        f"{identifier}.vsz", f"{identifier}.spec.json", *_names(identifier).values())}
    if out.exists():
        for path in out.iterdir():
            if path.name == ".creation":
                continue
            if path.name not in allowed:
                raise ValueError(f"Unrecognized native creation partial; preserve and inspect: {path}")
            _ordinary(path)
    if checkpoint_dir.exists():
        allowed_checkpoints = {name for identifier in identifiers
                               for name in (f"{identifier}.json", f"{identifier}.exports", f"{identifier}.saving")}
        for path in checkpoint_dir.iterdir():
            if path.name not in allowed_checkpoints:
                raise ValueError(f"Unrecognized native creation checkpoint partial; preserve and inspect: {path}")
            _ordinary(path, directory=path.name.endswith((".exports", ".saving")))
        for identifier in identifiers:
            saving = checkpoint_dir / f"{identifier}.saving"
            if saving.exists():
                if _read_json(checkpoint_dir / f"{identifier}.json").get("state") != "saving":
                    raise ValueError(f"Unbound native saving candidate: {saving}")
                for candidate in saving.iterdir():
                    if candidate.name != f"{identifier}.vsz":
                        raise ValueError(f"Unrecognized native saving candidate: {candidate}")
                    _ordinary(candidate)
            root = checkpoint_dir / f"{identifier}.exports"
            if not root.exists():
                continue
            state = _read_json(checkpoint_dir / f"{identifier}.json")
            attempts = _attempts(state)
            for stage in root.iterdir():
                if stage.name not in attempts:
                    raise ValueError(f"Unrecognized native export attempt: {stage}")
                _ordinary(stage, directory=True)
                for directory in stage.iterdir():
                    if directory.name not in {"exports", "logs"}:
                        raise ValueError(f"Unrecognized native export attempt directory: {directory}")
                    _ordinary(directory, directory=True)
                    allowed = (_names(identifier).values() if directory.name == "exports"
                               else {"veusz_export_stderr.log"})
                    for artifact in directory.iterdir():
                        suffixes = "|".join(re.escape(_export_suffix(fmt)[0]) for fmt in _FORMATS)
                        partial = (directory.name == "exports" and stage.name != state.get("sealed_attempt")
                                   and re.fullmatch(rf"\.{identifier}\.[0-9a-f]{{32}}({suffixes})", artifact.name))
                        if artifact.name not in allowed and not partial:
                            raise ValueError(f"Unrecognized native export partial: {artifact}")
                        _ordinary(artifact)


def _attempts(state: dict[str, Any]) -> list[str]:
    attempts = state.get("attempts")
    if (not isinstance(attempts, list) or any(not isinstance(item, str) or len(item) != 32
            or any(char not in "0123456789abcdef" for char in item) for item in attempts)
            or len(set(attempts)) != len(attempts)):
        raise ValueError("Invalid native creation export attempts; preserve and inspect.")
    return attempts


def _stage(out: Path, identifier: str, attempt: str) -> Path:
    return out / ".creation" / f"{identifier}.exports" / attempt / "exports"


def _check_sources(spec: dict[str, Any]) -> None:
    binding = spec["source_binding"]
    sources = binding.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("Native creation requires a list of explicit source bindings.")
    if "prepared_plan" in binding:
        sources = [*sources, binding["prepared_plan"]]
    for source in sources:
        if not isinstance(source, dict) or not {"path", "sha256"} <= source.keys():
            raise ValueError("Native creation source binding requires path and SHA256.")
        path = Path(source["path"])
        if not path.is_absolute() or not path.is_file() or file_sha256(path) != source["sha256"]:
            raise ValueError(f"Native creation source changed; preserve the saved documents: {path}")


def _sidecar(spec: dict[str, Any], figure: dict[str, Any]) -> dict[str, Any]:
    return {"kind": spec["kind"], "version": 1, "source_binding": spec["source_binding"],
            "transform_ledger": spec["transform_ledger"], "figure": figure}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid native creation evidence; preserve and inspect: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid native creation evidence object: {path}")
    return value


def _same_json(left: object, right: object) -> bool:
    return canonical_json_sha256(left, allow_nan=False) == canonical_json_sha256(right, allow_nan=False)


def _check_receipt(state: dict[str, Any], out: Path, identifier: str, *, native_out: Path | None = None) -> None:
    receipt, artifacts, names = state["receipt"], state["artifacts"], _names(identifier)
    native_out = native_out or out
    if not isinstance(receipt, dict) or set(artifacts) != set(names.values()):
        raise ValueError(f"Incomplete sealed native creation receipt: {identifier}")
    if any(receipt.get(key) != value for key, value in {
        "id": identifier, "spec_path": str(native_out / f"{identifier}.spec.json"),
        "document": str(native_out / f"{identifier}.vsz"), "document_sha256": state["document_sha256"],
        "export_dir": str(out), "native_audit_path": str(out / names["audit"]),
    }.items()):
        raise ValueError(f"Native creation receipt bindings changed: {identifier}")
    exports = receipt.get("exports")
    if (not isinstance(exports, list) or len(exports) != len(_FORMATS)
            or any(not isinstance(item, dict) or item.get("format") not in _FORMATS for item in exports)):
        raise ValueError(f"Incomplete native creation export set: {identifier}")
    by_format = {item.get("format"): item for item in exports if isinstance(item, dict)}
    if set(by_format) != set(_FORMATS):
        raise ValueError(f"Invalid native creation export formats: {identifier}")
    for fmt in _FORMATS:
        item = by_format[fmt]
        if item.get("path") != str(out / names[fmt]) or item.get("sha256") != artifacts[names[fmt]]:
            raise ValueError(f"Native creation export binding changed: {identifier}")
    audit = receipt.get("native_audit")
    if (not isinstance(audit, dict) or audit.get("status") != "passed"
            or audit.get("document") != receipt["document"]
            or audit.get("document_sha256") != state["document_sha256"]):
        raise ValueError(f"Native creation audit binding changed: {identifier}")
    audit_path = out / names["audit"]
    if audit_path.exists() and not _same_json(_read_json(audit_path), audit):
        raise ValueError(f"Native creation audit content changed: {identifier}")


def _read_state(
    out: Path, identifier: str, binding: dict[str, Any], expected_spec: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    checkpoint = out / ".creation" / f"{identifier}.json"
    document, sidecar = out / f"{identifier}.vsz", out / f"{identifier}.spec.json"
    names = _names(identifier)
    if not checkpoint.exists():
        if any((out / name).exists() for name in (document.name, sidecar.name, *names.values())):
            raise ValueError(f"Native files lack a valid creation checkpoint; preserve and inspect: {identifier}")
        return None, False
    state = _read_json(checkpoint)
    if (set(state) != {"kind", "version", "binding", "state", "spec_sha256", "document_sha256",
                      "artifacts", "receipt", "attempts", "sealed_attempt"}
            or state["kind"] != _KIND or type(state["version"]) is not int
            or state["version"] != 1 or state["binding"] != binding
            or state["state"] not in ("saving", "saved", "completed")):
        raise ValueError(f"Native creation checkpoint or source/spec binding changed: {identifier}")
    attempts = _attempts(state)
    if state["state"] == "saving":
        raise ValueError(f"Uncertain native Save; preserve the checkpoint and inspect instead of regenerating: {identifier}")
    if (not sidecar.is_file() or file_sha256(sidecar) != state["spec_sha256"]
            or not _same_json(_read_json(sidecar), expected_spec)):
        raise ValueError(f"Saved native specification changed or missing: {identifier}")
    if not document.is_file() or file_sha256(document) != state["document_sha256"]:
        raise ValueError(f"Saved native document changed or missing; regeneration is blocked: {identifier}")
    artifacts = state["artifacts"]
    if not isinstance(artifacts, dict) or not set(artifacts) <= set(names.values()):
        raise ValueError(f"Invalid native creation artifact inventory: {identifier}")
    if state["state"] == "completed" or artifacts or state["receipt"] is not None:
        _check_receipt(state, out, identifier)
        if state["sealed_attempt"] not in attempts:
            raise ValueError(f"Invalid sealed native export attempt: {identifier}")
        stage = _stage(out, identifier, state["sealed_attempt"])
        for name, digest in artifacts.items():
            candidate = stage / name
            if not candidate.is_file() or file_sha256(candidate) != digest:
                raise ValueError(f"Sealed native export changed or missing: {candidate}")
        if not _same_json(_read_json(stage / names["audit"]), state["receipt"]["native_audit"]):
            raise ValueError(f"Sealed native audit content differs from its receipt: {identifier}")
    elif state["sealed_attempt"] is not None:
        raise ValueError(f"Unbound sealed native export attempt: {identifier}")
    missing = False
    for name in names.values():
        path = out / name
        if path.exists():
            if name not in artifacts or file_sha256(path) != artifacts[name]:
                raise ValueError(f"Changed or unsealed native export; preserve and inspect: {path}")
        elif name in artifacts:
            missing = True
    return state, missing


def _publish_exports(out: Path, identifier: str, state: dict[str, Any]) -> None:
    """Install sealed copies without replacing any existing destination."""
    stage = _stage(out, identifier, state["sealed_attempt"])
    for name, digest in state["artifacts"].items():
        target, source = out / name, stage / name
        _ordinary(target)
        _ordinary(source)
        if file_sha256(source) != digest:
            raise ValueError(f"Sealed native export changed during publication: {source}")
        if target.exists():
            if file_sha256(target) != digest:
                raise ValueError(f"Native creation export changed; publication blocked: {target}")
            continue
        # Link a fully flushed private copy for an atomic, no-replace publication.
        # A killed process leaving its private copy remains an unknown partial.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=out, prefix=".creation-", delete=False) as handle:
                temporary = Path(handle.name)
                with source.open("rb") as data:
                    shutil.copyfileobj(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            if file_sha256(temporary) != digest:
                raise ValueError(f"Sealed native export changed while copying: {source}")
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _stage_exports(spec: dict[str, Any], out: Path, figure: dict[str, Any], state: dict[str, Any],
                   export_figure: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    identifier, attempt = figure["id"], uuid4().hex
    checkpoint = out / ".creation" / f"{identifier}.json"
    state = {**state, "attempts": [*state["attempts"], attempt]}
    atomic_write_json(checkpoint, state)
    stage = _stage(out, identifier, attempt)
    stage.mkdir(parents=True)
    path, spec_path = out / f"{identifier}.vsz", out / f"{identifier}.spec.json"
    exported = export_figure(path, stage, figure, check_presentation=True)
    _inventory(out, [item["id"] for item in spec["figures"]])
    _check_sources(spec)
    if not _same_json(_read_json(checkpoint), state):
        raise ValueError(f"Native creation checkpoint changed during export: {identifier}")
    if file_sha256(path) != state["document_sha256"] or file_sha256(spec_path) != state["spec_sha256"]:
        raise ValueError(f"Saved native document/spec changed during creation export: {identifier}")
    artifacts = {name: file_sha256(stage / name) for name in _names(identifier).values()}
    staged_receipt = {"id": identifier, "spec_path": str(spec_path), **exported}
    # Validate worker paths before rebinding exports into their final directory.
    _check_receipt({**state, "receipt": staged_receipt, "artifacts": artifacts},
                   stage, identifier, native_out=out)
    receipt = {**staged_receipt, "export_dir": str(out),
               "native_audit_path": str(out / _names(identifier)["audit"]),
               "exports": [{**item, "path": str(out / _names(identifier)[item["format"]])}
                           for item in exported["exports"]]}
    return {**state, "receipt": receipt, "artifacts": artifacts, "sealed_attempt": attempt}


def _context(spec: dict[str, Any], out: Path) -> tuple[list[str], list[dict], list[dict]]:
    identifiers = [_identifier(figure["id"]) for figure in spec["figures"]]
    if len(set(name.casefold() for name in identifiers)) != len(identifiers):
        raise ValueError("Native creation figure names must be unique, including case.")
    plan_sha = canonical_json_sha256(spec, allow_nan=False)
    bindings = [{"out": str(out), "plan_sha256": plan_sha, "figure_id": identifier}
                for identifier in identifiers]
    return identifiers, bindings, [_sidecar(spec, figure) for figure in spec["figures"]]


def _read_states(out: Path, context: tuple[list[str], list[dict], list[dict]]) -> list[tuple[dict | None, bool]]:
    identifiers, bindings, expected_specs = context
    _inventory(out, identifiers)
    return [_read_state(out, identifier, binding, sidecar)
            for identifier, binding, sidecar in zip(identifiers, bindings, expected_specs, strict=True)]


def _completed_result(out: Path, context: tuple[list[str], list[dict], list[dict]]) -> dict[str, Any]:
    final = _read_states(out, context)
    if any(state is None or state["state"] != "completed" or missing for state, missing in final):
        raise ValueError("Native creation outputs are incomplete; inspect and explicitly resume.")
    return {"kind": "sciplot_rheology_tts_render", "version": 1, "status": "completed",
            "figures": [state["receipt"] for state, _ in final]}


def check_native_continuation(compiled_spec: dict[str, Any], out: Path, *, completed: bool = False) -> dict | None:
    """Reuse creation guards without allocating files or a lease; caller owns its lease."""
    reject_symlink_path(out)
    _check_sources(compiled_spec)
    context = _context(compiled_spec, out)
    result = _completed_result(out, context) if completed else None
    if not completed:
        _read_states(out, context)
    _check_sources(compiled_spec)
    return result


def verify_native_creation(compiled_spec: dict[str, Any], out: Path) -> dict[str, Any]:
    """Read-only validation of a complete native checkpoint set; never render."""
    reject_symlink_path(out)
    out = out.resolve()
    with external_project_session(out):
        return check_native_continuation(compiled_spec, out, completed=True)


def render_native_creation(
    spec: dict[str, Any], out: Path, *, resume: bool,
    export_figure: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Create each VSZ at most once; durable uncertain Save states fail closed."""
    from sciplot_core.rheology_tts_native import save_native_figure

    if not isinstance(resume, bool):
        raise ValueError("Native creation resume must be a boolean.")
    reject_symlink_path(out)
    out = out.resolve()
    context = identifiers, bindings, expected_specs = _context(spec, out)
    _check_sources(spec)
    out.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(out):
        _inventory(out, identifiers)
        if not resume and out.exists() and any(path.is_file() for path in out.rglob("*")):
            raise FileExistsError("Native creation evidence already exists; use explicit resume or exact saved export.")
        _read_states(out, context)
        out.mkdir(parents=True, exist_ok=True)
        for figure, binding, sidecar in zip(
            spec["figures"], bindings, expected_specs, strict=True,
        ):
            identifier = figure["id"]
            path, spec_path = out / f"{identifier}.vsz", out / f"{identifier}.spec.json"
            checkpoint = out / ".creation" / f"{identifier}.json"
            _check_sources(spec)
            _inventory(out, identifiers)
            state, missing = _read_state(out, identifier, binding, sidecar)
            if state is None:
                # Durable saving precedes Save: a missing VSZ after this point
                # is uncertainty, never permission to create the document again.
                _new_json(spec_path, sidecar)
                state = {"kind": _KIND, "version": 1, "binding": binding, "state": "saving",
                         "spec_sha256": file_sha256(spec_path), "document_sha256": None,
                         "artifacts": {}, "receipt": None, "attempts": [], "sealed_attempt": None}
                _new_json(checkpoint, state)
                saving = checkpoint.parent / f"{identifier}.saving"
                saving.mkdir()
                candidate = saving / path.name
                save_native_figure(figure, candidate)
                _ordinary(candidate)
                os.link(candidate, path)
                candidate.unlink()
                saving.rmdir()
                _inventory(out, identifiers)
                _check_sources(spec)
                if not _same_json(_read_json(checkpoint), state):
                    raise ValueError(f"Native creation checkpoint changed during Save: {identifier}")
                state = {**state, "state": "saved", "document_sha256": file_sha256(path)}
                atomic_write_json(checkpoint, state)
            if state["state"] == "completed" and not missing:
                continue
            if state["receipt"] is None:
                state = _stage_exports(spec, out, figure, state, export_figure)
                atomic_write_json(checkpoint, state)
            _publish_exports(out, identifier, state)
            if not _same_json(_read_json(checkpoint), state):
                raise ValueError(f"Native creation checkpoint changed during publication: {identifier}")
            atomic_write_json(checkpoint, {**state, "state": "completed"})
        _check_sources(spec)
        return _completed_result(out, context)
