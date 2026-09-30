from __future__ import annotations

import json
import os
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

from .astgrep import Match
from .target import Target, Violation

LOCK_NAMES = ("uv.lock", "bun.lock", "package-lock.json")
CITE_PACKAGE = re.compile(r"EXTERNAL\(([A-Za-z0-9_.@/-]+)==(\S+) (\S+):([0-9]+)-([0-9]+)\): \S")
CITE_GIT = re.compile(
  r"EXTERNAL\(([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([0-9a-f]{7,40}) (\S+):L([0-9]+)-L([0-9]+)\): \S"
)
CITE_URL = re.compile(r"EXTERNAL\((https://\S+) @([0-9]{4}-[0-9]{2}-[0-9]{2})\): \S")
CITATION_FORMATS = (
  "EXTERNAL(<pkg>==<ver> <path>:<a>-<b>) | (<owner>/<repo>@<sha> <path>:L<a>-L<b>)"
  " | (<https-url> @<YYYY-MM-DD>), then ': <fact>'"
)
TRAILING_COMMA = re.compile(r",(\s*[}\]])")
PEP503_SEPARATORS = re.compile(r"[-_.]+")
QUOTE_CHARS = 100


@dataclass(frozen=True)
class PackageCitation:
  name: str
  version: str


@dataclass(frozen=True)
class SourceCitation:
  key: str


Citation = PackageCitation | SourceCitation


def check_comments(matches: list[Match]) -> list[Violation]:
  return [
    Violation(m.file, m.line, "comment", f"only directives and EXTERNAL(...): {_quote(m.text)}")
    for m in matches
    if m.family == "no-comments"
  ]


def check_docstrings(matches: list[Match]) -> list[Violation]:
  return [
    Violation(m.file, m.line, "docstring", "no docstrings: names, asserts and tests carry the why")
    for m in matches
    if m.family == "no-docstrings"
  ]


def check_citations(
  target: Target, matches: list[Match]
) -> tuple[list[Violation], Counter[str], tuple[str, ...]]:
  locks = lock_paths(target)
  versions = lock_versions(target.root, locks)
  violations: list[Violation] = []
  counts: Counter[str] = Counter()
  for m in matches:
    if m.family != "citation":
      continue
    citation = parse_citation(m.text)
    problem = _citation_problem(citation, versions)
    if problem is not None:
      violations.append(Violation(m.file, m.line, "citation", f"{problem}: {_quote(m.text)}"))
      continue
    assert citation is not None
    counts[citation.name if isinstance(citation, PackageCitation) else citation.key] += 1
  return violations, counts, locks


def parse_citation(comment: str) -> Citation | None:
  body = comment.lstrip("#/").strip()
  package = CITE_PACKAGE.match(body)
  if package is not None:
    start, end = int(package.group(4)), int(package.group(5))
    return PackageCitation(normalize(package.group(1)), package.group(2)) if start <= end else None
  git = CITE_GIT.match(body)
  if git is not None:
    return SourceCitation(git.group(1)) if int(git.group(4)) <= int(git.group(5)) else None
  url = CITE_URL.match(body)
  if url is not None and _is_date(url.group(2)):
    return SourceCitation(urlparse(url.group(1)).netloc)
  return None


def _citation_problem(citation: Citation | None, versions: dict[str, set[str]]) -> str | None:
  if citation is None:
    return f"malformed citation, want {CITATION_FORMATS}"
  if not isinstance(citation, PackageCitation):
    return None
  locked = versions.get(citation.name)
  if locked is None:
    return f"cites {citation.name}=={citation.version} but no lockfile has {citation.name}"
  if citation.version not in locked:
    return f"cites {citation.name}=={citation.version} but the lockfile has {sorted(locked)}"
  return None


def _is_date(text: str) -> bool:
  try:
    date.fromisoformat(text)
  except ValueError:
    return False
  return True


def _quote(text: str) -> str:
  return repr(text[:QUOTE_CHARS])


def normalize(name: str) -> str:
  return PEP503_SEPARATORS.sub("-", name).lower()


def lock_paths(target: Target) -> tuple[str, ...]:
  configured = target.cfg.comments.locks
  if configured is not None:
    candidates = set(configured)
  else:
    listed = {f for f in target.files if os.path.basename(f) in LOCK_NAMES}
    candidates = listed | set(LOCK_NAMES)
  return tuple(sorted(p for p in candidates if os.path.isfile(os.path.join(target.root, p))))


def lock_versions(root: str, locks: tuple[str, ...]) -> dict[str, set[str]]:
  versions: dict[str, set[str]] = {}
  for lock in locks:
    with open(os.path.join(root, lock), "rb") as f:
      raw = f.read()
    for name, version in _parse_lock(lock, raw):
      versions.setdefault(normalize(name), set()).add(version)
  return versions


def _parse_lock(lock: str, raw: bytes) -> list[tuple[str, str]]:
  kind = os.path.basename(lock)
  if kind == "uv.lock":
    packages = tomllib.loads(raw.decode()).get("package", [])
    return [(p["name"], p["version"]) for p in packages if "version" in p]
  if kind == "bun.lock":
    # bun.lock is JSON with trailing commas; each package is ["<name>@<version>", ...].
    doc = json.loads(TRAILING_COMMA.sub(r"\1", raw.decode()))
    specs = [entry[0] for entry in doc.get("packages", {}).values()]
    pairs = [spec.rpartition("@") for spec in specs if spec.rfind("@") > 0]
    return [(name, version) for name, _, version in pairs]
  if kind == "package-lock.json":
    doc = json.loads(raw)
    if "packages" not in doc:
      raise ValueError(f"{lock}: lockfileVersion {doc.get('lockfileVersion')} has no packages")
    packages = doc["packages"].items()
    return [
      (path.rpartition("node_modules/")[2], p["version"])
      for path, p in packages
      if path and "version" in p
    ]
  raise ValueError(f"{lock}: not one of {LOCK_NAMES}")
