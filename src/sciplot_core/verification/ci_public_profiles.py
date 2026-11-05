"""Run fresh public stages and stream their original progress and exit."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

DIRECTORY = ".tmp_verify/ci-public-profiles"


def run_profile(root: Path, profile: str) -> int:
    directory = root / DIRECTORY
    if (root / ".tmp_verify").is_symlink() or directory.is_symlink():
        raise ValueError("CI evidence roots cannot follow aliases.")
    environment = dict(os.environ)
    command = [sys.executable, "-m", "sciplot_core.verification.public_stage", "--profile", "public-" + profile,
               "--out", ".tmp_verify/ci_public_" + profile]
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f"{profile}.log"
    with log.open("x") as stream:
        # Same owned command.log stream previously used by comprehensive in Actions.
        # It is progress only; the original stage exit/finish/reports own completion.
        progress = subprocess.Popen(["tail", "-n", "+1", "--follow=name", "--retry",
                                     str(root / f".tmp_verify/ci_public_{profile}/command.log")],
                                    env=environment, stderr=subprocess.DEVNULL)
        try:
            child = subprocess.Popen(command, cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert child.stdout is not None
            for line in child.stdout:
                print(line, end="", flush=True)
                stream.write(line)
            code = child.wait()
        finally:
            if progress.poll() is None:
                progress.terminate()
            progress.wait()
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("focused", "comprehensive"))
    args = parser.parse_args()
    return run_profile(Path(__file__).resolve().parents[3], args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
