"""Publish one audited Managed artifact tree to its separately bound public output."""

import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.project_store.io import directory, install, read_file
from sciplot_core.studio_core.source_update_files import file_inventory

from .attachment_projection import path_metadata_view
from .attachment_sources import capture_source
from .context import exists, json_members, read, write
from .errors import EngineError
from .paths import canonical_path


def _paths(binding: dict[str, Any], output: Path) -> tuple[Path, Path, Path]:
    native = canonical_path(Path(binding["document"]))
    if native.relative_to(Path(binding["output"])).parts != ("artifacts", binding["ir_hash"], "document.vsz"):
        raise EngineError("managed_publication_binding_invalid", "Publication requires the exact existing Managed artifact layout.")
    return (native.parent, canonical_path(output / "artifacts" / binding["ir_hash"]),
            Path(binding["root"]) / "artifact-projections" / (binding["ir_hash"] + ".json"))


def _prior(receipt: Path, target: Path) -> dict[str, Any]:
    if not exists(receipt):
        return {}
    value = read(receipt)
    if (value.get("kind") != "sciplot_managed_artifact_projection" or value.get("version") != 1
            or value.get("target") != str(target)):
        raise EngineError("managed_publication_binding_invalid", "The saved artifact receipt does not own this output.")
    return value


def visible_native_changed(binding: dict[str, Any], output: Path) -> bool:
    """Edits to an already published VSZ retain the original mutation refusal."""
    from sciplot_core.foundation.file_hashing import existing_file_sha256

    _private, target, receipt = _paths(binding, output)
    prior = _prior(receipt, target)
    native = canonical_path(target / "document.vsz")
    if not prior or not native.exists():
        return False  # A missing disposable view is recoverable, never authoritative.
    allowed = {prior.get(field, {}).get("document.vsz") for field in ("members", "preimage")}
    return existing_file_sha256(native) not in allowed


def _inventory(path: Path) -> dict[str, str]:
    canonical_path(path)
    if not path.exists():
        return {}
    if not path.is_dir():
        raise EngineError("managed_output_conflict", "The selected Managed artifact namespace is not a directory.")
    try:
        return file_inventory(path)
    except ValueError:
        if any(path.iterdir()):
            raise
        return {}


def _capture(private: Path, exported: dict[str, Any]) -> dict[str, tuple[bytes, int]]:
    if exported.get("status") != "exported" or exported.get("ready_to_use") is not True:
        raise EngineError("managed_publication_artifacts_invalid", "Only an audited complete export can be published.")
    inventory = file_inventory(private)
    for fmt, name in (("vsz", "document.vsz"), ("pdf", None), ("tiff_300", None)):
        items = [item for item in exported["exports"] if item.get("format") == fmt]
        if len(items) != 1:
            raise EngineError("managed_publication_artifacts_invalid", "Expected one audited VSZ, PDF and TIFF.")
        item = items[0]
        source = canonical_path(Path(item["path"]))
        relative = source.relative_to(private)
        if (name is not None and relative.as_posix() != name
                or name is None and relative.parent != Path("exports")
                or inventory.get(relative.as_posix()) != exported["evidence_files"].get(str(source))
                or item.get("sha256") != inventory.get(relative.as_posix())):
            raise EngineError("managed_publication_artifacts_invalid", "The artifact does not match the complete native export receipt.")
    captured = {name: capture_source(private / name) for name in inventory}
    if ({name: hashlib.sha256(content).hexdigest() for name, (content, _) in captured.items()} != inventory
            or file_inventory(private) != inventory):
        raise EngineError("managed_publication_artifacts_invalid", "The audited artifact inventory changed during capture.")
    return captured


def _install_tree(target: Path, files: dict[str, tuple[bytes, int]], *, allowed: dict[str, str]) -> None:
    if not target.exists():
        with TemporaryDirectory(prefix=".sciplot-artifact-", dir=target.parent) as temp:
            staged = Path(temp) / "artifact"
            staged.mkdir()
            _install_tree(staged, files, allowed={})
            install_new_delivery(staged, target)
        return
    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, (content, mode) in files.items():
            relative = Path(name)
            with directory(fd, relative.parts[:-1], create=True) as parent:
                current = allowed.get(name)
                if current is not None and hashlib.sha256(read_file(parent, relative.name)[0]).hexdigest() != current:
                    raise EngineError("managed_output_conflict", "A published artifact changed before replacement.")
                if current != hashlib.sha256(content).hexdigest():
                    install(parent, relative.name, content, mode=mode, exclusive=current is None)
    finally:
        os.close(fd)


def publish_managed_artifacts(binding: dict[str, Any], output: Path, exported: dict[str, Any]) -> dict[str, Any]:
    """Project the exact export with the existing attached journal and host installer."""
    private, target, receipt = _paths(binding, output)
    files = _capture(private, exported)
    members = {name: hashlib.sha256(content).hexdigest() for name, (content, _) in files.items()}
    require_data_destination(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(output):
        root = canonical_path(output)
        previous = _prior(receipt, target)
        known = previous.get("members", {})
        preimage = previous.get("preimage", {})
        actual = _inventory(target)
        other_receipts = [item for item in json_members(receipt.parent, "*.json") if item != receipt]
        if ((not previous and not other_receipts and root.exists() and any(root.iterdir()))
                or any(digest not in {known.get(name), preimage.get(name)} for name, digest in actual.items())
                or not set(actual).issubset(members)):
            raise EngineError("managed_output_conflict", "The public artifact directory contains changed or unowned files; it was preserved.")
        intent = {"kind": "sciplot_managed_artifact_projection", "version": 1,
                  "target": str(target), "members": members, "preimage": actual}
        # If interrupted between any physical replacements, exactly the
        # recorded old/new bytes may be present; no outside bytes gain authority.
        write(receipt, intent)
        target.parent.mkdir(parents=True, exist_ok=True)
        _install_tree(target, files, allowed=actual)
        if _inventory(target) != members:
            raise EngineError("managed_output_conflict", "The installed public artifacts do not match the audited contents.")
        write(receipt, {**intent, "preimage": {}})

    def relocate(value: str) -> str:
        if value.startswith("/"):
            path = Path(value)
            if path.is_relative_to(private):
                return str(target / path.relative_to(private))
        return value

    result = dict(path_metadata_view(exported, relocate))
    # The native delivery owner still verifies the canonical local VSZ. Public
    # cache currentness also requires every visible projection byte.
    result["evidence_files"] = {**exported["evidence_files"],
                                **{str(target / name): sha for name, sha in members.items()}}
    return result
