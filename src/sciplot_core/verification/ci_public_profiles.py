"""Run public stages while keeping detailed evidence out of the Actions console."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

DIRECTORY = ".tmp_verify/ci-public-profiles"
PROGRESS_INTERVAL_SECONDS = 120


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _progress(paths: list[Path]) -> None:
    for path in reversed(paths):
        value = _read_object(path / "pytest-progress.json")
        if value:
            print(f"{path.name}: {value.get('completed')}/{value.get('selected_count')} completed; "
                  f"{value.get('failed')} failed, latest {value.get('latest_phase')} "
                  f"{str(value.get('latest_node'))[:400]}", flush=True)
            return
    print("Public verification: waiting for the first test checkpoint.", flush=True)


def report_profile(path: Path, result: dict[str, Any]) -> None:
    """Console is an index; original reports, stdout and result stay unchanged."""
    finish = result.get("finish", {})
    reports = _read_object(path / "reports.json").get("reports", [])
    failed: dict[str, list[str]] = {}
    for row in reports if isinstance(reports, list) else ():
        if (isinstance(row, dict) and row.get("outcome") == "failed"
                and isinstance(row.get("nodeid"), str) and isinstance(row.get("when"), str)):
            failed.setdefault(row["nodeid"], []).append(row["when"])
    print(f"{result.get('profile', path.name)} {result['status']}: "
          f"{len(finish.get('selected_tests', []))} selected, {len(finish.get('executed_tests', []))} passed bodies, "
          f"{len(failed)} failed nodes, original exit {result.get('actual_exit_code')}.", flush=True)
    if result["status"] != "PASS":
        for nodeid, phases in failed.items():
            print(f"FAILED {nodeid} [{', '.join(phases)}]", flush=True)
        for issue in result.get("issues", []):
            print(f"Evidence issue: {issue[:500]}", flush=True)
        detail = path / "command.log"
        if not failed and detail.is_file():
            # A collection/usage crash can happen before report hooks run.
            # Keep the original log; show its final diagnostic without dumping it.
            with detail.open("rb") as stream:
                stream.seek(max(0, detail.stat().st_size - 8192))
                final = stream.read().decode("utf-8", errors="replace").splitlines()
            for line in final[-10:]:
                print(f"pytest: {line[:500]}", flush=True)


def run_profile(root: Path, profile: str) -> int:
    directory = root / DIRECTORY
    if (root / ".tmp_verify").is_symlink() or directory.is_symlink():
        raise ValueError("CI evidence roots cannot follow aliases.")
    environment = dict(os.environ)
    output = ".tmp_verify/ci_public_" + profile
    command = [sys.executable, "-m", "sciplot_core.verification.public_stage",
               "--profile", "public-ci-full" if profile == "full" else "public-" + profile, "--out", output]
    result_directories = ([root / output / ("public-" + tier) for tier in ("focused", "comprehensive")]
                          if profile == "full" else [root / output])
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f"{profile}.log"
    with log.open("xb") as stream, subprocess.Popen(
        command, cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT,
    ) as child:
        while True:
            try:
                code = child.wait(timeout=PROGRESS_INTERVAL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                _progress(result_directories)
    expected_head = environment.get("GITHUB_SHA")
    for path in result_directories:
        result = _read_object(path / "result.json")
        if result:
            report_profile(path, result)
        if code == 0 and expected_head and result.get("origin_head") != expected_head:
            raise ValueError("Actual public stage source differs from GITHUB_SHA.")
    if code and not any((path / "result.json").is_file() for path in result_directories):
        failure = _read_object(log)
        detail = failure.get("error")
        print(f"Public verification exited {code} before creating a result."
              + (f" {detail[:1000]}" if isinstance(detail, str) else ""), flush=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("focused", "comprehensive", "full"))
    args = parser.parse_args()
    return run_profile(Path(__file__).resolve().parents[3], args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
