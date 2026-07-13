from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe


def export_request(request_path: Path, *, formats: list[str]) -> dict[str, Any]:
    """Compile one request to VSZ, then export through the production renderer."""

    from sciplot_core.studio import export_studio_document, prepare_studio_document

    payload = prepare_studio_document(request_path.expanduser().resolve())
    document_path = Path(str(payload["document"]))
    export_payload = export_studio_document(document_path, formats=formats)
    payload["exports"] = export_payload["exports"]
    return payload


def export_document(document_path: Path, *, formats: list[str]) -> dict[str, Any]:
    """Export the exact current VSZ without regenerating it."""

    from sciplot_core.studio import export_studio_document

    return export_studio_document(document_path.expanduser().resolve(), formats=formats)


def audit_documents(document_paths: list[Path]) -> dict[str, Any]:
    """Inspect exact current VSZ state through Veusz without rewriting it."""

    from PyQt6 import QtWidgets

    from sciplot_core.studio import _ensure_veusz_loader_compat, _ensure_veusz_on_path

    _ensure_veusz_on_path()
    from veusz import dataimport, document, widgets

    _ = dataimport, document, widgets
    _ensure_veusz_loader_compat()
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        from sciplot_core.veusz_audit import audit_veusz_documents

        return audit_veusz_documents([path.expanduser().resolve() for path in document_paths])
    finally:
        if existing_app is None:
            app.quit()


def _split_formats(value: str) -> list[str]:
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    return formats or ["pdf", "tiff_300"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal SciPlot Veusz export worker.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export", help="Generate and export a Veusz document from a request.")
    export_parser.add_argument("request", type=Path)
    export_parser.add_argument("--formats", default="pdf,tiff_300")
    export_document_parser = subparsers.add_parser("export-document", help="Export an existing Veusz document.")
    export_document_parser.add_argument("document", type=Path)
    export_document_parser.add_argument("--formats", default="pdf,tiff_300")
    audit_parser = subparsers.add_parser("audit-documents", help="Audit exact current Veusz documents.")
    audit_parser.add_argument("documents", nargs="+", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "export":
        payload = export_request(args.request, formats=_split_formats(args.formats))
    elif args.command == "export-document":
        payload = export_document(args.document, formats=_split_formats(args.formats))
    else:
        payload = audit_documents(args.documents)
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["audit_documents", "export_document", "export_request", "main"]
