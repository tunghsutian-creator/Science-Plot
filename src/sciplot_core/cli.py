from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


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
        f"or prepare an editable Veusz project with `sciplot studio {target}`."
    )


def _load_options(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    if value.startswith("@"):
        return json.loads(Path(value[1:]).expanduser().read_text(encoding="utf-8"))
    return json.loads(value)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def serve_intake(**kwargs: Any) -> None:
    """Lazy compatibility seam; keeps CLI startup independent of the Web app."""

    from sciplot_core.intake import serve_intake as _serve_intake

    _serve_intake(**kwargs)


def run_one_step(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from sciplot_core.workflow import run_one_step as _run_one_step

    return _run_one_step(*args, **kwargs)


def run_autoplot(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from sciplot_core.autoplot import run_autoplot as _run_autoplot

    return _run_autoplot(*args, **kwargs)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sciplot",
        description="Local SciPlot plotting, Studio, recipe, QA, and optional assisted-cleanup CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect a source and return ranked plot recommendations."
    )
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.add_argument("--sheet", default="0")
    inspect_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Check whether this SciPlot install is ready for alpha use."
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    readiness_parser = subparsers.add_parser(
        "readiness",
        help="Inspect or certify deterministic ready-rule validation envelopes.",
    )
    readiness_subparsers = readiness_parser.add_subparsers(
        dest="readiness_command",
        required=True,
    )
    readiness_status_parser = readiness_subparsers.add_parser(
        "status",
        help="Verify current ready-rule contracts against accepted evidence.",
    )
    readiness_status_parser.add_argument(
        "--registry",
        type=Path,
        help="Optional candidate validated-envelope registry.",
    )
    readiness_status_parser.add_argument("--json", action="store_true")
    readiness_certify_parser = readiness_subparsers.add_parser(
        "certify",
        help="Build a candidate registry from a complete real-data acceptance run.",
    )
    readiness_certify_parser.add_argument("acceptance_summary", type=Path)
    readiness_certify_parser.add_argument("--out", type=Path, required=True)
    readiness_certify_parser.add_argument("--json", action="store_true")

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="Run the fixture-free Studio lifecycle and delivery change gate.",
    )
    smoke_parser.add_argument(
        "--out", type=Path, default=Path(".tmp_verify") / "runtime_smoke"
    )
    smoke_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    readiness_probe_parser = subparsers.add_parser(
        "readiness-probe",
        help=argparse.SUPPRESS,
    )
    readiness_probe_parser.add_argument(
        "--out",
        type=Path,
        default=Path(".tmp_verify") / "readiness_probe",
    )
    readiness_probe_parser.add_argument("--json", action="store_true")
    openai_provider_probe_parser = subparsers.add_parser(
        "openai-provider-probe",
        help=argparse.SUPPRESS,
    )
    openai_provider_probe_parser.add_argument(
        "--out",
        type=Path,
        default=Path(".tmp_verify") / "openai_provider",
    )
    openai_provider_probe_parser.add_argument("--json", action="store_true")
    data_mapping_probe_parser = subparsers.add_parser(
        "data-mapping-probe",
        help=argparse.SUPPRESS,
    )
    data_mapping_probe_parser.add_argument(
        "--out",
        type=Path,
        default=Path(".tmp_verify") / "data_mapping",
    )
    data_mapping_probe_parser.add_argument("--json", action="store_true")

    render_parser = subparsers.add_parser(
        "render", help="Render a source through the SciPlot renderer."
    )
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument(
        "--template", help="Template id. Optional when --auto is given."
    )
    render_parser.add_argument("--sheet", default="0")
    render_parser.add_argument(
        "--options", help="JSON object or @path JSON file with render options."
    )
    render_parser.add_argument(
        "--auto",
        action="store_true",
        help="Apply the inspected recommendation's scientific defaults "
        "(template, axis scales, reversed axes). Explicit --options still win.",
    )
    render_parser.add_argument("--out", type=Path, required=True)

    recipe_parser = subparsers.add_parser(
        "recipe", help="Run an experiment-family recipe."
    )
    recipe_parser.add_argument("name")
    recipe_parser.add_argument("input", type=Path)
    recipe_parser.add_argument(
        "--options", help="JSON object or @path JSON file with recipe/render options."
    )
    recipe_parser.add_argument("--out", type=Path, required=True)

    run_parser = subparsers.add_parser("run", help="Run a plot_request.json workflow.")
    run_parser.add_argument("request", type=Path)

    one_step_parser = subparsers.add_parser(
        "one-step",
        help=argparse.SUPPRESS,
    )
    one_step_parser.add_argument("input", type=Path)
    one_step_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "one_step_projects"
    )
    one_step_parser.add_argument(
        "--name", help="Project name. Defaults to the input file or folder name."
    )
    one_step_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    autoplot_parser = subparsers.add_parser(
        "autoplot",
        help="One-command local plotting entrypoint with stable delivery and optional assistant handoff policy.",
    )
    autoplot_parser.add_argument("input", type=Path)
    autoplot_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "autoplot_projects"
    )
    autoplot_parser.add_argument(
        "--name", help="Project name. Defaults to the input file or folder name."
    )
    autoplot_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    acceptance_parser = subparsers.add_parser(
        "acceptance", help="Run real-data acceptance suites."
    )
    acceptance_subparsers = acceptance_parser.add_subparsers(
        dest="acceptance_command", required=True
    )
    acceptance_3dpa_parser = acceptance_subparsers.add_parser(
        "3dpa",
        help="Run the representative 3D PA real-data acceptance suite.",
    )
    acceptance_3dpa_parser.add_argument("input", type=Path)
    acceptance_3dpa_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "acceptance"
    )
    acceptance_3dpa_parser.add_argument(
        "--name", default="3dpa_acceptance", help="Acceptance project name."
    )
    acceptance_3dpa_parser.add_argument("--representative-count", type=int, default=6)
    acceptance_3dpa_parser.add_argument("--dense-series", type=int, default=44)
    acceptance_3dpa_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    acceptance_rules_parser = acceptance_subparsers.add_parser(
        "rules",
        help="Run the ready-rule Studio lifecycle acceptance matrix.",
    )
    acceptance_rules_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "acceptance"
    )
    acceptance_rules_parser.add_argument(
        "--name", default="ready_rule_acceptance", help="Acceptance project name."
    )
    acceptance_rules_parser.add_argument(
        "--rule",
        dest="rule_ids",
        action="append",
        help="Run one ready rule; repeat for a batch. Defaults to all ready rules.",
    )
    acceptance_rules_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    quick_parser = subparsers.add_parser("quick", help=argparse.SUPPRESS)
    quick_parser.add_argument("input", type=Path)
    quick_parser.add_argument("--host", default="127.0.0.1")
    quick_parser.add_argument(
        "--port", type=int, default=0, help="Use 0 to choose a free local port."
    )
    quick_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects"
    )
    quick_parser.add_argument(
        "--no-open", action="store_true", help="Do not open a browser automatically."
    )

    curate_parser = subparsers.add_parser(
        "curate", help="Create a reviewable curation project."
    )
    curate_subparsers = curate_parser.add_subparsers(
        dest="curate_command", required=True
    )
    curate_torque_parser = curate_subparsers.add_parser(
        "torque", help="Curate torque event segments."
    )
    curate_torque_parser.add_argument("input", type=Path)
    curate_torque_parser.add_argument(
        "--name", required=True, help="User-facing project name."
    )
    curate_torque_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "curation_projects"
    )
    curate_torque_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    curate_torque_parser.add_argument(
        "--open", action="store_true", help="Open the review HTML after export."
    )

    prepare_parser = subparsers.add_parser("prepare", help=argparse.SUPPRESS)
    prepare_parser.add_argument("input", type=Path)
    prepare_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects"
    )
    prepare_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    rules_parser = subparsers.add_parser(
        "rules", help="Inspect SciPlot material semantic rules."
    )
    rules_subparsers = rules_parser.add_subparsers(dest="rules_command", required=True)
    rules_list_parser = rules_subparsers.add_parser(
        "list", help="List material semantic rules."
    )
    rules_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    rules_list_parser.add_argument(
        "--all", action="store_true", help="Include pending internal rules."
    )
    rules_show_parser = rules_subparsers.add_parser(
        "show", help="Show one material semantic rule."
    )
    rules_show_parser.add_argument("rule_id")
    rules_show_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Create or inspect assisted-cleanup artifacts."
    )
    cleanup_subparsers = cleanup_parser.add_subparsers(
        dest="cleanup_command", required=True
    )
    cleanup_result_parser = cleanup_subparsers.add_parser(
        "result",
        help="Write a cleanup_result.json from a Codex/agent assisted cleanup job.",
    )
    cleanup_result_parser.add_argument("output_dir", type=Path)
    cleanup_result_parser.add_argument("--cleaned-data", type=Path, required=True)
    cleanup_result_parser.add_argument(
        "--mapping", help="JSON object or @path JSON file with column/sample mapping."
    )
    cleanup_result_parser.add_argument("--confidence", type=float, required=True)
    cleanup_result_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Mark the cleaned result as human-confirmed.",
    )
    cleanup_result_parser.add_argument(
        "--raw-input",
        type=Path,
        action="append",
        help="Raw input path preserved by cleanup.",
    )
    cleanup_result_parser.add_argument(
        "--provider",
        default="manual",
        help="Cleanup provider label, e.g. manual or codex.",
    )
    cleanup_result_parser.add_argument(
        "--notes", default="", help="Short cleanup note."
    )
    cleanup_result_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    cleanup_show_parser = cleanup_subparsers.add_parser(
        "show",
        help="Show cleanup_result.json from a directory or file.",
    )
    cleanup_show_parser.add_argument("target", type=Path)
    cleanup_show_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    mapping_parser = subparsers.add_parser(
        "mapping",
        help="Preview, confirm, execute, or inspect a typed DataMappingProposal.",
    )
    mapping_subparsers = mapping_parser.add_subparsers(
        dest="mapping_command",
        required=True,
    )
    mapping_preview_parser = mapping_subparsers.add_parser(
        "preview",
        help="Validate a proposal and compute metadata-only output changes without writing data.",
    )
    mapping_preview_parser.add_argument("proposal", type=Path)
    mapping_preview_parser.add_argument("--source-root", type=Path, required=True)
    mapping_preview_parser.add_argument("--request", type=Path, required=True)
    mapping_preview_parser.add_argument("--json", action="store_true")
    mapping_confirm_parser = mapping_subparsers.add_parser(
        "confirm",
        help="Create a user confirmation receipt bound to the exact proposal, request, and source hashes.",
    )
    mapping_confirm_parser.add_argument("proposal", type=Path)
    mapping_confirm_parser.add_argument("--source-root", type=Path, required=True)
    mapping_confirm_parser.add_argument("--request", type=Path, required=True)
    mapping_confirm_parser.add_argument(
        "--execution-root",
        type=Path,
        required=True,
        help="Exact parent directory where confirmed execution may write its candidate.",
    )
    mapping_confirm_parser.add_argument("--by", required=True)
    mapping_confirm_parser.add_argument("--out", type=Path)
    mapping_confirm_parser.add_argument("--json", action="store_true")
    mapping_execute_parser = mapping_subparsers.add_parser(
        "execute",
        help="Execute a confirmed proposal atomically and write a mapped request candidate.",
    )
    mapping_execute_parser.add_argument("proposal", type=Path)
    mapping_execute_parser.add_argument("--confirmation", type=Path, required=True)
    mapping_execute_parser.add_argument("--source-root", type=Path, required=True)
    mapping_execute_parser.add_argument("--request", type=Path, required=True)
    mapping_execute_parser.add_argument("--out", type=Path, required=True)
    mapping_execute_parser.add_argument("--json", action="store_true")
    mapping_show_parser = mapping_subparsers.add_parser(
        "show",
        help="Verify and show a completed data mapping execution.",
    )
    mapping_show_parser.add_argument("target", type=Path)
    mapping_show_parser.add_argument("--json", action="store_true")

    batch_parser = subparsers.add_parser(
        "batch", help="Run a batch over a data folder."
    )
    batch_parser.add_argument("input_dir", type=Path)
    batch_parser.add_argument("--out", type=Path, required=True)
    batch_parser.add_argument("--mode", choices=["smoke", "all"], default="smoke")
    batch_parser.add_argument(
        "--tensile-root",
        action="append",
        type=Path,
        help="Allow-list tensile data root. Repeat to allow multiple tensile folders.",
    )

    app_parser = subparsers.add_parser(
        "app",
        help=(
            "Open the browser compatibility surface for source, grouping, "
            "and export confirmation."
        ),
    )
    app_parser.add_argument("input", nargs="?", type=Path)
    app_parser.add_argument(
        "--catalog", action="store_true", help="Print the intake data type catalog."
    )
    app_parser.add_argument(
        "--all", action="store_true", help="Include pending internal catalog entries."
    )
    app_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    app_parser.add_argument("--host", default="127.0.0.1")
    app_parser.add_argument("--port", type=int, default=8765)
    app_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects"
    )
    app_parser.add_argument(
        "--project", help="Open an existing intake project under --out."
    )
    app_parser.add_argument(
        "--no-open", action="store_true", help="Do not open a browser automatically."
    )

    intake_parser = subparsers.add_parser("intake", help=argparse.SUPPRESS)
    intake_parser.add_argument("input", nargs="?", type=Path)
    intake_parser.add_argument(
        "--catalog", action="store_true", help="Print the intake data type catalog."
    )
    intake_parser.add_argument(
        "--all", action="store_true", help="Include pending internal catalog entries."
    )
    intake_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    intake_parser.add_argument("--host", default="127.0.0.1")
    intake_parser.add_argument("--port", type=int, default=8765)
    intake_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects"
    )
    intake_parser.add_argument(
        "--project", help="Open an existing intake project under --out."
    )
    intake_parser.add_argument(
        "--no-open", action="store_true", help="Do not open a browser automatically."
    )

    workbench_parser = subparsers.add_parser("workbench", help=argparse.SUPPRESS)
    workbench_parser.add_argument("input", nargs="?", type=Path)
    workbench_parser.add_argument(
        "--catalog", action="store_true", help="Print the intake data type catalog."
    )
    workbench_parser.add_argument(
        "--all", action="store_true", help="Include pending internal catalog entries."
    )
    workbench_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    workbench_parser.add_argument("--host", default="127.0.0.1")
    workbench_parser.add_argument("--port", type=int, default=8765)
    workbench_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects"
    )
    workbench_parser.add_argument(
        "--project", help="Open an existing intake project under --out."
    )
    workbench_parser.add_argument(
        "--no-open", action="store_true", help="Do not open a browser automatically."
    )

    studio_parser = subparsers.add_parser(
        "studio",
        help="Open the Veusz-based SciPlot Studio workflow.",
    )
    studio_parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        help="Raw data path, SciPlot project, plot_request.json, or .vsz file.",
    )
    studio_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Project root for raw input, or artifact root for standalone VSZ export. "
            "Raw input defaults to outputs/intake_projects; standalone VSZ defaults beside the document."
        ),
    )
    studio_parser.add_argument(
        "--rule",
        help="Explicit ready material rule selected by the user or Luna/Codex; bypass automatic recognition.",
    )
    studio_parser.add_argument(
        "--template",
        help="Preselect the SciPlot plot template, e.g. curve or stacked_curve.",
    )
    studio_parser.add_argument(
        "--name", help="Preselect the SciPlot project/figure name."
    )
    studio_parser.add_argument(
        "--new", action="store_true", help="Open an empty embedded Veusz Studio window."
    )
    studio_parser.add_argument(
        "--advanced-editor",
        action="store_true",
        help="Open the full upstream Veusz editor for a generated .vsz document.",
    )
    studio_parser.add_argument(
        "--export", help="Comma-separated export formats, e.g. pdf,tiff_300."
    )
    studio_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON and do not open the GUI.",
    )
    studio_parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Generate/register the Studio document only.",
    )
    studio_parser.add_argument(
        "--qt-smoke",
        action="store_true",
        help="Run a headless PyQt/Veusz embedding smoke test.",
    )

    qa_parser = subparsers.add_parser("qa", help="Validate rendered SciPlot outputs.")
    qa_parser.add_argument("output_dir", type=Path)
    qa_parser.add_argument("--goldens", type=Path)
    qa_parser.add_argument(
        "--strict-goldens",
        action="store_true",
        help="Fail when any golden target is missing from the rendered output.",
    )
    qa_parser.add_argument(
        "--publication-profile",
        "--profile",
        help="Publication profile id or JSON path for final-artifact checks.",
    )
    qa_parser.add_argument(
        "--strict-publication",
        action="store_true",
        help="Return a failed QA status when publication-profile checks need revision.",
    )

    publication_parser = subparsers.add_parser(
        "publication",
        help="Inspect publication profiles and deterministic figure-level layouts.",
    )
    publication_subparsers = publication_parser.add_subparsers(
        dest="publication_command", required=True
    )
    publication_profiles_parser = publication_subparsers.add_parser(
        "profiles", help="List publication profiles."
    )
    publication_profiles_parser.add_argument("--json", action="store_true")
    publication_profile_parser = publication_subparsers.add_parser(
        "profile", help="Show one publication profile."
    )
    publication_profile_parser.add_argument("profile_id")
    publication_profile_parser.add_argument("--json", action="store_true")
    publication_layouts_parser = publication_subparsers.add_parser(
        "layouts", help="List deterministic figure-level layouts."
    )
    publication_layouts_parser.add_argument("--json", action="store_true")
    publication_layout_parser = publication_subparsers.add_parser(
        "layout", help="Show one deterministic figure-level layout."
    )
    publication_layout_parser.add_argument("layout_id")
    publication_layout_parser.add_argument("--height-mm", type=float, default=55.0)
    publication_layout_parser.add_argument("--json", action="store_true")

    figure_parser = subparsers.add_parser(
        "figure",
        help="Build plot-ready curve and shared-colorbar figure profiles without scientific data processing.",
    )
    figure_subparsers = figure_parser.add_subparsers(dest="figure_command", required=True)
    figure_profiles_parser = figure_subparsers.add_parser("profiles", help="List reusable figure profiles.")
    figure_profiles_parser.add_argument("--json", action="store_true")
    figure_profile_parser = figure_subparsers.add_parser("profile", help="Show one reusable figure profile.")
    figure_profile_parser.add_argument("profile_id")
    figure_profile_parser.add_argument("--json", action="store_true")
    figure_build_parser = figure_subparsers.add_parser(
        "build",
        help="Build a VSZ/PDF/TIFF package from an explicit plot-ready figure request.",
    )
    figure_build_parser.add_argument("request", type=Path)
    figure_build_parser.add_argument("--out", type=Path, required=True)
    figure_build_parser.add_argument("--json", action="store_true")

    hidden_compatibility_commands = {
        "one-step",
        "quick",
        "prepare",
        "intake",
        "workbench",
        "readiness-probe",
        "openai-provider-probe",
        "data-mapping-probe",
    }
    subparsers._choices_actions[:] = [  # type: ignore[attr-defined]
        action
        for action in subparsers._choices_actions
        if action.dest not in hidden_compatibility_commands
    ]
    public_commands = [
        name for name in subparsers.choices if name not in hidden_compatibility_commands
    ]
    subparsers.metavar = "{" + ",".join(public_commands) + "}"

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            from sciplot_core.render import inspect_payload

            payload = inspect_payload(
                _resolve_input(args.input), sheet=_coerce_sheet(args.sheet)
            )
            if args.json:
                _print_json(payload)
            else:
                print(
                    payload.get(
                        "recommendation_summary", "No recommendation summary available."
                    )
                )
            return 0
        if args.command == "doctor":
            from sciplot_core.doctor import doctor_payload

            payload = doctor_payload()
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot doctor: {payload['status']}")
                print(
                    "Rules: "
                    f"{payload['rule_summary']['ready']} ready, "
                    f"{payload['rule_summary']['pending']} pending"
                )
                for check in payload["checks"]:
                    marker = "ok" if check["status"] == "passed" else "failed"
                    print(
                        f"{marker}  {check['label']}: {check.get('detail') or check['status']}"
                    )
            return 0 if payload["status"] == "ready" else 1
        if args.command == "readiness":
            from sciplot_core._utils import file_sha256
            from sciplot_core.readiness import (
                build_validated_envelope_registry,
                load_validated_envelope_registry,
                validated_envelope_status,
                write_validated_envelope_registry,
            )

            if args.readiness_command == "status":
                registry_path = (
                    _resolve_input(
                        args.registry,
                        kind="Validated-envelope registry",
                    )
                    if args.registry is not None
                    else None
                )
                registry = (
                    load_validated_envelope_registry(registry_path)
                    if registry_path is not None
                    else None
                )
                payload = validated_envelope_status(
                    registry,
                    registry_path=registry_path,
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(f"SciPlot readiness: {payload['status']}")
                    print(
                        "Current validated envelopes: "
                        f"{payload['ready_without_ai_rule_count']}/"
                        f"{payload['current_ready_rule_count']}"
                    )
                return 0 if payload["status"] == "ready" else 1
            acceptance_summary = _resolve_input(
                args.acceptance_summary,
                kind="Ready-rule acceptance summary",
            )
            registry = build_validated_envelope_registry(acceptance_summary)
            output = write_validated_envelope_registry(args.out, registry)
            status = validated_envelope_status(registry)
            payload = {
                "kind": "sciplot_validated_envelope_certification",
                "version": 1,
                "status": status["status"],
                "acceptance_summary": str(acceptance_summary.resolve()),
                "registry": str(output),
                "registry_sha256": file_sha256(output),
                "envelopes": status,
            }
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot readiness certification: {payload['status']}")
                print(payload["registry"])
            return 0 if payload["status"] == "ready" else 1
        if args.command == "smoke":
            from sciplot_core.studio import maybe_reexec_with_qt_runtime

            original_argv = list(sys.argv[1:] if argv is None else argv)
            maybe_reexec_with_qt_runtime(original_argv)
            from sciplot_core.smoke import run_runtime_smoke

            payload = run_runtime_smoke(output_root=args.out)
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot runtime smoke: {payload['status']}")
                print(payload["artifacts"]["summary"])
            return 0 if payload["status"] == "passed" else 1
        if args.command == "readiness-probe":
            from sciplot_core.readiness_probe import run_readiness_probe

            payload = run_readiness_probe(output_root=args.out)
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot readiness probe: {payload['status']}")
                print(payload["artifacts"]["summary"])
            return 0 if payload["status"] == "passed" else 1
        if args.command == "openai-provider-probe":
            from sciplot_core.openai_provider_probe import (
                run_openai_provider_probe,
            )

            payload = run_openai_provider_probe(output_root=args.out)
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot OpenAI provider probe: {payload['status']}")
                print(payload["artifacts"]["summary"])
            return 0 if payload["status"] == "passed" else 1
        if args.command == "data-mapping-probe":
            from sciplot_core.data_mapping_probe import (
                run_data_mapping_probe,
            )

            payload = run_data_mapping_probe(output_root=args.out)
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot data mapping probe: {payload['status']}")
                print(payload["artifacts"]["summary"])
            return 0 if payload["status"] == "passed" else 1
        if args.command == "render":
            from sciplot_core.render import inspect_payload, render_to_dir

            source = _resolve_input(args.input)
            sheet = _coerce_sheet(args.sheet)
            template = args.template
            options = _load_options(args.options)
            if args.auto:
                inspection = inspect_payload(source, sheet=sheet)
                resolution = inspection.get("inspection_resolution")
                if (
                    isinstance(resolution, dict)
                    and resolution.get("status") != "ready_rule_authoritative"
                ):
                    raise ValueError(
                        "--auto refused an unverified material-rule candidate; "
                        "inspect or repair the source, or pass --template and "
                        "--options explicitly."
                    )
                recommendations = inspection.get("recommendations") or []
                if not recommendations:
                    raise ValueError(
                        "--auto could not recommend a template; pass --template and --options explicitly."
                    )
                top = recommendations[0]
                template = template or str(top.get("template_id"))
                defaults = top.get("default_render_overrides")
                if isinstance(defaults, dict):
                    options = {
                        **defaults,
                        **options,
                    }  # explicit --options take precedence
            if not template:
                raise ValueError(
                    "render needs a template: pass --template NAME, or --auto to choose one."
                )
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
            from sciplot_recipes import run_recipe

            payload = run_recipe(
                args.name,
                _resolve_input(args.input),
                output_dir=args.out.expanduser(),
                options=_load_options(args.options),
            )
            _print_json(payload)
            return 0
        if args.command == "run":
            from sciplot_core.workflow import run_request

            payload = run_request(_resolve_input(args.request, kind="Request file"))
            _print_json(payload)
            request = (
                payload.get("request")
                if isinstance(payload.get("request"), dict)
                else {}
            )
            qa = payload.get("qa") if isinstance(payload.get("qa"), dict) else {}
            if bool(request.get("publication_strict")) and qa.get("status") != "passed":
                return 1
            return 0
        if args.command == "one-step":
            payload = run_one_step(
                _resolve_input(args.input),
                output_root=args.out.expanduser(),
                project_name=args.name,
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["run_output"])
            return 0 if payload.get("status") == "ready" else 1
        if args.command == "autoplot":
            payload = run_autoplot(
                _resolve_input(args.input),
                output_root=args.out.expanduser(),
                project_name=args.name,
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["delivery"] or payload["run_output"])
            return (
                0
                if payload.get("state") == "ready"
                and payload.get("ready_to_use") is not False
                else 1
            )
        if args.command == "acceptance":
            if args.acceptance_command == "3dpa":
                from sciplot_core.acceptance import run_3dpa_acceptance

                payload = run_3dpa_acceptance(
                    _resolve_input(args.input),
                    output_root=args.out.expanduser(),
                    project_name=args.name,
                    representative_count=args.representative_count,
                    dense_series_count=args.dense_series,
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(payload["project_dir"])
                return 0
            if args.acceptance_command == "rules":
                from sciplot_core.studio import maybe_reexec_with_qt_runtime

                original_argv = list(sys.argv[1:] if argv is None else argv)
                maybe_reexec_with_qt_runtime(original_argv)
                from sciplot_core.acceptance import run_rule_acceptance_suite

                payload = run_rule_acceptance_suite(
                    output_root=args.out.expanduser(),
                    project_name=args.name,
                    rule_ids=args.rule_ids,
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(payload["artifacts"]["matrix_markdown"])
                return 0 if payload["selected_state"] == "ready" else 1
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
                from sciplot_core.studio import maybe_reexec_with_qt_runtime

                original_argv = list(sys.argv[1:] if argv is None else argv)
                maybe_reexec_with_qt_runtime(original_argv)
                from sciplot_core.curate import curate_torque_project

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
            from sciplot_core.intake import prepare_intake_session

            payload = prepare_intake_session(
                args.input.expanduser(), output_root=args.out.expanduser()
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["session_path"])
            return 0
        if args.command == "rules":
            from sciplot_core.materials_rules import (
                list_rules_payload,
                show_rule_payload,
            )

            if args.rules_command == "list":
                payload = list_rules_payload(include_pending=args.all)
                if args.json:
                    _print_json(payload)
                else:
                    for item in payload["rules"]:
                        status = (
                            ""
                            if item.get("fixture_status") == "ready"
                            else f" [{item['fixture_status']}]"
                        )
                        print(f"{item['rule_id']}{status}: {item['x']} -> {item['y']}")
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
        if args.command == "cleanup":
            from sciplot_core.assisted_cleanup import (
                load_cleanup_result,
                write_cleanup_result,
            )

            if args.cleanup_command == "result":
                payload = write_cleanup_result(
                    args.output_dir.expanduser(),
                    cleaned_data=_resolve_input(args.cleaned_data, kind="Cleaned data"),
                    mapping_proposal=_load_options(args.mapping),
                    confidence=args.confidence,
                    human_confirmed=args.confirm,
                    raw_inputs=[path.expanduser() for path in args.raw_input or []],
                    notes=args.notes,
                    provider=args.provider,
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(payload["cleanup_result"])
                return 0
            if args.cleanup_command == "show":
                payload = load_cleanup_result(args.target.expanduser())
                if args.json:
                    _print_json(payload)
                else:
                    print(
                        f"{payload.get('cleaned_data', {}).get('path', '')} "
                        f"ready={payload.get('ready_for_normal_mode', False)}"
                    )
                return 0
        if args.command == "mapping":
            from sciplot_core.data_mapping import (
                create_data_mapping_confirmation,
                execute_data_mapping_proposal,
                load_data_mapping_execution,
                preview_data_mapping_proposal,
                write_data_mapping_confirmation,
            )

            proposal_path = (
                _resolve_input(
                    args.proposal,
                    kind="DataMappingProposal",
                )
                if hasattr(args, "proposal")
                else None
            )
            if args.mapping_command == "preview":
                payload = preview_data_mapping_proposal(
                    proposal_path,
                    source_root=_resolve_input(
                        args.source_root,
                        kind="Data mapping source root",
                    ),
                    request_path=_resolve_input(
                        args.request,
                        kind="Plot request",
                    ),
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(
                        f"{payload['status']}: "
                        f"{len(payload['sources'])} source(s), "
                        "no writes performed"
                    )
                return 0
            if args.mapping_command == "confirm":
                confirmation = create_data_mapping_confirmation(
                    proposal_path,
                    source_root=_resolve_input(
                        args.source_root,
                        kind="Data mapping source root",
                    ),
                    request_path=_resolve_input(
                        args.request,
                        kind="Plot request",
                    ),
                    output_root=args.execution_root.expanduser().resolve(),
                    confirmed_by=args.by,
                )
                destination = (
                    args.out.expanduser()
                    if args.out is not None
                    else proposal_path.parent / "confirmation.json"
                )
                written = write_data_mapping_confirmation(
                    destination,
                    confirmation,
                )
                payload = {
                    **confirmation.to_dict(),
                    "path": str(written),
                }
                if args.json:
                    _print_json(payload)
                else:
                    print(written)
                return 0
            if args.mapping_command == "execute":
                payload = execute_data_mapping_proposal(
                    proposal_path,
                    _resolve_input(
                        args.confirmation,
                        kind="Data mapping confirmation",
                    ),
                    source_root=_resolve_input(
                        args.source_root,
                        kind="Data mapping source root",
                    ),
                    request_path=_resolve_input(
                        args.request,
                        kind="Plot request",
                    ),
                    output_root=args.out.expanduser(),
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(payload["request_candidate"])
                return 0
            if args.mapping_command == "show":
                payload = load_data_mapping_execution(
                    _resolve_input(
                        args.target,
                        kind="Data mapping execution",
                    )
                )
                if args.json:
                    _print_json(payload)
                else:
                    print(
                        f"{payload['status']}: "
                        f"{payload['proposal_id']} -> "
                        f"{payload['request_candidate']}"
                    )
                return 0
        if args.command == "batch":
            from sciplot_core.batch import run_batch

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
            from sciplot_core.intake import intake_catalog_payload

            if args.catalog:
                payload = intake_catalog_payload(include_pending=args.all)
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
        if args.command == "studio":
            from sciplot_core.studio import run_studio_command

            original_argv = list(sys.argv[1:] if argv is None else argv)
            return run_studio_command(
                target=args.target.expanduser() if args.target else None,
                output_root=args.out.expanduser() if args.out else None,
                rule_id=args.rule,
                template=args.template,
                project_name=args.name,
                new=args.new,
                advanced_editor=args.advanced_editor,
                export=args.export,
                json_output=args.json,
                prepare_only=args.prepare_only,
                qt_smoke=args.qt_smoke,
                original_argv=original_argv,
            )
        if args.command == "publication":
            from sciplot_core.publication import (
                build_composite_layout,
                get_publication_profile,
                list_composite_layouts,
                list_publication_profiles,
            )

            if args.publication_command == "profiles":
                payload = {
                    "kind": "sciplot_publication_profiles",
                    "profiles": list_publication_profiles(),
                }
            elif args.publication_command == "profile":
                payload = get_publication_profile(args.profile_id)
            elif args.publication_command == "layouts":
                payload = {
                    "kind": "sciplot_composite_layouts",
                    "layouts": list_composite_layouts(),
                }
            else:
                payload = build_composite_layout(
                    args.layout_id, canvas_height_mm=args.height_mm
                )
            if args.json:
                _print_json(payload)
            else:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if args.command == "figure":
            from sciplot_core.figure_profiles import (
                figure_profile_payload,
                list_figure_profiles,
            )

            if args.figure_command == "profiles":
                payload = {
                    "kind": "sciplot_figure_profiles",
                    "version": 1,
                    "profiles": list_figure_profiles(),
                }
            elif args.figure_command == "profile":
                payload = figure_profile_payload(args.profile_id)
            else:
                from sciplot_core.studio import maybe_reexec_with_qt_runtime

                original_argv = list(sys.argv[1:] if argv is None else argv)
                maybe_reexec_with_qt_runtime(original_argv)
                from sciplot_core.figure_workflow import run_plot_ready_figure_request

                payload = run_plot_ready_figure_request(
                    _resolve_input(args.request, kind="Figure request file"),
                    output_dir=args.out.expanduser(),
                )
            if args.json:
                _print_json(payload)
            elif args.figure_command == "build":
                print(payload["delivery"])
            else:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if args.command == "qa":
            from sciplot_core.qa import run_qa

            payload = run_qa(
                args.output_dir.expanduser(),
                goldens_dir=args.goldens.expanduser() if args.goldens else None,
                require_all_goldens=args.strict_goldens,
                publication_profile=args.publication_profile,
                strict_publication=args.strict_publication,
            )
            _print_json(payload)
            return 0 if payload.get("status") == "passed" else 1
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
