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

    assert "绘图交付不要写进 SciPlot 软件或代码仓库内部的 `outputs/`。" in readme
    assert "优先省略 `--out`" in readme
    assert "在原数据旁创建 `SOURCE_SciPlot/`" in readme

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

    assert "本文是用户工作流和产品边界的唯一说明" in readme
    assert "This skill owns agent routing and verification." in skill
    assert "current module-ownership and dependency reference" in architecture
    assert "R0 complete; paused before R1 authorization" in roadmap
    assert "当前唯一候选下一步是 R1，尚未授权" in roadmap
    assert "docs/AUTOMATION_CONTROL_CONTRACT.md" in roadmap
    assert "R0 frozen design draft; not current runtime behavior" in automation_contract
    assert "does not add a conductor" in automation_contract
    assert "R0 automation baseline evidence" in architecture


def test_human_confirmation_is_a_real_operation_gate_not_a_generic_runtime() -> None:
    roadmap = _normalized(REPO_ROOT / "DEVELOPMENT_ROADMAP.md")
    automation_contract = _normalized(AUTOMATION_CONTROL_CONTRACT)

    assert "2026-09-01 人工确认范围决定" in roadmap
    assert "不预建通用问题生成器" in roadmap
    assert "`decision.question`" in roadmap
    assert "显式为 `null`" in roadmap
    assert "真实一问一答不作为 R2 退出门" in roadmap
    assert "R5 的首个试点限定为真实且可由 rule identity selection 解除的歧义" in roadmap
    assert "显式 `--rule`" in roadmap
    assert "fresh `plan`" in roadmap
    assert "同一显式 rule" in roadmap
    assert "原始源 hash 未变" in roadmap
    assert "一次真实 `needs_human_confirmation`" not in roadmap
    assert (
        "A bounded question payload is no longer an R1/R2 exit requirement"
        in automation_contract
    )
    assert "generic question generator is explicitly out of scope" in automation_contract
    assert (
        "`decision.question` is a closed, explicitly nullable pass-through field"
        in automation_contract
    )
    assert (
        "R5 owns one real ambiguity that can be resolved by rule-identity"
        in automation_contract
    )
    assert "scientific facts must not be encoded into `--rule`" in automation_contract
    assert "not manufactured as a pilot exit gate" in automation_contract
    assert "DataMapping receipts and rheology" in automation_contract
    assert "complete zero-write confirmation handoff" in automation_contract
    assert (
        "R1/R2 must add and test exactly one bounded question"
        not in automation_contract
    )


def test_skill_defers_the_exact_mypy_scope_to_pyproject() -> None:
    readme = _read(REPO_ROOT / "README.md")
    skill = _read(REPO_ROOT / "skill" / "SKILL.md")
    architecture = _read(REPO_ROOT / "docs" / "ARCHITECTURE.md")

    assert "`[tool.mypy]` 中声明的路径" in readme
    assert "精确范围、文件数量和严格选项的唯一权威" in readme
    assert "42 个文件" not in readme
    assert "declared under `[tool.mypy]` in `pyproject.toml`" in skill
    assert "Its exact scope and strictness belong to `pyproject.toml`." in skill
    assert "configured files" not in skill
    assert "The exact strict Python diagnostic scope" in architecture
    assert "Strict Python 3.11 baseline for `foundation/`" not in architecture
