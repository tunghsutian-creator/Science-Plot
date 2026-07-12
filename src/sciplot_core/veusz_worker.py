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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "export":
        payload = export_request(args.request, formats=_split_formats(args.formats))
    else:
        payload = export_document(args.document, formats=_split_formats(args.formats))
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["export_document", "export_request", "main"]
