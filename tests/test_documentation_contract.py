from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_GUIDANCE = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "skill" / "SKILL.md",
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "DEVELOPMENT_ROADMAP.md",
)
RETIRED_AGENT_GUIDE = REPO_ROOT / "agent.md"
REMOVED_ARCHITECTURE_SNAPSHOT = (
    REPO_ROOT / "docs" / "ARCHITECTURE_REFACTOR_AUDIT_2026-07-28.md"
)
AUTOMATION_CONTROL_CONTRACT = REPO_ROOT / "docs" / "AUTOMATION_CONTROL_CONTRACT.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).split())


def test_user_plotting_guidance_keeps_deliveries_source_adjacent() -> None:
    readme = _normalized(REPO_ROOT / "README.md")

    assert (
        "Outputs are saved beside your source data in `SOURCE_SciPlot/` by default."
        in readme
    )
    skill = _normalized(REPO_ROOT / "skill" / "SKILL.md")
    assert "omit `--out` by default" in skill
    assert "Do not put user plotting deliveries inside the SciPlot repository" in skill

    for path in ACTIVE_GUIDANCE:
        guidance = _read(path)
        assert "--out outputs/" not in guidance
        assert "--out=outputs/" not in guidance


def test_current_documents_do_not_restore_the_dated_architecture_snapshot() -> None:
    gitignore = _read(REPO_ROOT / ".gitignore")

    assert not REMOVED_ARCHITECTURE_SNAPSHOT.exists()
    assert "!/docs/ARCHITECTURE_REFACTOR_AUDIT_2026-07-28.md" not in gitignore
    assert "!/docs/AUTOMATION_CONTROL_CONTRACT.md" in gitignore
    assert AUTOMATION_CONTROL_CONTRACT.is_file()


def test_tracked_guidance_does_not_keep_a_duplicate_agent_file() -> None:
    assert not RETIRED_AGENT_GUIDE.exists()

    for path in ACTIVE_GUIDANCE:
        assert "`agent.md`" not in _read(path)


def test_roadmap_contains_closable_work_not_standing_invariants() -> None:
    roadmap = _read(REPO_ROOT / "DEVELOPMENT_ROADMAP.md")
    architecture = _read(REPO_ROOT / "docs" / "ARCHITECTURE.md")

    assert "## P2 — Ongoing maintainability" not in roadmap
    assert "Keep ordinary source files below 400 lines" not in roadmap
    assert "Keep the removed `_vendor`" not in roadmap
    assert "Ordinary source files stay under 400 lines" in architecture
    assert "first-party dependencies remain acyclic" in architecture


def test_active_documents_declare_distinct_responsibilities() -> None:
    readme = _read(REPO_ROOT / "README.md")
    skill = _read(REPO_ROOT / "skill" / "SKILL.md")
    architecture = _read(REPO_ROOT / "docs" / "ARCHITECTURE.md")
    roadmap = _read(REPO_ROOT / "DEVELOPMENT_ROADMAP.md")
    automation_contract = _normalized(AUTOMATION_CONTROL_CONTRACT)

    assert "local scientific plotting tool for use with an external AI assistant" in readme
    assert "`README.md` owns product behavior and the user workflow." in skill
    assert "This skill owns agent routing and verification." in skill
    assert "current module-ownership and dependency reference" in architecture
    assert "External AI is the task interface" in roadmap
    assert "Independent beginner and installation acceptance" in roadmap
    assert "Reviewed annotation rebinding" in roadmap
    assert "R0 frozen design draft; not current runtime behavior" in automation_contract
    assert "does not add a conductor" in automation_contract
    assert "R0 automation baseline evidence" in architecture


def test_task_guidance_preserves_real_choices_and_separate_human_acceptance() -> None:
    roadmap = _normalized(REPO_ROOT / "DEVELOPMENT_ROADMAP.md")
    guide = _normalized(REPO_ROOT / "skill/references/external-control.md")
    readme = _normalized(REPO_ROOT / "README.md")
    assert "rule-selection answer must not encode arbitrary scientific facts" in roadmap
    assert "current headers, units and mappings can be validated" in roadmap
    assert "not this human usability evidence" in roadmap
    assert "needs_input" in guide and "rule_id" in guide
    assert "arbitrary DataMapping answers" in guide
    assert "no redundant user permission" in guide
    assert "task capabilities" in guide and "project operations-preview" in guide
    assert "MCP" in readme and "runs plotting and exports locally" in readme
    assert "Independent beginner and installation acceptance" in roadmap


def test_skill_defers_the_exact_mypy_scope_to_pyproject() -> None:
    skill = _read(REPO_ROOT / "skill/references/development.md")
    architecture = _read(REPO_ROOT / "docs" / "ARCHITECTURE.md")

    assert "declared under `[tool.mypy]` in `pyproject.toml`" in skill
    assert "Its exact scope and strictness belong to `pyproject.toml`." in skill
    assert "configured files" not in skill
    assert "The exact strict Python diagnostic scope" in architecture
    assert "all strictness options belong only to `[tool.mypy]`" in architecture
    assert "without maintaining another scope list or file count" in architecture
    assert "Strict Python 3.11 baseline for `foundation/`" not in architecture


def test_skill_entrypoint_is_bounded_and_its_routes_are_readable() -> None:
    skill_path = REPO_ROOT / "skill" / "SKILL.md"
    skill = _read(skill_path)

    assert len(skill.splitlines()) <= 100
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", skill)
    assert links
    for link in links:
        target = skill_path.parent / link.split("#", 1)[0]
        assert target.is_file(), f"Unreadable skill route: {link}"
        assert _read(target).strip(), f"Empty skill route: {link}"


def test_self_use_edit_guidance_keeps_deferred_readiness_and_full_evidence():
    guide = _read(REPO_ROOT / "skill/references/external-control.md")
    assert '"export":false' in guide and 'status:"saved"' in guide
    assert "not a publication receipt" in guide
    assert "--full" in guide and "review_path" in guide
    assert "compact stdout is a summary, not an apply file" in guide
    assert "set_sample_style" in guide and "figures[].sample_styles" in guide
    assert "ambiguous labels are rejected" in guide


def test_saved_figure_ai_entry_chooses_compact_only_for_known_managed_plots() -> None:
    skill = _normalized(REPO_ROOT / "skill/SKILL.md")
    route = _normalized(REPO_ROOT / "skill/references/saved-figure-edit.md")
    readme = _normalized(REPO_ROOT / "README.md")
    intent = _normalized(REPO_ROOT / "docs/plot_typed_intent.md")

    assert "For a known ManagedPlot, start with a compact summary" in skill
    assert "For unknown or LegacyPlot authority, open full" in skill
    assert "Known ManagedPlot:" in route and "Unknown authority or known LegacyPlot:" in route
    assert "plot open TARGET --scope summary --json" in route
    assert '"description":{"scope":"summary"}' in route
    assert "plot describe PLOT --scope edit --target-id ID --property NAME --json" in route
    assert '"description":{"scope":"edit","target":"ID", "property":"NAME"}' in route
    assert "status`, `changed_inputs`, `artifact_status`, `pending` and `next_step" in route
    assert "A LegacyPlot stays under its full description" in route
    assert "a separate scoped edit read is unnecessary" in route
    assert "When authority is unknown or the figure is a LegacyPlot" in readme
    assert "do not read it again solely to get the summary" in intent
    assert "do not guess among duplicates" in intent


def test_saved_figure_examples_match_public_cli_and_request_contract(tmp_path, monkeypatch, capsys) -> None:
    from jsonschema import Draft202012Validator

    from sciplot_core import cli
    from sciplot_core.cli.dispatch import plots as plot_dispatch
    from sciplot_core.mcp_server.schemas import tool_definitions
    from sciplot_core.mcp_server.server import INSTRUCTIONS
    from sciplot_core.plot_document.schema import patch_schema
    from sciplot_core.plot_engine.typed_intent import intent_schema

    route = _read(REPO_ROOT / "skill/references/saved-figure-edit.md")
    intent = _read(REPO_ROOT / "docs/plot_typed_intent.md")
    patch_example = json.loads(re.search(r"```json\n(.*?)\n```", route, re.DOTALL).group(1))
    intent_example = json.loads(re.search(r"```json\n(.*?)\n```", intent, re.DOTALL).group(1))
    Draft202012Validator(patch_schema()).validate(patch_example)
    Draft202012Validator(intent_schema()).validate(intent_example)

    forwarded = []
    monkeypatch.setattr(plot_dispatch, "call", lambda method, params, **_: forwarded.append((method, params)) or {"status": "ready"})
    request_path = tmp_path / "intent.json"
    request_path.write_text(json.dumps(intent_example), encoding="utf-8")
    target = str(tmp_path.resolve())
    assert cli.main(["plot", "open", target, "--scope", "summary", "--json", "--direct"]) == 0
    assert cli.main(["plot", "describe", target, "--scope", "edit", "--target-id", "axis:xb",
                     "--property", "axis.label", "--json", "--direct"]) == 0
    assert cli.main(["plot", "intent", target, "--request", str(request_path), "--json", "--direct"]) == 0
    capsys.readouterr()
    assert forwarded == [
        ("project.open", {"target": target, "description": {"scope": "summary"}}),
        ("plot.describe", {"plot": target, "description": {"scope": "edit", "target": "axis:xb",
                                                              "property": "axis.label"}}),
        ("plot.intent", {"plot": target, "request": intent_example}),
    ]
    tools = {tool.name: tool for tool in tool_definitions()}
    assert "scope summary" in INSTRUCTIONS and "unknown or LegacyPlot" in INSTRUCTIONS
    assert "known ManagedPlot" in tools["sciplot_project_open"].description
    assert "scope edit" in tools["sciplot_plot_describe"].description
    assert "Not for LegacyPlot" in tools["sciplot_plot_intent"].description


def test_saved_figure_mcp_entry_byte_measurement(tmp_path, monkeypatch) -> None:
    """Print reproducible fixture transport bytes with -s; these are not tokens."""
    from test_managed_description_scopes import _service

    from sciplot_core.mcp_server import server
    from sciplot_core.mcp_server.schemas import tool_definitions

    def encoded_bytes(value) -> int:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8"))

    tool_items = [item.model_dump(mode="json", by_alias=True, exclude_none=True)
                  for item in tool_definitions()]
    edit_names = {"sciplot_project_open", "sciplot_plot_describe",
                  "sciplot_plot_patch", "sciplot_plot_intent"}
    counts = {
        "tool_count": len(tool_items),
        "all_tool_definitions_array_bytes": encoded_bytes(tool_items),
        "four_edit_tool_definitions_array_bytes": encoded_bytes(
            [item for item in tool_items if item["name"] in edit_names]),
        "server_instructions_utf8_bytes": len(server.INSTRUCTIONS.encode("utf-8")),
    }
    with TemporaryDirectory() as directory:
        service, root, _ = _service(Path(directory), monkeypatch)
        cases = {
            "full_open": ("sciplot_project_open", {"target": str(root)}, service.open(root)),
            "managed_summary": ("sciplot_project_open", {"target": str(root),
                                "description": {"scope": "summary"}},
                                service.open(root, description={"scope": "summary"})),
            "axis_label_edit": ("sciplot_plot_describe", {"plot": str(root), "description": {
                "scope": "edit", "target": "axis:xb", "property": "axis.label"}},
                service.describe(root, description={"scope": "edit", "target": "axis:xb",
                                                    "property": "axis.label"})),
        }
        for label, (name, arguments, payload) in cases.items():
            monkeypatch.setattr(server, "invoke_owner", lambda *_args, result=payload: result)
            result = server.Adapter()._execute(name, arguments)
            counts[label + "_mcp_call_result_bytes"] = encoded_bytes(
                result.model_dump(mode="json", by_alias=True, exclude_none=True))
    counts["summary_plus_edit_mcp_call_result_bytes"] = (
        counts["managed_summary_mcp_call_result_bytes"] +
        counts["axis_label_edit_mcp_call_result_bytes"])
    assert counts["summary_plus_edit_mcp_call_result_bytes"] < counts["full_open_mcp_call_result_bytes"]
    print(json.dumps(counts, indent=2, sort_keys=True))
