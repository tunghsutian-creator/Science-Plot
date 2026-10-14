from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--input-scope", choices=("public-focused", "public-comprehensive", "public-all", "private-science"),
                     help="Exact reviewed test-input scope; default pytest retains the complete suite.")


def pytest_ignore_collect(collection_path, config: pytest.Config) -> bool | None:
    # These are data namespaces, never test source modules. Scoped collection
    # still imports every test module and validates the complete exact node union.
    # Avoid pytest traversing forbidden raw/golden directories just to find tests.
    if config.getoption("input_scope"):
        from pathlib import Path
        root = Path(__file__).parent / "fixtures"
        if collection_path in {root / name for name in ("real_world", "polymer_corpus", "archived_output_raw_data", "rendering_profiles")}:
            return True
    return None


def pytest_configure(config: pytest.Config) -> None:
    scope = config.getoption("input_scope")
    if scope and scope.startswith("public-"):
        import os
        from pathlib import Path

        from sciplot_core.verification.public_input_guard import BOOTSTRAP_KEY, configure_environment, install
        bootstrap = None if os.environ.get(BOOTSTRAP_KEY) else Path(__file__).parents[1] / "src/sciplot_core/verification/public_guard_bootstrap"
        os.environ.update(configure_environment(Path(__file__).parents[1], dict(os.environ), bootstrap=bootstrap))
        install()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Make the focused and comprehensive tiers exhaustive and disjoint."""
    focused = pytest.mark.focused
    for item in items:
        comprehensive_marker = item.get_closest_marker("comprehensive")
        focused_marker = item.get_closest_marker("focused")
        if comprehensive_marker is not None and focused_marker is not None:
            raise pytest.UsageError(
                f"{item.nodeid} cannot be both focused and comprehensive"
            )
        if comprehensive_marker is None and focused_marker is None:
            item.add_marker(focused)
    profile = config.getoption("input_scope")
    if profile is None:
        return
    from pathlib import Path

    from sciplot_core.verification.input_scope import load_manifest, select_scope
    from sciplot_core.verification.private_corpus import INVENTORY, declared_input_availability
    import json

    root = Path(__file__).parents[1]
    collected = [item.nodeid for item in items]
    try:
        private = {row["nodeid"] for row in json.loads(INVENTORY.read_text())["cases"]}
        selected = set(select_scope(profile, manifest=load_manifest(), collected=collected,
                                    tiers={item.nodeid: "comprehensive" if item.get_closest_marker("comprehensive") else "focused"
                                           for item in items}, private_nodes=private))
        if profile == "private-science":
            availability = declared_input_availability(repo_root=root, selected_nodeids=sorted(selected),
                                                       collected_nodeids=set(collected))
            if availability["status"] == "BLOCKED":
                raise ValueError("Private input availability BLOCKED before test bodies: " + json.dumps(availability["issues"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise pytest.UsageError(str(exc)) from exc
    rejected = [item for item in items if item.nodeid not in selected]
    config.hook.pytest_deselected(items=rejected)
    items[:] = [item for item in items if item.nodeid in selected]
