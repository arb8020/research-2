#!/usr/bin/env python3
"""Compare aligned JSONL boundaries and preserve first-divergence evidence."""

import json
import sys
from pathlib import Path


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def first_difference(left, right, field="$"):
    if type(left) is not type(right):
        return field, left, right
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{field}.{key}", left.get(key, "<missing>"), right.get(key, "<missing>")
            difference = first_difference(left[key], right[key], f"{field}.{key}")
            if difference:
                return difference
    elif isinstance(left, list):
        if len(left) != len(right):
            return f"{field}.length", len(left), len(right)
        for index, (left_value, right_value) in enumerate(zip(left, right)):
            difference = first_difference(left_value, right_value, f"{field}[{index}]")
            if difference:
                return difference
    elif left != right:
        return field, left, right
    return None


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: compare_boundaries.py ORACLE NATIVE ARTIFACT")
    oracle_path, native_path, artifact_path = map(Path, sys.argv[1:])
    oracle, native = load(oracle_path), load(native_path)
    difference = first_difference(oracle, native)
    result = {
        "schema": "gen3ou-first-divergence-v1",
        "equal": difference is None,
        "oracle": str(oracle_path),
        "native": str(native_path),
    }
    if difference:
        field, oracle_value, native_value = difference
        result["first_unequal_field"] = field
        result["oracle_value"] = oracle_value
        result["native_value"] = native_value
    artifact_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if difference is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
