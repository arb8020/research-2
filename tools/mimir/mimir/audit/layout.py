from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..imports import ImportReference, absolute_module, relpath_to_module, resolve_reference
from .astgrep import Match
from .target import Target, Violation, WidthConfig

TS_EXTENSIONS = (".ts", ".tsx")
TS_RESOLVE_SUFFIXES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")
LAYER_EXEMPT_FILES = ("__init__.py",)


@dataclass(frozen=True)
class ImportFact:
  file: str
  line: int
  names: tuple[str, ...]
  resolved: str | None


def dir_entries(target: Target) -> dict[str, set[str]]:
  skips = target.cfg.width.skips
  out: dict[str, set[str]] = defaultdict(set)
  for f in target.files:
    parts = f.split("/")
    hidden = any(p.startswith(".") for p in parts)
    skipped_dir = any(p in skips.dirs for p in parts[:-1])
    if hidden or skipped_dir or parts[-1] in skips.files or parts[-1].endswith(skips.suffixes):
      continue
    for i, part in enumerate(parts):
      out["/".join(parts[:i]) or "."].add(part)
  return out


def check_dir_entries(target: Target) -> list[Violation]:
  counted = dir_entries(target)
  return _too_wide(counted, target.cfg.width) + _stale_allows(counted, target.cfg.width)


def _too_wide(counted: dict[str, set[str]], width: WidthConfig) -> list[Violation]:
  violations: list[Violation] = []
  for d, names in sorted(counted.items()):
    in_scope = any(r == "." or d == r or d.startswith(r + "/") for r in width.roots)
    if not in_scope or d in width.exempt or len(names) <= width.max_entries:
      continue
    allowed = width.allow.get(d)
    if allowed is None or len(names) > allowed:
      limit = width.max_entries if allowed is None else f"{allowed}, allowlisted"
      message = f"{len(names)} entries (max {limit}): {sorted(names)}"
      violations.append(Violation(d, 0, "dir-too-wide", message))
  return violations


def _stale_allows(counted: dict[str, set[str]], width: WidthConfig) -> list[Violation]:
  return [
    Violation(
      d,
      0,
      "dir-allow-stale",
      f"{n} entries <= {width.max_entries}: delete its [tool.mimir.layout.allow] line",
    )
    for d in sorted(width.allow)
    if (n := len(counted.get(d, ()))) <= width.max_entries
  ]


def import_facts(target: Target, matches: list[Match]) -> dict[str, list[ImportFact]]:
  files = set(target.files)
  py_paths = PythonPaths(python_roots(target), frozenset(f for f in files if f.endswith(".py")))
  modules = {relpath_to_module(py_paths.module_path(f)): f for f in py_paths.files}
  out: dict[str, list[ImportFact]] = defaultdict(list)
  for m in matches:
    if m.family != "imports":
      continue
    fact = (
      _python_fact(m, py_paths.module_path(m.file), modules)
      if m.grammar == "python"
      else _ts_fact(m, files)
    )
    if fact is not None:
      out[m.file].append(fact)
  return out


def python_roots(target: Target) -> tuple[str, ...]:
  roots = {lr.root for lr in target.cfg.layers} | set(target.cfg.scope.src)
  return tuple(sorted(r for r in roots if r != "."))


@dataclass(frozen=True)
class PythonPaths:
  roots: tuple[str, ...]
  files: frozenset[str]

  def module_path(self, path: str) -> str:
    candidates = [self._package_top(posixpath.dirname(path))]
    for r in self.roots:
      if path.startswith(r + "/"):
        is_package = f"{r}/__init__.py" in self.files
        candidates.append(self._package_top(r) if is_package else r)
    entry = min(candidates, key=lambda d: 0 if d == "" else d.count("/") + 1)
    return path if entry == "" else posixpath.relpath(path, entry)

  def _package_top(self, directory: str) -> str:
    here = directory
    while here and f"{here}/__init__.py" in self.files:
      here = posixpath.dirname(here)
    return here


def _python_fact(m: Match, anchored: str, modules: dict[str, str]) -> ImportFact | None:
  if m.module is None:
    ref = ImportReference(m.text)
  else:
    level = len(m.module) - len(m.module.lstrip("."))
    names = () if m.text == "*" else (m.text,)
    ref = ImportReference(module=m.module.lstrip("."), names=names, level=level)
  base = absolute_module(anchored, ref)
  if base is None:
    return None
  dotted = (base, *(f"{base}.{n}" if base else n for n in ref.names))
  resolved = resolve_reference(anchored, ref, modules)
  return ImportFact(m.file, m.line, dotted, min(resolved) if resolved else None)


def _ts_fact(m: Match, files: set[str]) -> ImportFact:
  spec = m.text
  if not spec.startswith("."):
    return ImportFact(m.file, m.line, (spec,), None)
  base = posixpath.normpath(posixpath.join(posixpath.dirname(m.file), spec))
  stem = base.removesuffix(".js").removesuffix(".jsx")
  candidates = [base + s for s in TS_RESOLVE_SUFFIXES] + [stem + s for s in TS_EXTENSIONS]
  resolved = next((c for c in candidates if c in files), None)
  names = (spec,) if resolved is None else (spec, _ts_stem(resolved))
  return ImportFact(m.file, m.line, names, resolved)


def _ts_stem(path: str) -> str:
  no_ext = posixpath.splitext(path)[0]
  return no_ext.removesuffix("/index")


def check_layers(target: Target, facts: dict[str, list[ImportFact]]) -> list[Violation]:
  violations: list[Violation] = []
  for layer_root in target.cfg.layers:
    top = layer_root.root + "/"
    rank = {name: i for i, name in enumerate(layer_root.order)}
    for f in target.files:
      if not (f.startswith(top) and _is_layered_code(f)) or f[len(top) :] in LAYER_EXEMPT_FILES:
        continue
      mine = _segment(f, top)
      if mine not in rank:
        message = f"{mine!r} is in no layer of {layer_root.root} {list(layer_root.order)}"
        violations.append(Violation(f, 0, "layer-unranked", message))
        continue
      for fact in facts.get(f, []):
        theirs = _segment(fact.resolved, top) if fact.resolved else None
        if theirs in rank and rank[theirs] > rank[mine]:
          message = f"{mine} imports later layer {fact.resolved}"
          violations.append(Violation(f, fact.line, "layer-order", message))
  return violations


def _is_layered_code(path: str) -> bool:
  return path.endswith((".py", *TS_EXTENSIONS)) and not path.endswith(".d.ts")


def _segment(path: str, top: str) -> str | None:
  if not path.startswith(top):
    return None
  first = path[len(top) :].split("/")[0]
  return first.removesuffix(".py").removesuffix(".tsx").removesuffix(".ts")


def check_boundaries(target: Target, facts: dict[str, list[ImportFact]]) -> list[Violation]:
  listed = set(target.files)
  violations: list[Violation] = []
  for boundary in target.cfg.boundaries:
    matched = sorted(
      rel
      for p in Path(target.root).glob(boundary.src)
      if (rel := p.relative_to(target.root).as_posix()) in listed
    )
    for relpath in matched:
      sep = "." if relpath.endswith(".py") else "/"
      for fact in facts.get(relpath, []):
        hit = next((n for n in fact.names if _under(n, boundary.forbid, sep)), None)
        if hit is not None:
          message = f"{relpath} imports {hit}; forbidden by boundary {boundary.src}"
          violations.append(Violation(relpath, fact.line, "import-boundary", message))
  return violations


def _under(name: str, prefixes: tuple[str, ...], sep: str) -> bool:
  return any(name == p or name.startswith(p + sep) for p in prefixes)
