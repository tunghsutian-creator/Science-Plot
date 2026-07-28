"""Parse and dispatch the internal Veusz worker command line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.veusz_worker.operations import (
    export_request,
    export_document,
    audit_documents,
    inspect_document_state,
    migrate_unit_labels,
)
from sciplot_core.veusz_worker.save import (
    save_spec,
)
from sciplot_core.veusz_worker.spec_audit import audit_spec_data


def _split_formats(value: str) -> list[str]:
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    return formats or ["pdf", "tiff_300"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Internal SciPlot Veusz export worker."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser(
        "export", help="Generate and export a Veusz document from a request."
    )
    export_parser.add_argument("request", type=Path)
    export_parser.add_argument("--formats", default="pdf,tiff_300")
    export_document_parser = subparsers.add_parser(
        "export-document", help="Export an existing Veusz document."
    )
    export_document_parser.add_argument("document", type=Path)
    export_document_parser.add_argument("--formats", default="pdf,tiff_300")
    export_document_parser.add_argument("--out", type=Path)
    audit_parser = subparsers.add_parser(
        "audit-documents", help="Audit exact current Veusz documents."
    )
    audit_parser.add_argument("documents", nargs="+", type=Path)
    spec_data_audit_parser = subparsers.add_parser(
        "audit-spec-data",
        help="Verify that an exact-current VSZ consumes one SciPlot data spec.",
    )
    spec_data_audit_parser.add_argument("document", type=Path)
    spec_data_audit_parser.add_argument("spec", type=Path)
    save_spec_parser = subparsers.add_parser(
        "save-spec", help="Generate a VSZ from a SciPlot Veusz spec."
    )
    save_spec_parser.add_argument("document", type=Path)
    save_spec_parser.add_argument("spec", type=Path)
    inspect_state_parser = subparsers.add_parser(
        "inspect-document-state",
        help="Reopen a VSZ and materialize its widget settings.",
    )
    inspect_state_parser.add_argument("document", type=Path)
    migrate_unit_labels_parser = subparsers.add_parser(
        "migrate-unit-labels",
        help="Normalize visible unit labels in an existing Veusz document.",
    )
    migrate_unit_labels_parser.add_argument("document", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "export":
        payload = export_request(args.request, formats=_split_formats(args.formats))
    elif args.command == "export-document":
        payload = export_document(
            args.document,
            formats=_split_formats(args.formats),
            output_dir=args.out,
        )
    elif args.command == "audit-documents":
        payload = audit_documents(args.documents)
    elif args.command == "audit-spec-data":
        payload = audit_spec_data(args.document, args.spec)
    elif args.command == "inspect-document-state":
        payload = inspect_document_state(args.document)
    elif args.command == "migrate-unit-labels":
        payload = migrate_unit_labels(args.document)
    else:
        payload = save_spec(args.document, args.spec)
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0
