from __future__ import annotations

from collections.abc import Iterator
import hashlib
from pathlib import Path
import tempfile

import pytest


@pytest.fixture(scope="session")
def _recorded_test_host() -> Iterator[Path]:
    from platformdirs import user_cache_path
    from sciplot_core.foundation.research_destination import require_data_destination

    # Ordinary pytest tmp_path may itself be in the disposable SciPlot cache.
    # A child process uses real host providers, so this simulated recorded host
    # must be physically external too. Only this fixture's synthetic data is
    # removed at session end; real recorded evidence has no automatic cleanup.
    with tempfile.TemporaryDirectory(prefix="sciplot-recorded-unit-host-") as directory:
        host = Path(directory).resolve()
        cache = user_cache_path("SciPlot").resolve()
        assert host != cache and not host.is_relative_to(cache)
        assert require_data_destination(host) == host
        yield host


@pytest.fixture(autouse=True)
def _isolated_recorded_host(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, _recorded_test_host: Path,
) -> None:
    """Keep simulated recorded hosts out of the real persistent user state.

    Only the host path providers are replaced. The production allocator,
    source boundary and fresh directory identity checks run unchanged.
    """
    from sciplot_core.verification import recorded_workspace
    from sciplot_core.foundation import research_destination

    node = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()
    host = _recorded_test_host / node
    def cache_path(_app: str) -> Path:
        return host / "cache"
    monkeypatch.setattr(recorded_workspace, "user_state_path", lambda _app: host / "state")
    monkeypatch.setattr(recorded_workspace, "user_cache_path", cache_path)
    monkeypatch.setattr(research_destination, "user_cache_path", cache_path)


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
