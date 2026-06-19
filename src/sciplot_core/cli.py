from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sciplot_core.batch import run_batch
from sciplot_core.curate import curate_torque_project
from sciplot_core.intake import intake_catalog_payload, prepare_intake_session, serve_intake
from sciplot_core.materials_rules import list_rules_payload, show_rule_payload
from sciplot_core.origin_handoff import export_origin_handoff
from sciplot_core.qa import run_qa
from sciplot_core.render import inspect_payload, render_to_dir
from sciplot_core.workflow import run_request
from sciplot_recipes import run_recipe


def _coerce_sheet(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def _resolve_input(path: Path, *, kind: str = "Input") -> Path:
    """Expand and existence-check a user-supplied path before handing it on.

    Produces a clear ``Input not found: PATH`` instead of leaking a raw
    ``[Errno 2]`` from deep in the loader.
    """
    resolved = path.expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"{kind} not found: {path}")
    return resolved


# Substrings that mark a "we couldn't make sense of this table" failure, for
# which a recovery hint is genuinely useful (unlike, say, a bad-template error
# that already lists every valid option).
_RECOGNITION_ERROR_MARKERS = (
    "recognize",
    "numeric curve series",
    "unsupported file format",
    "must match",
    "no numeric",
)


def _recovery_hint(input_path: Path | None) -> str:
    target = str(input_path) if input_path is not None else "<input>"
    return (
        f"Hint: run `sciplot inspect {target} --json` to see how SciPlot read the table, "
        f"reshape it as a 2-column curve / replicate / heatmap table, "
        f"or open it in the workbench with `sciplot intake {target}`."
    )


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
    render_parser.add_argument("--template", help="Template id. Optional when --auto is given.")
    render_parser.add_argument("--sheet", default="0")
    render_parser.add_argument("--options", help="JSON object or @path JSON file with render options.")
    render_parser.add_argument(
        "--auto",
        action="store_true",
        help="Apply the inspected recommendation's scientific defaults "
        "(template, axis scales, reversed axes). Explicit --options still win.",
    )
    render_parser.add_argument("--out", type=Path, required=True)

    recipe_parser = subparsers.add_parser("recipe", help="Run an experiment-family recipe.")
    recipe_parser.add_argument("name")
    recipe_parser.add_argument("input", type=Path)
    recipe_parser.add_argument("--options", help="JSON object or @path JSON file with recipe/render options.")
    recipe_parser.add_argument("--out", type=Path, required=True)

    run_parser = subparsers.add_parser("run", help="Run a plot_request.json workflow.")
    run_parser.add_argument("request", type=Path)

    origin_parser = subparsers.add_parser(
        "origin-handoff",
        help="Export a completed SciPlot run as an OriginPro LabTalk script/data handoff.",
    )
    origin_parser.add_argument("input", type=Path, help="SciPlot run output directory or manifest.json.")
    origin_parser.add_argument("--out", type=Path, help="Output directory. Defaults to RUN_OUTPUT/origin_handoff.")

    quick_parser = subparsers.add_parser("quick", help="Open the shortest confirmation flow for a raw data path.")
    quick_parser.add_argument("input", type=Path)
    quick_parser.add_argument("--host", default="127.0.0.1")
    quick_parser.add_argument("--port", type=int, default=0, help="Use 0 to choose a free local port.")
    quick_parser.add_argument("--out", type=Path, default=Path("outputs") / "intake_projects")
    quick_parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")

    curate_parser = subparsers.add_parser("curate", help="Create a reviewable curation project.")
    curate_subparsers = curate_parser.add_subparsers(dest="curate_command", required=True)
    curate_torque_parser = curate_subparsers.add_parser("torque", help="Curate torque event segments.")
    curate_torque_parser.add_argument("input", type=Path)
    curate_torque_parser.add_argument("--name", required=True, help="User-facing project name.")
    curate_torque_parser.add_argument("--out", type=Path, default=Path("outputs") / "curation_projects")
    curate_torque_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    curate_torque_parser.add_argument("--open", action="store_true", help="Open the review HTML after export.")

    prepare_parser = subparsers.add_parser("prepare", help="Prepare a Codex-first intake session from a path.")
    prepare_parser.add_argument("input", type=Path)
    prepare_parser.add_argument("--out", type=Path, default=Path("outputs") / "intake_projects")
    prepare_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    rules_parser = subparsers.add_parser("rules", help="Inspect SciPlot material semantic rules.")
    rules_subparsers = rules_parser.add_subparsers(dest="rules_command", required=True)
    rules_list_parser = rules_subparsers.add_parser("list", help="List material semantic rules.")
    rules_list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    rules_show_parser = rules_subparsers.add_parser("show", help="Show one material semantic rule.")
    rules_show_parser.add_argument("rule_id")
    rules_show_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    batch_parser = subparsers.add_parser("batch", help="Run a batch over a data folder.")
    batch_parser.add_argument("input_dir", type=Path)
    batch_parser.add_argument("--out", type=Path, required=True)
    batch_parser.add_argument("--mode", choices=["smoke", "all"], default="smoke")
    batch_parser.add_argument(
        "--tensile-root",
        action="append",
        type=Path,
        help="Allow-list tensile data root. Repeat to allow multiple tensile folders.",
    )

    app_parser = subparsers.add_parser("app", help="Open the local SciPlot Web app for manual plotting.")
    app_parser.add_argument("input", nargs="?", type=Path)
    app_parser.add_argument("--catalog", action="store_true", help="Print the intake data type catalog.")
    app_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    app_parser.add_argument("--host", default="127.0.0.1")
    app_parser.add_argument("--port", type=int, default=8765)
    app_parser.add_argument("--out", type=Path, default=Path("outputs") / "intake_projects")
    app_parser.add_argument("--project", help="Open an existing intake project under --out.")
    app_parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")

    intake_parser = subparsers.add_parser("intake", help="Open the SciPlot intake project builder.")
    intake_parser.add_argument("input", nargs="?", type=Path)
    intake_parser.add_argument("--catalog", action="store_true", help="Print the intake data type catalog.")
    intake_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    intake_parser.add_argument("--host", default="127.0.0.1")
    intake_parser.add_argument("--port", type=int, default=8765)
    intake_parser.add_argument("--out", type=Path, default=Path("outputs") / "intake_projects")
    intake_parser.add_argument("--project", help="Open an existing intake project under --out.")
    intake_parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")

    workbench_parser = subparsers.add_parser("workbench", help="Open the SciPlot Codex-aware Web workbench.")
    workbench_parser.add_argument("input", nargs="?", type=Path)
    workbench_parser.add_argument("--catalog", action="store_true", help="Print the intake data type catalog.")
    workbench_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    workbench_parser.add_argument("--host", default="127.0.0.1")
    workbench_parser.add_argument("--port", type=int, default=8765)
    workbench_parser.add_argument("--out", type=Path, default=Path("outputs") / "intake_projects")
    workbench_parser.add_argument("--project", help="Open an existing intake project under --out.")
    workbench_parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")

    qa_parser = subparsers.add_parser("qa", help="Validate rendered SciPlot outputs.")
    qa_parser.add_argument("output_dir", type=Path)
    qa_parser.add_argument("--goldens", type=Path)
    qa_parser.add_argument(
        "--strict-goldens",
        action="store_true",
        help="Fail when any golden target is missing from the rendered output.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            payload = inspect_payload(_resolve_input(args.input), sheet=_coerce_sheet(args.sheet))
            if args.json:
                _print_json(payload)
            else:
                print(payload.get("recommendation_summary", "No recommendation summary available."))
            return 0
        if args.command == "render":
            source = _resolve_input(args.input)
            sheet = _coerce_sheet(args.sheet)
            template = args.template
            options = _load_options(args.options)
            if args.auto:
                recommendations = inspect_payload(source, sheet=sheet).get("recommendations") or []
                if not recommendations:
                    raise ValueError("--auto could not recommend a template; pass --template and --options explicitly.")
                top = recommendations[0]
                template = template or str(top.get("template_id"))
                defaults = top.get("default_render_overrides")
                if isinstance(defaults, dict):
                    options = {**defaults, **options}  # explicit --options take precedence
            if not template:
                raise ValueError("render needs a template: pass --template NAME, or --auto to choose one.")
            payload = render_to_dir(
                source,
                template=template,
                output_dir=args.out.expanduser(),
                sheet=sheet,
                options=options,
            )
            _print_json(payload)
            return 0
        if args.command == "recipe":
            payload = run_recipe(
                args.name,
                _resolve_input(args.input),
                output_dir=args.out.expanduser(),
                options=_load_options(args.options),
            )
            _print_json(payload)
            return 0
        if args.command == "run":
            _print_json(run_request(_resolve_input(args.request, kind="Request file")))
            return 0
        if args.command == "origin-handoff":
            _print_json(
                export_origin_handoff(
                    _resolve_input(args.input, kind="SciPlot run output or manifest"),
                    output_dir=args.out.expanduser() if args.out else None,
                )
            )
            return 0
        if args.command == "quick":
            serve_intake(
                input_path=_resolve_input(args.input),
                host=args.host,
                port=args.port,
                output_root=args.out.expanduser(),
                open_browser=not args.no_open,
            )
            return 0
        if args.command == "curate":
            if args.curate_command == "torque":
                payload = curate_torque_project(
                    args.input.expanduser(),
                    output_root=args.out.expanduser(),
                    project_name=args.name,
                    open_review=args.open,
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(payload["review_html"])
                return 0
        if args.command == "prepare":
            payload = prepare_intake_session(args.input.expanduser(), output_root=args.out.expanduser())
            if args.json:
                _print_json(payload)
            else:
                print(payload["session_path"])
            return 0
        if args.command == "rules":
            if args.rules_command == "list":
                payload = list_rules_payload()
                if args.json:
                    _print_json(payload)
                else:
                    for item in payload["rules"]:
                        print(f"{item['rule_id']}: {item['x']} -> {item['y']}")
                return 0
            if args.rules_command == "show":
                payload = show_rule_payload(args.rule_id)
                if args.json:
                    _print_json(payload)
                else:
                    x_label = payload["axis_plan"]["x"]["display_label"]
                    y_label = payload["axis_plan"]["y"]["display_label"]
                    print(f"{payload['rule_id']}: {x_label} -> {y_label}")
                return 0
        if args.command == "batch":
            _print_json(
                run_batch(
                    args.input_dir.expanduser(),
                    output_dir=args.out.expanduser(),
                    mode=args.mode,
                    tensile_roots=args.tensile_root,
                )
            )
            return 0
        if args.command in {"app", "intake", "workbench"}:
            if args.catalog:
                payload = intake_catalog_payload()
                if args.json:
                    _print_json(payload)
                else:
                    for data_type in payload["data_types"]:
                        print(data_type["label"])
                        for experiment in data_type["experiments"]:
                            print(f"  {experiment['id']}: {experiment['label']}")
                return 0
            serve_kwargs: dict[str, Any] = {
                "input_path": args.input.expanduser() if args.input else None,
                "host": args.host,
                "port": args.port,
                "output_root": args.out.expanduser(),
                "open_browser": not args.no_open,
            }
            if args.project:
                serve_kwargs["project_slug"] = args.project
            serve_intake(**serve_kwargs)
            return 0
        if args.command == "qa":
            _print_json(
                run_qa(
                    args.output_dir.expanduser(),
                    goldens_dir=args.goldens.expanduser() if args.goldens else None,
                    require_all_goldens=args.strict_goldens,
                )
            )
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if args.command in {"inspect", "render", "recipe"} and any(
            marker in str(exc).casefold() for marker in _RECOGNITION_ERROR_MARKERS
        ):
            print(_recovery_hint(getattr(args, "input", None)), file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
