"""Thin local CLI adapter for project-bound PDF annotation references."""

from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.visual_review.pdf_review_binding import create_pdf_review, read_pdf_review


def dispatch_pdf_review(args: Any) -> int:
    if args.pdf_review_action == "create":
        payload = create_pdf_review(args.target, review_dir=args.out, figure_id=args.figure)
    elif args.pdf_review_action == "read":
        payload = read_pdf_review(args.target, review_id=args.review_id)
    else:
        raise ValueError("Unknown PDF review action.")
    _print_json(payload)
    return 0
