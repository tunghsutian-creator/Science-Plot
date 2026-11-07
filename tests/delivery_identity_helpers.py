"""Generate historical v1 shell bytes only for compatibility counterexamples."""

from pathlib import Path
from sciplot_core.delivery_identity import DeliveryBinding
from sciplot_core.launchers.delivery_launcher import _delivery_launcher_lines
from sciplot_core.policy import DELIVERY_LAUNCHER


def write_legacy_delivery_launcher(root: Path, *, binding: DeliveryBinding | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / DELIVERY_LAUNCHER
    path.write_text("\n".join(_delivery_launcher_lines(binding)) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path
