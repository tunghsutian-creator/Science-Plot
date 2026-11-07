"""Generate historical v1 shell bytes only for compatibility counterexamples."""

from pathlib import Path
from copy import deepcopy
from sciplot_core.delivery_identity import DeliveryBinding, DELIVERY_IDENTITY, read_delivery_binding
from sciplot_core.launchers.delivery_inspection import inspect_delivery_launcher_contract
from sciplot_core.launchers.delivery_launcher import _delivery_launcher_lines
from sciplot_core.policy import DELIVERY_LAUNCHER


def write_legacy_delivery_launcher(root: Path, *, binding: DeliveryBinding | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / DELIVERY_LAUNCHER
    path.write_text("\n".join(_delivery_launcher_lines(binding)) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def make_generated_v6_fixture(root: Path, current: dict) -> dict:
    """Create old bytes in a detached test stage, never certify a user history."""
    record = deepcopy(current)
    launcher = write_legacy_delivery_launcher(root, binding=read_delivery_binding(root))
    (root / DELIVERY_IDENTITY).unlink()
    record["version"] = 6
    for key in ("identity", "identity_sha256", "identity_contract"):
        record.pop(key)
    contract = inspect_delivery_launcher_contract(root)
    record.update(open_in_veusz=str(launcher), open_in_veusz_sha256=contract["content_sha256"], launcher_contract=contract)
    for artifact in record["artifacts"]:
        if artifact["id"] == "delivery_identity":
            artifact.update(id="open_in_veusz", path=str(launcher), details=contract)
    return record
