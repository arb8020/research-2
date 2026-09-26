from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SG_DIR = Path(__file__).parent / "sg"
GRAMMARS = {".py": "python", ".ts": "typescript", ".tsx": "tsx"}
LANGUAGE_GRAMMARS = {"python": ("python",), "typescript": ("typescript", "tsx")}
COMMENT_LEADERS = {"python": "#", "typescript": "//", "tsx": "//"}
REGEX_META = re.compile(r"([\\.^$|?*+()\[\]{}])")
FAMILIES = ("no-comments", "no-docstrings", "citation", "imports")
# One ast-grep process per this many files keeps argv far below ARG_MAX.
MAX_FILES_PER_RUN = 1000
SG_TIMEOUT_SECONDS = 300


class SgError(Exception):
  pass


@dataclass(frozen=True)
class Match:
  family: str
  grammar: str
  file: str
  line: int
  text: str
  module: str | None


def code_files(files: tuple[str, ...], languages: tuple[str, ...]) -> list[str]:
  grammars = {g for lang in languages for g in LANGUAGE_GRAMMARS[lang]}
  return [f for f in files if GRAMMARS.get(os.path.splitext(f)[1]) in grammars]


def render_utils(directives: tuple[str, ...]) -> dict[str, str]:
  alternatives = "|".join(REGEX_META.sub(r"\\\1", d) for d in directives)
  out: dict[str, str] = {}
  for grammar, leader in COMMENT_LEADERS.items():
    regex = f"^{leader}\\s*({alternatives})" if directives else "^$"
    rule = {"id": f"allowed-directive-{grammar}", "language": grammar, "rule": {"regex": regex}}
    out[f"allowed-directive-{grammar}.yml"] = json.dumps(rule) + "\n"
  return out


def scan(
  root: str, files: list[str], families: tuple[str, ...], directives: tuple[str, ...]
) -> list[Match]:
  assert set(families) <= set(FAMILIES), families
  if not files or not families:
    return []
  unreadable = [f for f in files if not _is_utf8(os.path.join(root, f))]
  if unreadable:
    raise SgError(f"ast-grep skips files that are not UTF-8: {unreadable[:20]}")
  sg = _sg_binary()
  with tempfile.TemporaryDirectory(prefix="mimir-sg-") as tmp:
    config = _write_config(Path(tmp), directives)
    rule_filter = f"^({'|'.join(families)})-({'|'.join(COMMENT_LEADERS)})$"
    matches: list[Match] = []
    for start in range(0, len(files), MAX_FILES_PER_RUN):
      chunk = files[start : start + MAX_FILES_PER_RUN]
      cmd = [sg, "scan", "-c", str(config), "--filter", rule_filter, "--hint", "--json=stream"]
      matches.extend(_run(cmd + ["--", *chunk], root))
  return sorted(matches, key=lambda m: (m.file, m.line, m.family, m.text))


def _is_utf8(path: str) -> bool:
  try:
    with open(path, "rb") as f:
      f.read().decode("utf-8")
  except (OSError, UnicodeDecodeError):
    return False
  return True


def _sg_binary() -> str:
  here = Path(sys.executable).parent / "ast-grep"
  if here.is_file():
    return str(here)
  found = shutil.which("ast-grep")
  if found is None:
    raise SgError("ast-grep not found: install mimir with its ast-grep-cli dependency")
  return found


def _write_config(tmp: Path, directives: tuple[str, ...]) -> Path:
  utils = tmp / "utils"
  utils.mkdir()
  for name, text in render_utils(directives).items():
    (utils / name).write_text(text)
  config = tmp / "sgconfig.yml"
  config.write_text(json.dumps({"ruleDirs": [str(SG_DIR / "rules")], "utilDirs": [str(utils)]}))
  return config


def _run(cmd: list[str], root: str) -> list[Match]:
  try:
    result = subprocess.run(
      cmd, cwd=root, capture_output=True, text=True, timeout=SG_TIMEOUT_SECONDS
    )
  except (OSError, subprocess.TimeoutExpired) as e:
    raise SgError(f"ast-grep failed to run: {e}") from e
  if result.returncode != 0:
    raise SgError(f"ast-grep exited {result.returncode}: {result.stderr.strip()[:2000]}")
  return [_parse(json.loads(line)) for line in result.stdout.splitlines() if line.strip()]


def _parse(raw: dict) -> Match:
  family, _, grammar = raw["ruleId"].rpartition("-")
  if family not in FAMILIES or grammar not in COMMENT_LEADERS:
    raise SgError(f"unexpected ast-grep rule id {raw['ruleId']!r}")
  single = (raw.get("metaVariables") or {}).get("single") or {}
  module = single.get("MOD", {}).get("text")
  return Match(
    family=family,
    grammar=grammar,
    file=raw["file"].replace(os.sep, "/"),
    line=raw["range"]["start"]["line"] + 1,
    text=raw["text"],
    module=module,
  )
