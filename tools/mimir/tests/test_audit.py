from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mimir.cli import main

UV_LOCK = """
version = 1

[[package]]
name = "httpx"
version = "0.28.1"

[[package]]
name = "Typing_Extensions"
version = "4.12.2"
"""
BUN_LOCK = """{
  "lockfileVersion": 1,
  "packages": {
    "react": ["react@19.1.0", "", {}, "sha512-x"],
    "@types/node": ["@types/node@22.5.0", "", {}, "sha512-y"],
  },
}
"""
PACKAGE_LOCK = {
  "lockfileVersion": 3,
  "packages": {
    "": {"name": "app"},
    "node_modules/left-pad": {"version": "1.3.0"},
    "node_modules/a/node_modules/left-pad": {"version": "1.1.0"},
  },
}


def write(root: Path, files: dict[str, str]) -> Path:
  for rel, text in files.items():
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
  return root


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
  repo = tmp_path / "repo"
  repo.mkdir()
  subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
  return write(repo, files)


def audit(repo: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict]:
  argv_backup = sys.argv
  sys.argv = ["mimir", "audit", str(repo), "--json", *args]
  try:
    main()
  except SystemExit as e:
    code = e.code
  finally:
    sys.argv = argv_backup
  out = capsys.readouterr().out
  assert isinstance(code, int)
  return code, (json.loads(out) if out else {})


def by_check(report: dict) -> dict[str, dict]:
  return {c["name"]: c for c in report["checks"]}


def found(report: dict, check: str) -> list[tuple[str, int, str]]:
  return [(v["file"], v["line"], v["kind"]) for v in by_check(report)[check]["violations"]]


def test_legacy_python_config_width_and_boundaries(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  repo = make_repo(
    tmp_path,
    {
      "pyproject.toml": (
        "[tool.mimir]\nmax-dir-entries = 2\n"
        'boundaries = [{ src = "pkg/core/*.py", forbid = ["pkg.web"] }]\n'
      ),
      "pkg/__init__.py": "",
      "pkg/core/__init__.py": "",
      "pkg/core/a.py": "from pkg.web import handler\n",
      "pkg/core/b.py": "from ..web import handler\n",
      "pkg/core/c.py": "import os\n",
      "pkg/web/__init__.py": "",
      "pkg/web/handler.py": "X = 1\n",
      "pkg/tests/t1.py": "",
      "pkg/tests/t2.py": "",
      "pkg/tests/t3.py": "",
    },
  )
  code, report = audit(repo, capsys, "--only", "directories,boundaries")
  assert code == 1
  assert found(report, "directories") == [("pkg/core", 0, "dir-too-wide")]
  assert found(report, "boundaries") == [
    ("pkg/core/a.py", 1, "import-boundary"),
    ("pkg/core/b.py", 1, "import-boundary"),
  ]


COMMENTED = {
  "pkg/__init__.py": "",
  "pkg/a.py": (
    '"""module docstring"""\n'
    "# plain\n"
    "x = f()  # type: ignore[attr-defined]\n"
    "y = 1  # noqa: E501\n"
    "# EXTERNAL(httpx==0.28.1 httpx/_client.py:1-2): fact\n"
    "def g():\n"
    "  '''function docstring'''\n"
    "  return 1\n"
  ),
  "web/a.ts": "// plain\n// @ts-expect-error: why\nconst s = '// in a string';\n",
  "web/b.tsx": "const e = <div>{/* jsx */}</div>;\n",
}


def test_comments_and_docstrings_python_and_ts(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  config = (
    '[tool.mimir]\nlanguages = ["python", "typescript"]\n[tool.mimir.comments]\nenabled = true\n'
  )
  repo = make_repo(tmp_path, {**COMMENTED, "pyproject.toml": config})
  code, report = audit(repo, capsys, "--only", "comments,docstrings")
  assert code == 1
  assert found(report, "comments") == [
    ("pkg/a.py", 2, "comment"),
    ("web/a.ts", 1, "comment"),
    ("web/b.tsx", 1, "comment"),
  ]
  assert found(report, "docstrings") == [("pkg/a.py", 1, "docstring"), ("pkg/a.py", 7, "docstring")]


def test_allow_directives_come_from_config(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  config = '[tool.mimir]\n[tool.mimir.comments]\nenabled = true\nallow_directives = ["noqa:"]\n'
  repo = make_repo(tmp_path, {**COMMENTED, "pyproject.toml": config})
  _, report = audit(repo, capsys, "--only", "comments")
  assert found(report, "comments") == [("pkg/a.py", 2, "comment"), ("pkg/a.py", 3, "comment")]


CITATIONS = {
  "pyproject.toml": (
    '[tool.mimir]\nlanguages = ["python", "typescript"]\n[tool.mimir.comments]\ncitations = true\n'
  ),
  "uv.lock": UV_LOCK,
  "app/bun.lock": BUN_LOCK,
  "legacy/package-lock.json": json.dumps(PACKAGE_LOCK),
  "pkg/__init__.py": "",
  "pkg/a.py": (
    "# EXTERNAL(httpx==0.28.1 httpx/_client.py:10-20): locked\n"
    "# EXTERNAL(typing-extensions==4.12.2 typing_extensions.py:1-2): normalized name\n"
    "# EXTERNAL(httpx==0.27.0 httpx/_client.py:10-20): stale\n"
    "# EXTERNAL(requests==2.0.0 requests/api.py:1-2): not locked\n"
    "# EXTERNAL(httpx 0.28.1): malformed\n"
    "# EXTERNAL(encode/httpx@0123abc httpx/_client.py:L1-L9): git\n"
    "# EXTERNAL(https://peps.python.org/pep-0503/ @2026-09-25): url\n"
    "# EXTERNAL(https://example.com @2026-13-45): not a date\n"
  ),
  "app/src/x.ts": (
    "// EXTERNAL(react==19.1.0 index.js:1-2): bun\n"
    "// EXTERNAL(@types/node==22.5.0 index.d.ts:1-2): scoped\n"
    "// EXTERNAL(left-pad==1.1.0 index.js:1-2): nested package-lock entry\n"
    "/* EXTERNAL(react==19.1.0 index.js:1-2): block comments are not citations */\n"
  ),
}


def test_citations_checked_against_every_lockfile(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  repo = make_repo(tmp_path, CITATIONS)
  code, report = audit(repo, capsys, "--only", "citations")
  assert code == 1
  assert found(report, "citations") == [
    ("pkg/a.py", 3, "citation"),
    ("pkg/a.py", 4, "citation"),
    ("pkg/a.py", 5, "citation"),
    ("pkg/a.py", 8, "citation"),
  ]
  assert by_check(report)["citations"]["stats"] == {
    "@types/node": 1,
    "encode/httpx": 1,
    "httpx": 1,
    "left-pad": 1,
    "peps.python.org": 1,
    "react": 1,
    "typing-extensions": 1,
  }


def test_configured_locks_replace_discovery(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  files = {**CITATIONS, "pkg/a.py": "# EXTERNAL(httpx==0.28.1 httpx/_client.py:10-20): x\n"}
  files["pyproject.toml"] += 'locks = ["app/bun.lock", "missing/uv.lock"]\n'
  repo = make_repo(tmp_path, files)
  _, report = audit(repo, capsys, "--only", "citations")
  messages = {v["file"]: v["message"] for v in by_check(report)["citations"]["violations"]}
  assert "no lockfile has httpx" in messages["pkg/a.py"]
  assert "locks: app/bun.lock" in by_check(report)["citations"]["details"]


def test_layers_python_and_ts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  config = (
    '[tool.mimir]\nlanguages = ["python", "typescript"]\n'
    '[[tool.mimir.layout.layers]]\nroot = "src/app"\norder = ["store", "api", "__main__"]\n'
    '[[tool.mimir.layout.layers]]\nroot = "web/src"\norder = ["lib", "ui"]\n'
  )
  repo = make_repo(
    tmp_path,
    {
      "pyproject.toml": config,
      "src/app/__init__.py": "from app.api import routes\n",
      "src/app/__main__.py": "from app.api import routes\n",
      "src/app/store.py": "from app.api.routes import handler\nfrom . import api\n",
      "src/app/api/__init__.py": "",
      "src/app/api/routes.py": "from ..store import x\nfrom app import __main__\n",
      "src/app/misc.py": "",
      "web/src/lib/util.ts": "import { V } from '../ui/view';\nexport const u = 1;\n",
      "web/src/lib/types.d.ts": "export type T = 1;\n",
      "web/src/ui/view.tsx": "import { u } from '../lib/util.js';\nexport const V = u;\n",
      "web/src/other.ts": "export const o = 1;\n",
    },
  )
  code, report = audit(repo, capsys, "--only", "layers")
  assert code == 1
  assert found(report, "layers") == [
    ("src/app/api/routes.py", 2, "layer-order"),
    ("src/app/misc.py", 0, "layer-unranked"),
    ("src/app/store.py", 1, "layer-order"),
    ("src/app/store.py", 2, "layer-order"),
    ("web/src/lib/util.ts", 1, "layer-order"),
    ("web/src/other.ts", 0, "layer-unranked"),
  ]


def test_ts_boundaries_match_specifiers_and_paths(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  config = (
    '[tool.mimir]\nlanguages = ["typescript"]\n'
    'boundaries = [{ src = "web/lib/*.ts", forbid = ["react", "web/ui"] }]\n'
  )
  repo = make_repo(
    tmp_path,
    {
      "pyproject.toml": config,
      "web/lib/a.ts": "import React from 'react';\nimport { x } from 'react-dom';\n",
      "web/lib/b.ts": "export * from '../ui';\nconst m = await import('react/jsx-runtime');\n",
      "web/ui/index.tsx": "export const x = 1;\n",
    },
  )
  _, report = audit(repo, capsys, "--only", "boundaries")
  assert found(report, "boundaries") == [
    ("web/lib/a.ts", 1, "import-boundary"),
    ("web/lib/b.ts", 1, "import-boundary"),
    ("web/lib/b.ts", 2, "import-boundary"),
  ]


def test_width_layout_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  config = (
    "[tool.mimir]\n[tool.mimir.layout]\nmax_dir_entries = 2\n"
    'dir_roots = ["."]\nexempt = ["."]\ndata_trees = ["tests/fixtures"]\nskip_dirs = []\n'
    'skip_suffixes = [".d.ts"]\n'
    '[tool.mimir.layout.allow]\n"wide" = 3\n"grew" = 3\n"narrow" = 3\n'
  )
  repo = make_repo(
    tmp_path,
    {
      "pyproject.toml": config,
      "a.py": "",
      "b.py": "",
      "c.py": "",
      "wide/1": "",
      "wide/2": "",
      "wide/3": "",
      "grew/1": "",
      "grew/2": "",
      "grew/3": "",
      "grew/4": "",
      "narrow/1": "",
      "tests/fixtures/1": "",
      "tests/fixtures/2": "",
      "tests/fixtures/3": "",
      "tests/t1.py": "",
      "tests/t2.py": "",
      "tests/t3.py": "",
      "types/a.d.ts": "",
      "types/b.d.ts": "",
      "types/c.d.ts": "",
      "ignored/.gitignore": "*\n",
      "ignored/1": "",
      "ignored/2": "",
      "ignored/3": "",
    },
  )
  _, report = audit(repo, capsys, "--only", "directories")
  assert found(report, "directories") == [
    ("grew", 0, "dir-too-wide"),
    ("tests", 0, "dir-too-wide"),
    ("narrow", 0, "dir-allow-stale"),
  ]


def test_data_trees_are_not_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  config = (
    "[tool.mimir]\n[tool.mimir.comments]\nenabled = true\n"
    '[tool.mimir.layout]\ndata_trees = ["tests/fixtures"]\n'
  )
  repo = make_repo(
    tmp_path,
    {"pyproject.toml": config, "tests/fixtures/x.py": "# fixture\n", "tests/t.py": "# real\n"},
  )
  _, report = audit(repo, capsys, "--only", "comments")
  assert found(report, "comments") == [("tests/t.py", 1, "comment")]


def test_tsc_runs_the_projects_own_compiler(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  config = '[tool.mimir]\nlanguages = ["typescript"]\ntsconfigs = ["app/tsconfig.json"]\n'
  repo = make_repo(
    tmp_path,
    {
      "pyproject.toml": config,
      "app/tsconfig.json": "{}",
      "app/node_modules/.bin/tsc": '#!/bin/sh\necho "fake tsc $@"; exit 2\n',
    },
  )
  os.chmod(repo / "app/node_modules/.bin/tsc", 0o755)
  code, report = audit(repo, capsys, "--only", "tsc")
  assert code == 1
  assert by_check(report)["tsc"]["passed"] is False
  assert "fake tsc --noEmit -p" in by_check(report)["tsc"]["details"]


@pytest.mark.parametrize(
  ("config", "args"),
  [
    ("[tool.mimir]\n", ("--only", "nope")),
    ("[tool.mimir]\n", ("--only", "tsc")),
    ("[tool.mimir.comments]\nenabeld = true\n", ()),
    ('[tool.mimir]\nlanguages = ["rust"]\n', ()),
    ('[[tool.mimir.layout.layers]]\nroot = "a"\n', ()),
  ],
)
def test_misconfiguration_exits_2(
  tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str, args: tuple[str, ...]
) -> None:
  repo = make_repo(tmp_path, {"pyproject.toml": config})
  code, report = audit(repo, capsys, *args)
  assert code == 2
  assert report == {}


def test_config_flag_reads_another_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path, {"a/1": "", "a/2": "", "a/3": ""})
  config = write(
    tmp_path, {"cfg.toml": '[tool.mimir.layout]\nmax_dir_entries = 2\ndir_roots = ["."]\n'}
  )
  code, report = audit(repo, capsys, "--only", "directories", "--config", str(config / "cfg.toml"))
  assert code == 1
  assert found(report, "directories") == [("a", 0, "dir-too-wide")]


def test_nested_layer_root_and_src_layout_resolve_full_module_names(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  config = (
    '[tool.mimir]\nsrc = ["pkg", "src"]\n'
    'boundaries = [{ src = "src/app/api/*.py", forbid = ["app.db"] }]\n'
    '[[tool.mimir.layout.layers]]\nroot = "pkg/core"\norder = ["a", "b"]\n'
  )
  repo = make_repo(
    tmp_path,
    {
      "pyproject.toml": config,
      "pkg/__init__.py": "",
      "pkg/core/__init__.py": "",
      "pkg/core/a/__init__.py": "",
      "pkg/core/a/x.py": "from pkg.core.b import y\n",
      "pkg/core/b/__init__.py": "",
      "pkg/core/b/y.py": "",
      "src/app/__init__.py": "",
      "src/app/db.py": "",
      "src/app/api/__init__.py": "",
      "src/app/api/h.py": "from ..db import conn\n",
    },
  )
  _, report = audit(repo, capsys, "--only", "layers,boundaries")
  assert found(report, "layers") == [("pkg/core/a/x.py", 1, "layer-order")]
  assert found(report, "boundaries") == [("src/app/api/h.py", 1, "import-boundary")]


def test_enabled_comments_validate_citations_by_default(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  config = "[tool.mimir]\n[tool.mimir.comments]\nenabled = true\n"
  repo = make_repo(tmp_path, {"pyproject.toml": config, "a.py": "# EXTERNAL(any prose)\n"})
  _, report = audit(repo, capsys, "--only", "comments,citations")
  assert found(report, "comments") == []
  assert found(report, "citations") == [("a.py", 1, "citation")]


def test_non_utf8_code_fails_instead_of_being_skipped(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  repo = make_repo(tmp_path, {"pyproject.toml": "[tool.mimir.comments]\nenabled = true\n"})
  (repo / "latin.py").write_bytes("# caf\xe9\n".encode("latin-1"))
  code, report = audit(repo, capsys, "--only", "comments")
  assert code == 1
  assert "not UTF-8" in by_check(report)["comments"]["details"]


@pytest.mark.parametrize(
  "config",
  [
    '[tool.mimir.comments]\nallow_directives = [""]\n',
    '[tool.mimir]\ntsconfigs = ["tsconfig.json"]\n',
  ],
)
def test_configs_that_would_silently_pass_exit_2(
  tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str
) -> None:
  repo = make_repo(tmp_path, {"pyproject.toml": config})
  code, _ = audit(repo, capsys, "--only", "directories")
  assert code == 2


def test_empty_only_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path, {})
  code, _ = audit(repo, capsys, "--only", ",")
  assert code == 2
