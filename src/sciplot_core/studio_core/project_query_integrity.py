"""Read-only integrity checks for native documents and exported figures."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.project_store.runtime import literal_runtime_path, projected_runtime_artifact


def _documents_match(
    project: Path, run: Path, manifest: dict[str, Any], figures: list[dict[str, Any]]
) -> bool:
    recorded = manifest.get("veusz_document_hashes")
    if not isinstance(recorded, dict) or len(recorded) != len(figures):
        return False
    expected_paths = set()
    for figure in figures:
        document = canonical_path(run / Path(figure["document"]).relative_to(project))
        spec = canonical_path(run / Path(figure["spec"]).relative_to(project))
        literal = literal_runtime_path(document)
        expected_paths.add(literal)
        if (
            figure["document_sha256"] is None
            or recorded.get(literal) != figure["document_sha256"]
            or existing_file_sha256(document) != figure["document_sha256"]
            or existing_file_sha256(spec) != figure["spec_sha256"]
        ):
            return False
    return set(recorded) == expected_paths


def _exports_match(
    run: Path, manifest: dict[str, Any], figures: list[dict[str, Any]]
) -> bool:
    qa = manifest.get("qa") or {}
    exports = (manifest.get("result") or {}).get("exports")
    if qa.get("status") != "passed" or not isinstance(exports, list) or not exports:
        return False
    qa_hashes = {
        item.get("path"): item.get("sha256")
        for category in ("pdfs", "tiffs")
        for item in qa.get(category, [])
        if isinstance(item, dict)
    }
    document_formats: dict[str, set[str]] = {}
    seen = set()
    for item in exports:
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            return False
        fmt, digest = item.get("format"), item["sha256"]
        if (not isinstance(fmt, str) or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            return False
        declared = Path(item["path"])
        if not declared.suffix or (fmt == "pdf" and declared.suffix.casefold() != ".pdf"):
            return False
        path = canonical_path(projected_runtime_artifact(declared))
        if not path.is_file():
            return False
        if not path.is_relative_to(run) or str(path) in seen:
            return False
        seen.add(str(path))
        if existing_file_sha256(path) != digest:
            return False
        if fmt in {"pdf", "tiff_300"} and qa_hashes.get(item["path"]) != digest:
            return False
        document_formats.setdefault(str(item.get("document")), set()).add(fmt)
    for figure in figures:
        relative = Path(figure["document"]).relative_to(run.parent.parent)
        if not {"pdf", "tiff_300"}.issubset(
            document_formats.get(literal_runtime_path(run / relative), set())
        ):
            return False
    return True
