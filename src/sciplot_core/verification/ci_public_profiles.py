"""Run public stages while keeping detailed evidence out of the Actions console."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from sciplot_core.verification.public_stage_selection import COMPREHENSIVE_SHARDS

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


def _console_tail(path: Path, prefix: str) -> None:
    if not path.is_file():
        return
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 8192))
        final = stream.read().decode("utf-8", errors="replace").splitlines()
    for line in final[-10:]:
        print(f"{prefix}: {line[:500]}", flush=True)


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
        if not failed:
            # A collection/usage crash can happen before report hooks run.
            _console_tail(path / "command.log", "pytest")


def run_profile(root: Path, profile: str) -> int:
    directory = root / DIRECTORY
    if (root / ".tmp_verify").is_symlink() or directory.is_symlink():
        raise ValueError("CI evidence roots cannot follow aliases.")
    environment = dict(os.environ)
    output = ".tmp_verify/ci_public_" + profile
    grouped = {"full": ("public-ci-full", "public-comprehensive"),
               "primary": ("public-ci-primary", COMPREHENSIVE_SHARDS[1])}
    name, comprehensive = grouped.get(profile, ("public-" + profile, ""))
    command = [sys.executable, "-m", "sciplot_core.verification.public_stage",
               "--profile", name, "--out", output]
    result_directories = ([root / output / tier for tier in ("public-focused", comprehensive)]
                          if comprehensive else [root / output])
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
    missing_results = []
    for path in result_directories:
        result = _read_object(path / "result.json")
        if result:
            report_profile(path, result)
        else:
            missing_results.append(path.name)
        if code == 0:
            if expected_head and result.get("origin_head") != expected_head:
                raise ValueError("Actual public stage source differs from GITHUB_SHA.")
            if result.get("status") != "PASS":
                raise ValueError("Successful public command is missing an exact passing stage result.")
            if profile in {"primary", "comprehensive-first"}:
                expected = path.name if comprehensive else name
                if result.get("profile") != expected or result.get("canonical_profile_executed") is not (expected == "public-focused"):
                    raise ValueError("Actual public stage does not prove the expected profile or shard.")
    if code:
        failure = _read_object(log)
        detail = failure.get("error")
        stages = f"; no result: {', '.join(missing_results)}" if missing_results else ""
        if isinstance(detail, str) or missing_results:
            print(f"Public verification exited {code}{stages}."
                  + (f" {detail[:1000]}" if isinstance(detail, str) else ""), flush=True)
        if missing_results and not failure:
            _console_tail(log, "public stage")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("focused", "comprehensive", "full", "primary", "comprehensive-first"))
    args = parser.parse_args()
    return run_profile(Path(__file__).resolve().parents[3], args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
