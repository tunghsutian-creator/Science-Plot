from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sciplot_core.qa import run_qa
from sciplot_core.render import inspect_payload, render_to_dir
from sciplot_recipes import run_recipe


def _coerce_sheet(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def _load_options(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    if value.startswith("@"):
        return json.loads(Path(value[1:]).expanduser().read_text(encoding="utf-8"))
    return json.loads(value)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sciplot", description="Headless SciPlot plotting and recipe CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a source and return ranked plot recommendations.")
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.add_argument("--sheet", default="0")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    render_parser = subparsers.add_parser("render", help="Render a source through the SciPlot renderer.")
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument("--template", required=True)
    render_parser.add_argument("--sheet", default="0")
    render_parser.add_argument("--options", help="JSON object or @path JSON file with render options.")
    render_parser.add_argument("--out", type=Path, required=True)

    recipe_parser = subparsers.add_parser("recipe", help="Run an experiment-family recipe.")
    recipe_parser.add_argument("name")
    recipe_parser.add_argument("input", type=Path)
    recipe_parser.add_argument("--options", help="JSON object or @path JSON file with recipe/render options.")
    recipe_parser.add_argument("--out", type=Path, required=True)

    qa_parser = subparsers.add_parser("qa", help="Validate rendered SciPlot outputs.")
    qa_parser.add_argument("output_dir", type=Path)
    qa_parser.add_argument("--goldens", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            payload = inspect_payload(args.input.expanduser(), sheet=_coerce_sheet(args.sheet))
            if args.json:
                _print_json(payload)
            else:
                print(payload.get("recommendation_summary", "No recommendation summary available."))
            return 0
        if args.command == "render":
            payload = render_to_dir(
                args.input.expanduser(),
                template=args.template,
                output_dir=args.out.expanduser(),
                sheet=_coerce_sheet(args.sheet),
                options=_load_options(args.options),
            )
            _print_json(payload)
            return 0
        if args.command == "recipe":
            payload = run_recipe(
                args.name,
                args.input.expanduser(),
                output_dir=args.out.expanduser(),
                options=_load_options(args.options),
            )
            _print_json(payload)
            return 0
        if args.command == "qa":
            _print_json(
                run_qa(
                    args.output_dir.expanduser(),
                    goldens_dir=args.goldens.expanduser() if args.goldens else None,
                )
            )
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
