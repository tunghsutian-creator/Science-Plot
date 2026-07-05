from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe


def export_request(request_path: Path, *, formats: list[str]) -> dict[str, Any]:
    from sciplot_core.studio import export_studio_document, prepare_studio_document

    payload = prepare_studio_document(request_path)
    document_path = Path(str(payload["document"]))
    export_payload = export_studio_document(document_path, formats=formats)
    payload["exports"] = export_payload["exports"]
    return payload


def _split_formats(value: str) -> list[str]:
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    return formats or ["pdf", "tiff_300"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal SciPlot Veusz rendering worker.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export", help="Generate and export a Veusz document from a request.")
    export_parser.add_argument("request", type=Path)
    export_parser.add_argument("--formats", default="pdf,tiff_300")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "export":
        payload = export_request(args.request.expanduser(), formats=_split_formats(args.formats))
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["export_request", "main"]
