#!/usr/bin/env python3
"""Validate the frozen feature contract without treating claims as coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORACLE_REVISION = "6e71625b9e6cffeda268b548ae7f43a7643fc3f0"
PATCH_DIGEST = "253eac3fc84c67b0844baf97ad959a077e2e82f97dd39f0d796da918c6301f24"

TOP_LEVEL_KEYS = {
    "schema_version", "manifest_version", "oracle", "format", "scope",
    "observables", "inventories", "features", "interaction_requirements",
}
FEATURE_KEYS = {
    "id", "kind", "title", "required", "denotation", "members",
    "showdown_sources", "native_boundaries", "depends_on", "observables",
    "focused_tests", "differential_cases", "coverage_axes", "invariants", "status",
}


def duplicate_ids(records: list[dict[str, object]]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        identifier = str(record["id"])
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    return duplicates


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: validate_manifest.py SCHEMA MANIFEST")

    # Parse the checked-in schema as a frozen artifact, but keep this verifier
    # stdlib-only so a missing pip package cannot silently disable the gate.
    json.loads(Path(sys.argv[1]).read_text())
    manifest = json.loads(Path(sys.argv[2]).read_text())
    structural_failures: list[str] = []
    readiness_failures: list[str] = []

    if set(manifest) != TOP_LEVEL_KEYS:
        structural_failures.append(
            f"top-level keys differ: missing={sorted(TOP_LEVEL_KEYS - set(manifest))} "
            f"extra={sorted(set(manifest) - TOP_LEVEL_KEYS)}"
        )
    if manifest.get("schema_version") != 1:
        structural_failures.append("schema_version must be 1")

    features = manifest.get("features", [])
    inventories = manifest.get("inventories", [])
    interactions = manifest.get("interaction_requirements", [])
    feature_ids = {feature["id"] for feature in features}
    inventory_ids = {inventory["id"] for inventory in inventories}

    for label, records in (("feature", features), ("inventory", inventories), ("interaction", interactions)):
        for identifier in sorted(duplicate_ids(records)):
            structural_failures.append(f"duplicate {label} id: {identifier}")

    for feature in features:
        identifier = feature["id"]
        if set(feature) != FEATURE_KEYS:
            structural_failures.append(f"{identifier}: feature keys differ from schema")
        if not isinstance(feature["required"], bool):
            structural_failures.append(f"{identifier}: required must be boolean")
        for mapping in ("showdown_sources", "native_boundaries"):
            for reference in feature[mapping]:
                if set(reference) != {"path", "symbol"} or not all(
                    isinstance(value, str) and value for value in reference.values()
                ):
                    structural_failures.append(f"{identifier}: malformed {mapping} reference")
        for dependency in feature["depends_on"]:
            if dependency not in feature_ids:
                structural_failures.append(f"{identifier}: unknown dependency {dependency}")
        inventory = feature["members"]["inventory"]
        if inventory is not None and inventory not in inventory_ids:
            structural_failures.append(f"{identifier}: unknown inventory {inventory}")
        if feature["required"]:
            for mapping in ("showdown_sources", "native_boundaries", "focused_tests", "differential_cases"):
                if not feature[mapping]:
                    readiness_failures.append(f"{identifier}: required mapping {mapping} is empty")
            if feature["status"] != "complete":
                readiness_failures.append(
                    f"{identifier}: required feature status is {feature['status']!r}, not 'complete'"
                )

    for interaction in interactions:
        for feature_id in interaction["features"]:
            if feature_id not in feature_ids:
                structural_failures.append(f"{interaction['id']}: unknown feature {feature_id}")

    oracle = manifest.get("oracle", {})
    if oracle.get("commit") != ORACLE_REVISION:
        structural_failures.append("oracle revision does not match verifier lock")
    if oracle.get("instrumentation_digest") != PATCH_DIGEST:
        structural_failures.append("instrumentation digest does not match verifier patch")

    result = {
        "schema_valid": not structural_failures,
        "completion_ready": not structural_failures and not readiness_failures,
        "structural_failures": structural_failures,
        "readiness_failures": readiness_failures,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not structural_failures and not readiness_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
