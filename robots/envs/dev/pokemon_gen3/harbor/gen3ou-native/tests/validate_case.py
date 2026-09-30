#!/usr/bin/env python3
"""Validate a verifier-owned differential case and its closed references."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: validate_case.py SCHEMA CASE FEATURE_MANIFEST")

    schema_path = Path(sys.argv[1]).resolve()
    case_path = Path(sys.argv[2]).resolve()
    schema = json.loads(schema_path.read_text())
    case = json.loads(case_path.read_text())
    manifest = json.loads(Path(sys.argv[3]).read_text())
    failures: list[str] = []
    for error in sorted(
        Draft202012Validator(schema).iter_errors(case), key=lambda item: list(item.path)
    ):
        location = ".".join(str(part) for part in error.path) or "$"
        failures.append(f"schema:{location}: {error.message}")

    # Team references are verifier-owned leaf filenames. Resolve them only
    # after schema validation and prove that resolution stays beside the case.
    case_dir = case_path.parent
    team_bytes: list[bytes] = []
    for reference in case.get("teams", {}).get("values", []):
        candidate = (case_dir / reference).resolve()
        if candidate.parent != case_dir:
            failures.append(f"team reference escapes case directory: {reference}")
            continue
        if not candidate.is_file():
            failures.append(f"missing team fixture: {reference}")
            continue
        team_bytes.append(candidate.read_bytes())
    if len(team_bytes) == 2:
        digest = hashlib.sha256(team_bytes[0] + b"\0" + team_bytes[1]).hexdigest()
        if digest != case.get("teams", {}).get("normalization_digest"):
            failures.append("team normalization_digest does not match fixture bytes")

    feature_ids = {item["id"] for item in manifest.get("features", [])}
    interaction_ids = {item["id"] for item in manifest.get("interaction_requirements", [])}
    for feature_id in case.get("features", []):
        if feature_id not in feature_ids:
            failures.append(f"unknown feature id: {feature_id}")
    for interaction_id in case.get("interactions", []):
        if interaction_id not in interaction_ids:
            failures.append(f"unknown interaction id: {interaction_id}")

    print(json.dumps({"valid": not failures, "failures": failures}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
