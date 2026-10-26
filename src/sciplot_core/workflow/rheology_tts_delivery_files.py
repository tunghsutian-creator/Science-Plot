"""Assemble private delivery files from exact native receipts and declared host paths."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import shlex
import shutil
from sciplot_core._paths import REPO_ROOT
from sciplot_core.workflow.rheology_tts_saved_state import _sha, _figure_folder

def launcher_bytes(arguments: list[str]) -> bytes:
    command = [str(REPO_ROOT / "skill/scripts/sciplot"), *arguments]
    return ("#!/bin/zsh\nset -e\nexec " + " ".join(shlex.quote(value) for value in command) + "\n").encode()


def _launcher(path: Path, arguments: list[str]) -> None:
    path.write_bytes(launcher_bytes(arguments))
    path.chmod(0o755)


def _output_paths(source: Path, requested: str | Path) -> tuple[Path, Path]:
    """Allow new sibling suites and an explicit revision inside an existing suite."""
    delivery = Path(requested).expanduser().resolve()
    parent = source.parent
    if delivery.parent != parent:
        previous_manifest = delivery.parent / "data" / "delivery_manifest.json"
        if delivery.parent.parent != parent or not previous_manifest.is_file():
            raise ValueError("TTS output must be beside its original data or a new revision inside an existing source-adjacent suite.")
        previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
        original_paths = {Path(s["path"]).resolve() for s in previous.get("sources", [])}
        if previous.get("kind") != "sciplot_rheology_tts_suite" or source not in original_paths:
            raise ValueError("Revision parent is not a source-bound suite for this frequency source.")
    if delivery == parent or ".sciplot" in delivery.relative_to(parent).parts:
        raise ValueError("Visible delivery must be a dedicated folder outside hidden evidence.")
    relative_name = "__".join(delivery.relative_to(parent).parts)
    return delivery, parent / ".sciplot" / relative_name


def _publish(stage: Path, delivery: Path, spec: dict[str, Any], native_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy known new outputs; visible native files become the sole edit authority."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path

    reject_symlink_path(stage)
    reject_symlink_path(delivery)
    # Creation checkpoints retain sealed and failed exports below .creation.
    # Those historical bytes are not another candidate for visible publication.
    for item in stage.iterdir():
        reject_symlink_path(item)
        if item.is_dir() and item.name != ".creation":
            raise ValueError(f"Unexpected nested native publication output: {item}")

    def bound_file(name: str, receipt_path: str, digest: str) -> Path:
        path = stage / name
        reject_symlink_path(path)
        if (not path.is_file() or path.stat().st_nlink != 1
                or Path(receipt_path) != path or _sha(path) != digest):
            raise ValueError(f"Missing, changed or aliased receipt-bound native output: {path}")
        return path

    receipts = native_result["figures"]
    by_id = {r["id"]: r for r in receipts}
    expected_ids = [f["id"] for f in spec["figures"]]
    if len(by_id) != len(receipts) or set(by_id) != set(expected_ids):
        raise ValueError("Native render receipts do not match the selected figure set.")
    prepared = []
    # Check the complete set before publishing any figure, including missing TIFFs.
    for identifier in expected_ids:
        receipt = by_id[identifier]
        native = bound_file(identifier + ".vsz", receipt["document"], receipt["document_sha256"])
        expected_names = {identifier + suffix for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png")}
        exported = {Path(r["path"]).name: r for r in receipt["exports"]}
        if len(exported) != len(receipt["exports"]) or set(exported) != expected_names:
            raise ValueError(f"Expected exactly PDF, TIFF and PNG receipts for {identifier}.")
        sources = []
        for name in sorted(expected_names):
            digest = exported[name]["sha256"]
            sources.append((bound_file(name, exported[name]["path"], digest), digest))
        prepared.append((identifier, native, receipt["document_sha256"], sources))
    documents = []
    for identifier, source_native, native_sha, sources in prepared:
        native = delivery / "editable" / f"{identifier}.vsz"
        native.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_native, native)
        if _sha(native) != native_sha or _sha(source_native) != native_sha:
            raise RuntimeError(f"Native delivery byte mismatch: {native}")
        destination = _figure_folder(delivery, identifier)
        destination.mkdir(parents=True, exist_ok=True)
        files = []
        for path, digest in sources:
            target = destination / path.name
            shutil.copy2(path, target)
            if _sha(target) != digest or _sha(path) != digest:
                raise RuntimeError(f"Delivery byte mismatch: {target}")
            files.append(str(target))
        documents.append({"id": identifier, "path": str(native), "sha256": _sha(native), "exports": files})
        _launcher(delivery / "editable" / f"Open_{identifier}.command", ["studio", str(native)])
    return documents
