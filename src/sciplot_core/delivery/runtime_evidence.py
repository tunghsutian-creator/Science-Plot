"""Keep recorded delivery identities distinct from their scoped physical IO."""

from pathlib import Path
from contextlib import ExitStack
from typing import Any

from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.policy import DELIVERY_EDITOR_LAUNCHER
from sciplot_core.project_store.runtime import projected_runtime_artifact, project_read_window


def path_identity(value: Path) -> Path:
    """The existing locator owns identity; no package field is rewritten."""
    return Path(literal_source_path(value))


def launcher_contract_identity(value: object) -> object:
    """Only the observed path differs after an explicit whole-project import."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return value
    return {**value, "path": str(path_identity(Path(value["path"])))}


def recorded_path_exists(value: Any) -> bool:
    return projected_runtime_artifact(str(value)).exists()


def recorded_artifacts_ready(artifacts: Any) -> bool:
    """Observe the finite recorded artifact set without spanning raw hash IO."""
    if not isinstance(artifacts, list) or not artifacts:
        return False
    with ExitStack() as scope:
        entered = False
        for item in artifacts:
            if (not isinstance(item, dict) or item.get("exists") is not True
                    or not isinstance(item.get("path"), str)):
                return False
            if not entered:
                scope.enter_context(project_read_window())
                entered = True
            if not recorded_path_exists(item["path"]):
                return False
        return True


def recorded_editor_launcher_current(
    record: dict[str, Any], *, expected_root: Path, contract: dict[str, object],
) -> bool:
    """Match every recorded legacy editor field; a partial record is invalid."""
    path = record.get("open_in_sciplot")
    return bool(
        isinstance(path, str)
        and path.strip()
        and path_identity(Path(path).expanduser())
        == path_identity(expected_root / DELIVERY_EDITOR_LAUNCHER)
        and contract.get("ready") is True
        and record.get("open_in_sciplot_sha256") == contract.get("content_sha256")
        and launcher_contract_identity(record.get("editor_launcher_contract"))
        == launcher_contract_identity(contract)
    )


def recorded_delivery_identity(record: dict[str, Any], root: Path) -> tuple[dict[str, bool], dict[str, object], str]:
    """Keep v6 executable evidence and v7 inert evidence explicitly distinct."""
    from sciplot_core.delivery_identity import DELIVERY_IDENTITY, inspect_delivery_identity
    from sciplot_core.launchers import inspect_delivery_launcher_contract
    from sciplot_core.policy import DELIVERY_LAUNCHER

    current = record.get("version") == 7
    name = DELIVERY_IDENTITY if current else DELIVERY_LAUNCHER
    prefix = "identity" if current else "launcher"
    field = "identity" if current else "open_in_veusz"
    observed = inspect_delivery_identity(root) if current else inspect_delivery_launcher_contract(root)
    recorded_path = record.get(field)
    path_current = bool(isinstance(recorded_path, str) and recorded_path.strip()
                        and path_identity(Path(recorded_path).expanduser()) == path_identity(root / name))
    digest = record.get(field + "_sha256")
    checks = {
        prefix + "_path_current": path_current,
        prefix + "_hash_current": bool(digest and digest == observed.get("content_sha256")),
        prefix + "_structure_current": observed.get("ready") is True,
        prefix + "_contract_current": bool(record.get(prefix + "_contract")
            and launcher_contract_identity(record[prefix + "_contract"]) == launcher_contract_identity(observed)),
    }
    if not current:
        checks["launcher_structure_current"] = bool(checks["launcher_structure_current"]
            and observed.get("canonical_structure") is True and observed.get("required_command_present") is True)
    checks[prefix + "_current"] = all(checks.values())
    return checks, observed, name
