#!/usr/bin/env python3
"""Fail closed unless every frozen oracle artifact agrees with oracle.lock."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    tests_dir = Path(__file__).resolve().parent
    task_dir = tests_dir.parent
    lock = tomllib.loads((tests_dir / "oracle.lock").read_text())
    patch = tests_dir / lock["trace_patch"]
    actual = digest(patch)
    sidecar = (tests_dir / "oracle-observer.sha256").read_text().split()[0]
    locked = lock["trace_patch_sha256"]

    if len({actual, sidecar, locked}) != 1:
        print(
            f"observer patch digest mismatch: actual={actual} sidecar={sidecar} lock={locked}",
            file=sys.stderr,
        )
        return 1

    artifacts = {
        "trace_smoke_script_sha256": tests_dir / "oracle_smoke.js",
        "feature_schema_sha256": task_dir / "feature-map.schema.json",
        "supported_features_sha256": task_dir / "supported-features.json",
        "case_schema_sha256": task_dir / "case.schema.json",
        "seed42_battle04_case_sha256": tests_dir / "cases/seed42-battle04.case",
    }
    for key, path in artifacts.items():
        observed = digest(path)
        if observed != lock[key]:
            print(f"{key} mismatch: actual={observed} lock={lock[key]}", file=sys.stderr)
            return 1

    smoke = (tests_dir / "oracle-smoke.sha256").read_text().split()[0]
    if smoke != lock["trace_smoke_sha256"]:
        print(
            f"trace_smoke_sha256 mismatch: sidecar={smoke} lock={lock['trace_smoke_sha256']}",
            file=sys.stderr,
        )
        return 1

    if len(sys.argv) != 3:
        print("usage: validate_oracle_lock.py CLEAN_SHOWDOWN PATCHED_SHOWDOWN", file=sys.stderr)
        return 2
    for label, checkout in zip(("clean", "patched"), map(Path, sys.argv[1:])):
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
        ).strip()
        if revision != lock["revision"]:
            print(f"{label} oracle revision={revision} lock={lock['revision']}", file=sys.stderr)
            return 1
    for key, name in (("package_json_sha256", "package.json"), ("package_lock_sha256", "package-lock.json")):
        observed = digest(Path(sys.argv[1]) / name)
        if observed != lock[key]:
            print(f"{key} mismatch: actual={observed} lock={lock[key]}", file=sys.stderr)
            return 1

    print(f"oracle lock verified: revision={lock['revision']} patch={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
