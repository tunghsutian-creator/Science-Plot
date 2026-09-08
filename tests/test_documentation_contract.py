from __future__ import annotations

from pathlib import Path


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
    skill = _read(REPO_ROOT / "skill" / "SKILL.md")
    architecture = _read(REPO_ROOT / "docs" / "ARCHITECTURE.md")

    assert "declared under `[tool.mypy]` in `pyproject.toml`" in skill
    assert "Its exact scope and strictness belong to `pyproject.toml`." in skill
    assert "configured files" not in skill
    assert "The exact strict Python diagnostic scope" in architecture
    assert "all strictness options belong only to `[tool.mypy]`" in architecture
    assert "without maintaining another scope list or file count" in architecture
    assert "Strict Python 3.11 baseline for `foundation/`" not in architecture


def test_self_use_edit_guidance_keeps_deferred_readiness_and_full_evidence():
    guide = _read(REPO_ROOT / "skill/references/external-control.md")
    assert '"export":false' in guide and 'status:"saved"' in guide
    assert "not a publication receipt" in guide
    assert "--full" in guide and "review_path" in guide
    assert "compact stdout is a summary, not an apply file" in guide
    assert "set_sample_style" in guide and "figures[].sample_styles" in guide
    assert "ambiguous labels are rejected" in guide
