from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass
from typing import Any

from ..config import load_tool_mimir
from ..scan import SKIP_DIRS

DEFAULTS: dict[str, int] = {
  "max-function-lines": 70,
  "max-file-lines": 1000,
  "max-nesting": 4,
  "max-cyclomatic": 10,
  "max-args": 6,
  "max-dir-entries": 7,
}

LANGUAGES = ("python", "typescript")
DEFAULT_DIRECTIVES = ("type: ignore[", "noqa:", "fmt: skip", "@ts-expect-error")
DEFAULT_SKIP_FILES = ("__init__.py", "__main__.py")
DEFAULT_SKIP_DIRS = ("tests", "test")
COMMENTS_KEYS = {"enabled", "allow_directives", "citations", "locks"}
LAYOUT_KEYS = {
  "max_dir_entries",
  "dir_roots",
  "exempt",
  "data_trees",
  "skip_dirs",
  "skip_files",
  "skip_suffixes",
  "allow",
  "layers",
}

_DEFAULT_VOID_EXEMPT_METHODS: set[str] = {
  "start",
  "stop",
  "close",
  "reply",
  "upload_file",
  "upload_dir",
  "download_file",
  "download_dir",
  "_validate_definition",
  "_reset_task_workspace",
  "_run_setup_scripts",
  "find_spec",
  "find_module",
  "load_module",
  "do_GET",
  "do_POST",
  "do_PUT",
  "do_DELETE",
  "do_HEAD",
  "do_OPTIONS",
  "log_message",
  "log_request",
}


class ConfigError(Exception):
  pass


@dataclass(frozen=True)
class Boundary:
  src: str
  forbid: tuple[str, ...]


@dataclass(frozen=True)
class LayerRoot:
  root: str
  order: tuple[str, ...]


@dataclass(frozen=True)
class Scope:
  src: tuple[str, ...]
  exclude: tuple[str, ...]
  languages: tuple[str, ...]
  tsconfigs: tuple[str, ...]
  data_trees: tuple[str, ...]


@dataclass(frozen=True)
class StyleConfig:
  max_function_lines: int
  max_file_lines: int
  max_nesting: int
  max_cyclomatic: int
  max_args: int
  check_void_returns: bool
  check_isinstance: bool
  void_exempt_methods: frozenset[str]


@dataclass(frozen=True)
class WidthSkips:
  dirs: tuple[str, ...]
  files: tuple[str, ...]
  suffixes: tuple[str, ...]


@dataclass(frozen=True)
class WidthConfig:
  max_entries: int
  roots: tuple[str, ...]
  exempt: tuple[str, ...]
  skips: WidthSkips
  allow: dict[str, int]


@dataclass(frozen=True)
class CommentsConfig:
  enabled: bool
  allow_directives: tuple[str, ...]
  citations: bool
  locks: tuple[str, ...] | None


@dataclass(frozen=True)
class AuditConfig:
  scope: Scope
  style: StyleConfig
  width: WidthConfig
  comments: CommentsConfig
  boundaries: tuple[Boundary, ...]
  layers: tuple[LayerRoot, ...]


@dataclass(frozen=True)
class Target:
  root: str
  cfg: AuditConfig
  files: tuple[str, ...]


@dataclass
class Violation:
  file: str
  line: int
  kind: str
  message: str


@dataclass
class CheckResult:
  name: str
  passed: bool
  details: str
  violations: list[Violation]
  stats: dict[str, int] | None = None


def load_config(root: str, config_path: str | None = None) -> AuditConfig:
  cfg = load_tool_mimir(root) if config_path is None else _read_config_file(config_path)

  src_raw = cfg.get("src", None)
  if src_raw is None:
    src_raw = _auto_detect_src(root)
  src = tuple(s.rstrip("/") for s in src_raw)
  layout = _table(cfg, "layout", LAYOUT_KEYS)

  languages = _languages(cfg)
  tsconfigs = _strs(cfg, "tsconfigs", ())
  if tsconfigs and "typescript" not in languages:
    raise ConfigError('[tool.mimir] tsconfigs needs "typescript" in languages')
  return AuditConfig(
    scope=Scope(
      src=src,
      exclude=tuple(cfg.get("exclude", [])),
      languages=languages,
      tsconfigs=tsconfigs,
      data_trees=tuple(t.rstrip("/") for t in _strs(layout, "data_trees", ())),
    ),
    style=_style_config(cfg),
    width=_width_config(cfg, layout, src),
    comments=_comments_config(_table(cfg, "comments", COMMENTS_KEYS)),
    boundaries=tuple(
      Boundary(src=b["src"], forbid=tuple(b["forbid"])) for b in cfg.get("boundaries", [])
    ),
    layers=tuple(_layer_root(raw) for raw in layout.get("layers", [])),
  )


def _read_config_file(path: str) -> dict[str, Any]:
  try:
    with open(path, "rb") as f:
      data = tomllib.load(f)
  except (OSError, ValueError) as e:
    raise ConfigError(f"cannot read config {path}: {e}") from e
  cfg = data.get("tool", {}).get("mimir")
  if not isinstance(cfg, dict):
    raise ConfigError(f"{path} has no [tool.mimir] table")
  return cfg


def _table(cfg: dict[str, Any], key: str, allowed: set[str]) -> dict[str, Any]:
  raw = cfg.get(key, {})
  if not isinstance(raw, dict):
    raise ConfigError(f"[tool.mimir.{key}] must be a table")
  unknown = sorted(set(raw) - allowed)
  if unknown:
    raise ConfigError(f"[tool.mimir.{key}] unknown keys {unknown}; known: {sorted(allowed)}")
  return raw


def _strs(cfg: dict[str, Any], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
  raw = cfg.get(key, list(default))
  if not (isinstance(raw, list) and all(isinstance(s, str) for s in raw)):
    raise ConfigError(f"[tool.mimir] {key} must be a list of strings, got {raw!r}")
  return tuple(raw)


def _languages(cfg: dict[str, Any]) -> tuple[str, ...]:
  languages = _strs(cfg, "languages", ("python",))
  unknown = sorted(set(languages) - set(LANGUAGES))
  if unknown:
    raise ConfigError(f"[tool.mimir] languages: unknown {unknown}; known: {list(LANGUAGES)}")
  return languages


def _style_config(cfg: dict[str, Any]) -> StyleConfig:
  return StyleConfig(
    max_function_lines=cfg.get("max-function-lines", DEFAULTS["max-function-lines"]),
    max_file_lines=cfg.get("max-file-lines", DEFAULTS["max-file-lines"]),
    max_nesting=cfg.get("max-nesting", DEFAULTS["max-nesting"]),
    max_cyclomatic=cfg.get("max-cyclomatic", DEFAULTS["max-cyclomatic"]),
    max_args=cfg.get("max-args", DEFAULTS["max-args"]),
    check_void_returns=cfg.get("check-void-returns", True),
    check_isinstance=cfg.get("check-isinstance", False),
    void_exempt_methods=frozenset(
      cfg.get("void-exempt-methods", list(_DEFAULT_VOID_EXEMPT_METHODS))
    ),
  )


def _width_config(cfg: dict[str, Any], layout: dict[str, Any], src: tuple[str, ...]) -> WidthConfig:
  legacy_max = cfg.get("max-dir-entries", DEFAULTS["max-dir-entries"])
  allow = layout.get("allow", {})
  if not all(isinstance(n, int) for n in allow.values()):
    raise ConfigError(f"[tool.mimir.layout.allow] values must be entry counts, got {allow!r}")
  return WidthConfig(
    max_entries=layout.get("max_dir_entries", legacy_max),
    roots=tuple(r.rstrip("/") or "." for r in _strs(layout, "dir_roots", src)),
    exempt=tuple(e.rstrip("/") or "." for e in _strs(layout, "exempt", ())),
    skips=WidthSkips(
      dirs=_strs(layout, "skip_dirs", DEFAULT_SKIP_DIRS),
      files=_strs(layout, "skip_files", DEFAULT_SKIP_FILES),
      suffixes=_strs(layout, "skip_suffixes", ()),
    ),
    allow={d.rstrip("/") or ".": n for d, n in allow.items()},
  )


def _comments_config(raw: dict[str, Any]) -> CommentsConfig:
  locks = _strs(raw, "locks", ()) if "locks" in raw else None
  directives = _strs(raw, "allow_directives", DEFAULT_DIRECTIVES)
  if not all(d.strip() for d in directives):
    raise ConfigError(
      "[tool.mimir.comments] allow_directives: an empty prefix allows every comment"
    )
  enabled = bool(raw.get("enabled", False))
  return CommentsConfig(
    enabled=enabled,
    allow_directives=directives,
    citations=bool(raw.get("citations", enabled)),
    locks=locks,
  )


def _layer_root(raw: Any) -> LayerRoot:
  if not (isinstance(raw, dict) and set(raw) == {"root", "order"}):
    raise ConfigError(f"[[tool.mimir.layout.layers]] needs exactly root and order, got {raw!r}")
  order = _strs(raw, "order", ())
  if len(set(order)) != len(order):
    raise ConfigError(f"[[tool.mimir.layout.layers]] {raw['root']}: duplicate names in order")
  return LayerRoot(root=raw["root"].rstrip("/"), order=order)


def _auto_detect_src(root: str) -> list[str]:
  candidates = []
  for entry in sorted(os.listdir(root)):
    full = os.path.join(root, entry)
    if not os.path.isdir(full):
      continue
    if entry.startswith((".", "_")):
      continue
    if entry in {"build", "dist", "node_modules", "worktrees", "docs", "scripts"}:
      continue
    init = os.path.join(full, "__init__.py")
    if os.path.isfile(init):
      candidates.append(entry)
  return candidates if candidates else ["."]


def list_files(root: str, data_trees: tuple[str, ...]) -> tuple[str, ...]:
  listed = _git_files(root)
  files = _walked_files(root) if listed is None else listed
  trees = tuple(t + "/" for t in data_trees)
  return tuple(sorted(f for f in files if not f.startswith(trees)))


def _git_files(root: str) -> list[str] | None:
  cmd = ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
  try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
  except FileNotFoundError:
    return None
  if result.returncode != 0:
    return None
  names = [f for f in result.stdout.split("\0") if f]
  # --cached lists files deleted from the work tree; they are not there to check.
  return [f for f in names if os.path.isfile(os.path.join(root, f))]


def _walked_files(root: str) -> list[str]:
  out: list[str] = []
  for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
    rel = os.path.relpath(dirpath, root)
    out.extend(fn if rel == "." else f"{rel}/{fn}" for fn in filenames)
  return [f.replace(os.sep, "/") for f in out]
